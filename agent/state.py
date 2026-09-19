from typing import Optional, TypedDict


class AgentState(TypedDict, total=False):
    ticket: dict
    target_path: str
    original_code: str

    analysis: str
    patched_code: str
    diff: str

    syntax_ok: bool
    syntax_error: Optional[str]
    static_issues: list
    style_violations: list
    security_findings: list
    compliance_passed: bool

    feedback: str
    retry_count: int
    max_retries: int

    branch_name: str
    pr_url: Optional[str]
    status: str
