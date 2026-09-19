"""
The core LangGraph workflow.

    ingest_ticket -> analyze_bug -> generate_patch -> validate_syntax -> compliance_check
                                          ^                                      |
                                          |                 fail (retries left)  |
                                          +---------------- prepare_retry <------+
                                                                                  |
                                                        pass -> create_pr -> END  |
                                                        fail (retries exhausted) -> mark_failed -> END

Two agents are represented here:
  1. The "fixer" (analyze_bug / generate_patch) that reads the ticket + code and writes a patch.
  2. The "auditor" (compliance_check), which calls the *isolated* compliance MCP
     server and never touches GitHub -- it only ever returns findings.

`route_after_checks` is the feedback loop: syntax or policy failures get
turned into structured feedback and routed back into generate_patch, up to
max_retries, before the run is marked failed.
"""

from langgraph.graph import END, StateGraph

from . import mcp_clients as mcp
from .llm import get_llm
from .state import AgentState

llm = get_llm()

SYSTEM_ANALYZE = (
    "ANALYZE: You are a senior engineer triaging a bug ticket against a real "
    "source file. In 2-4 sentences, state the precise root cause. Do not propose "
    "the fix yet, just the diagnosis."
)

SYSTEM_PATCH = (
    "PATCH: You are a senior engineer fixing a bug. Return ONLY the complete, "
    "corrected file content -- no explanations, no markdown code fences, no "
    "commentary. Preserve everything in the file that isn't related to the bug."
)


def ingest_ticket(state: AgentState) -> AgentState:
    ticket = state["ticket"]
    path = ticket.get("file_hint")
    if not path:
        files = mcp.call_github_tool("list_files", extension=".py")
        path = files[0] if files else "app/calculator.py"

    file_data = mcp.call_github_tool("get_file_content", path=path)

    state["target_path"] = path
    state["original_code"] = file_data["content"]
    state["retry_count"] = 0
    state["max_retries"] = state.get("max_retries", 3)
    state["feedback"] = ""
    state["status"] = "ingested"
    return state


def analyze_bug(state: AgentState) -> AgentState:
    user = (
        f"TICKET: {state['ticket']['title']}\n{state['ticket']['body']}\n\n"
        f"FILE ({state['target_path']}):\n{state['original_code']}"
    )
    state["analysis"] = llm.complete(SYSTEM_ANALYZE, user)
    state["status"] = "analyzed"
    return state


def generate_patch(state: AgentState) -> AgentState:
    feedback_block = (
        f"PREVIOUS ATTEMPT WAS REJECTED. Fix these specific issues:\n{state['feedback']}\n\n"
        if state.get("feedback")
        else ""
    )
    user = (
        f"TICKET: {state['ticket']['title']}\n{state['ticket']['body']}\n\n"
        f"ANALYSIS:\n{state['analysis']}\n\n"
        f"{feedback_block}"
        f"CURRENT FILE CONTENT:\n{state['original_code']}"
    )
    patched = llm.complete(SYSTEM_PATCH, user)
    state["patched_code"] = patched.strip("\n") + "\n"
    state["diff"] = mcp.call_github_tool(
        "generate_diff",
        path=state["target_path"],
        original=state["original_code"],
        patched=state["patched_code"],
    )
    state["status"] = "patched"
    return state


def validate_syntax(state: AgentState) -> AgentState:
    result = mcp.call_compliance_tool("check_syntax", code=state["patched_code"])
    state["syntax_ok"] = result["ok"]
    state["syntax_error"] = result.get("error")
    return state


def compliance_check(state: AgentState) -> AgentState:
    static = mcp.call_compliance_tool(
        "run_static_analysis", code=state["patched_code"], filename=state["target_path"].split("/")[-1]
    )
    style = mcp.call_compliance_tool("check_style_guide", code=state["patched_code"])
    security = mcp.call_compliance_tool("check_security_rules", code=state["patched_code"])

    state["static_issues"] = static.get("issues", [])
    state["style_violations"] = style.get("violations", [])
    state["security_findings"] = security.get("findings", [])
    state["compliance_passed"] = style.get("passed", True) and security.get("passed", True)
    state["status"] = "audited"
    return state


def route_after_checks(state: AgentState) -> str:
    if state["syntax_ok"] and state["compliance_passed"]:
        return "create_pr"
    if state["retry_count"] >= state["max_retries"]:
        return "fail"
    return "retry"


def prepare_retry(state: AgentState) -> AgentState:
    lines = []
    if not state["syntax_ok"]:
        lines.append(f"- Syntax error: {state['syntax_error']}")
    for v in state.get("style_violations", []):
        if v["severity"] == "error":
            lines.append(f"- Style violation [{v['rule']}]: {v['message']}")
    for f in state.get("security_findings", []):
        lines.append(f"- Security finding [{f['rule']}]: {f['message']}")

    state["feedback"] = "\n".join(lines)
    state["retry_count"] += 1
    state["status"] = f"retrying ({state['retry_count']}/{state['max_retries']})"
    return state


def create_pr(state: AgentState) -> AgentState:
    branch = f"agent/fix-{state['ticket']['id']}"
    state["branch_name"] = branch

    mcp.call_github_tool("create_branch", branch_name=branch)
    mcp.call_github_tool(
        "commit_and_push",
        path=state["target_path"],
        content=state["patched_code"],
        message=f"Fix: {state['ticket']['title']}",
        branch_name=branch,
    )

    pr_body = (
        f"## Automated fix\n\n"
        f"**Ticket:** {state['ticket']['title']}\n\n"
        f"**Root cause analysis:**\n{state['analysis']}\n\n"
        f"**Retries needed:** {state['retry_count']}\n\n"
        f"**Diff:**\n```diff\n{state['diff']}```\n\n"
        f"**Compliance:** style_ok={not any(v['severity']=='error' for v in state['style_violations'])}, "
        f"security_ok={not state['security_findings']}"
    )
    result = mcp.call_github_tool(
        "open_pull_request",
        branch_name=branch,
        title=f"[Auto-fix] {state['ticket']['title']}",
        body=pr_body,
    )
    state["pr_url"] = result["url"]
    state["status"] = "pr_created"
    return state


def mark_failed(state: AgentState) -> AgentState:
    state["status"] = "failed_after_max_retries"
    return state


def build_graph():
    g = StateGraph(AgentState)

    g.add_node("ingest_ticket", ingest_ticket)
    g.add_node("analyze_bug", analyze_bug)
    g.add_node("generate_patch", generate_patch)
    g.add_node("validate_syntax", validate_syntax)
    g.add_node("compliance_check", compliance_check)
    g.add_node("prepare_retry", prepare_retry)
    g.add_node("create_pr", create_pr)
    g.add_node("mark_failed", mark_failed)

    g.set_entry_point("ingest_ticket")
    g.add_edge("ingest_ticket", "analyze_bug")
    g.add_edge("analyze_bug", "generate_patch")
    g.add_edge("generate_patch", "validate_syntax")
    g.add_edge("validate_syntax", "compliance_check")
    g.add_conditional_edges(
        "compliance_check",
        route_after_checks,
        {"create_pr": "create_pr", "retry": "prepare_retry", "fail": "mark_failed"},
    )
    g.add_edge("prepare_retry", "generate_patch")
    g.add_edge("create_pr", END)
    g.add_edge("mark_failed", END)

    return g.compile()
