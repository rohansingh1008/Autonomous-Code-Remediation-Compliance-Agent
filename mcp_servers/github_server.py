"""
FastMCP server: GitHub tool interface for the remediation agent.

Two modes, chosen automatically:
  - REAL mode:  GITHUB_TOKEN + GITHUB_REPO are set -> talks to the real GitHub REST API.
  - LOCAL mode: not set -> operates on a local git checkout at LOCAL_REPO_PATH
                (defaults to ./demo_repo) and simulates branch/commit/PR on disk.

This lets the exact same agent graph run either as a real coding agent against
a GitHub repo, or as a fully offline, zero-credential demo.
"""

import base64
import difflib
import json
import os
import subprocess

from fastmcp import FastMCP

mcp = FastMCP("github-server")

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO")  # "owner/repo"
LOCAL_REPO_PATH = os.environ.get("LOCAL_REPO_PATH", "./demo_repo")
TICKETS_DIR = os.environ.get("TICKETS_DIR", os.path.join(LOCAL_REPO_PATH, "tickets"))
PR_OUTPUT_DIR = os.environ.get("PR_OUTPUT_DIR", "./pr_output")

API_ROOT = "https://api.github.com"


def _use_real_github() -> bool:
    return bool(GITHUB_TOKEN and GITHUB_REPO)


def _gh_headers() -> dict:
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }


def _run_git(args: list[str]) -> subprocess.CompletedProcess:
    # Ensure the local demo repo is an actual git repo (idempotent).
    if not os.path.isdir(os.path.join(LOCAL_REPO_PATH, ".git")):
        subprocess.run(["git", "init", "-q"], cwd=LOCAL_REPO_PATH)
        subprocess.run(["git", "add", "-A"], cwd=LOCAL_REPO_PATH)
        subprocess.run(
            ["git", "-c", "user.email=agent@example.com", "-c", "user.name=RemediationAgent",
             "commit", "-q", "-m", "initial demo repo state"],
            cwd=LOCAL_REPO_PATH,
        )
    return subprocess.run(["git"] + args, cwd=LOCAL_REPO_PATH, capture_output=True, text=True)


@mcp.tool()
def get_open_tickets() -> list[dict]:
    """List open bug tickets to work on.

    REAL mode: GitHub issues labeled 'bug'. LOCAL mode: JSON files in TICKETS_DIR.
    """
    if _use_real_github():
        import requests

        r = requests.get(
            f"{API_ROOT}/repos/{GITHUB_REPO}/issues",
            headers=_gh_headers(),
            params={"state": "open", "labels": "bug"},
            timeout=20,
        )
        r.raise_for_status()
        return [
            {"id": i["number"], "title": i["title"], "body": i.get("body") or "", "file_hint": None}
            for i in r.json()
            if "pull_request" not in i
        ]

    out = []
    if os.path.isdir(TICKETS_DIR):
        for fn in sorted(os.listdir(TICKETS_DIR)):
            if fn.endswith(".json"):
                with open(os.path.join(TICKETS_DIR, fn)) as f:
                    out.append(json.load(f))
    return out


@mcp.tool()
def list_files(extension: str = ".py") -> list[str]:
    """List repo files with a given extension, used when a ticket has no explicit file hint."""
    if _use_real_github():
        import requests

        r = requests.get(f"{API_ROOT}/repos/{GITHUB_REPO}/git/trees/HEAD?recursive=1", headers=_gh_headers(), timeout=20)
        r.raise_for_status()
        return [item["path"] for item in r.json().get("tree", []) if item["type"] == "blob" and item["path"].endswith(extension)]

    matches = []
    for root, dirs, files in os.walk(LOCAL_REPO_PATH):
        dirs[:] = [d for d in dirs if d != ".git"]
        for fn in files:
            if fn.endswith(extension):
                matches.append(os.path.relpath(os.path.join(root, fn), LOCAL_REPO_PATH))
    return matches


