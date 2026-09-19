"""
CLI entrypoint for the autonomous code remediation & compliance agent.

Usage:
    python main.py                     # run against the first open ticket
    python main.py --ticket-id 1       # run a specific ticket by id/number
    python main.py --max-retries 5     # allow more self-correction attempts
"""

import argparse

from agent import mcp_clients as mcp
from agent.graph import build_graph


def main():
    parser = argparse.ArgumentParser(description="Autonomous code remediation & compliance agent")
    parser.add_argument("--ticket-id", type=int, default=None, help="Specific ticket/issue number to work")
    parser.add_argument("--max-retries", type=int, default=3, help="Max self-correction attempts before giving up")
    args = parser.parse_args()

    print("Fetching open tickets...")
    tickets = mcp.call_github_tool("get_open_tickets")
    if not tickets:
        print("No open tickets found. (Local mode: check demo_repo/tickets/*.json)")
        return

    if args.ticket_id is None:
        ticket = tickets[0]
    else:
        matches = [t for t in tickets if t["id"] == args.ticket_id]
        if not matches:
            print(f"No open ticket with id {args.ticket_id}")
            return
        ticket = matches[0]

    print(f"Working ticket #{ticket['id']}: {ticket['title']}\n")

    graph = build_graph()
    final_state = graph.invoke({"ticket": ticket, "max_retries": args.max_retries})

    print("\n=== RUN SUMMARY ===")
    print(f"Status:        {final_state['status']}")
    print(f"File:          {final_state.get('target_path')}")
    print(f"Retries used:  {final_state['retry_count']}/{final_state['max_retries']}")
    if final_state.get("pr_url"):
        print(f"PR:            {final_state['pr_url']}")
    if not final_state.get("syntax_ok", True):
        print(f"Syntax error:  {final_state.get('syntax_error')}")
    if final_state.get("style_violations"):
        print(f"Style issues:  {final_state['style_violations']}")
    if final_state.get("security_findings"):
        print(f"Security:      {final_state['security_findings']}")

    print("\n--- Diff ---")
    print(final_state.get("diff", "(none)"))


if __name__ == "__main__":
    main()