@mcp.tool()
def get_file_content(path: str) -> dict:
    """Retrieve a file's current content and (for REAL mode) its git blob sha."""
    if _use_real_github():
        import requests

        r = requests.get(f"{API_ROOT}/repos/{GITHUB_REPO}/contents/{path}", headers=_gh_headers(), timeout=20)
        r.raise_for_status()
        data = r.json()
        return {"path": path, "content": base64.b64decode(data["content"]).decode(), "sha": data["sha"]}

    full = os.path.join(LOCAL_REPO_PATH, path)
    with open(full) as f:
        return {"path": path, "content": f.read(), "sha": None}


@mcp.tool()
def generate_diff(path: str, original: str, patched: str) -> str:
    """Produce a unified diff between the original and patched file content."""
    diff = difflib.unified_diff(
        original.splitlines(keepends=True),
        patched.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    )
    return "".join(diff)


@mcp.tool()
def create_branch(branch_name: str) -> dict:
    """Create a new branch off the default branch (main)."""
    if _use_real_github():
        import requests

        base = requests.get(f"{API_ROOT}/repos/{GITHUB_REPO}/git/ref/heads/main", headers=_gh_headers(), timeout=20).json()
        sha = base["object"]["sha"]
        r = requests.post(
            f"{API_ROOT}/repos/{GITHUB_REPO}/git/refs",
            headers=_gh_headers(),
            json={"ref": f"refs/heads/{branch_name}", "sha": sha},
            timeout=20,
        )
        return {"ok": r.status_code in (200, 201), "branch": branch_name}

    _run_git(["checkout", "main"]) if _branch_exists("main") else None
    r = _run_git(["checkout", "-b", branch_name])
    return {"ok": r.returncode == 0, "branch": branch_name, "log": (r.stdout + r.stderr).strip()}


def _branch_exists(name: str) -> bool:
    r = subprocess.run(["git", "rev-parse", "--verify", name], cwd=LOCAL_REPO_PATH, capture_output=True)
    return r.returncode == 0


@mcp.tool()
def commit_and_push(path: str, content: str, message: str, branch_name: str) -> dict:
    """Write the patched file and commit it (REAL mode: via Contents API; LOCAL mode: via git commit)."""
    if _use_real_github():
        import requests

        cur = requests.get(f"{API_ROOT}/repos/{GITHUB_REPO}/contents/{path}", headers=_gh_headers(),
                            params={"ref": "main"}, timeout=20)
        sha = cur.json().get("sha") if cur.status_code == 200 else None
        payload = {"message": message, "content": base64.b64encode(content.encode()).decode(), "branch": branch_name}
        if sha:
            payload["sha"] = sha
        r = requests.put(f"{API_ROOT}/repos/{GITHUB_REPO}/contents/{path}", headers=_gh_headers(), json=payload, timeout=20)
        return {"ok": r.status_code in (200, 201)}

    full = os.path.join(LOCAL_REPO_PATH, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as f:
        f.write(content)
    _run_git(["add", path])
    r = _run_git(["-c", "user.email=agent@example.com", "-c", "user.name=RemediationAgent", "commit", "-m", message])
    return {"ok": True, "log": (r.stdout + r.stderr).strip()}


@mcp.tool()
def open_pull_request(branch_name: str, title: str, body: str) -> dict:
    """Open a PR (REAL mode) or write a PR description file to PR_OUTPUT_DIR (LOCAL mode)."""
    if _use_real_github():
        import requests

        r = requests.post(
            f"{API_ROOT}/repos/{GITHUB_REPO}/pulls",
            headers=_gh_headers(),
            json={"title": title, "head": branch_name, "base": "main", "body": body},
            timeout=20,
        )
        r.raise_for_status()
        return {"url": r.json()["html_url"]}

    os.makedirs(PR_OUTPUT_DIR, exist_ok=True)
    safe_name = branch_name.replace("/", "_")
    fname = os.path.join(PR_OUTPUT_DIR, f"{safe_name}.md")
    with open(fname, "w") as f:
        f.write(f"# {title}\n\n**Branch:** `{branch_name}`\n\n{body}\n")
    return {"url": f"file://{os.path.abspath(fname)}"}


if __name__ == "__main__":
    mcp.run()
