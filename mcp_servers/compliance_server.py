from dotenv import load_dotenv
load_dotenv()
import sys
if sys.platform == "win32":
    for _stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass



import ast
import json
import os
import re
import subprocess
import tempfile

import yaml
from fastmcp import FastMCP

mcp = FastMCP("compliance-server")

POLICY_PATH = os.environ.get("POLICY_PATH", "config/policies.yaml")


def _load_policies() -> dict:
    with open(POLICY_PATH) as f:
        return yaml.safe_load(f) or {}


@mcp.tool()
def check_syntax(code: str) -> dict:
    """Parse the code with ast to catch syntax regressions before anything else runs."""
    try:
        ast.parse(code)
        return {"ok": True, "error": None}
    except SyntaxError as e:
        return {"ok": False, "error": f"{e.msg} (line {e.lineno})"}


@mcp.tool()
def run_static_analysis(code: str, filename: str = "patched.py") -> dict:
    """Run ruff (lint) and bandit (security) against the patched code, if installed."""
    issues: list[dict] = []
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, filename)
        with open(path, "w") as f:
            f.write(code)

        try:
            r = subprocess.run(
                ["ruff", "check", path, "--output-format=json"],
                capture_output=True, text=True, timeout=20,
            )
            if r.stdout.strip():
                for item in json.loads(r.stdout):
                    issues.append({
                        "tool": "ruff",
                        "code": item.get("code"),
                        "message": item.get("message"),
                        "line": item.get("location", {}).get("row"),
                    })
        except FileNotFoundError:
            issues.append({"tool": "ruff", "note": "ruff not installed, skipped"})
        except Exception as e:  # noqa: BLE001 - report, don't crash the audit
            issues.append({"tool": "ruff", "error": str(e)})

        try:
            b = subprocess.run(
                ["bandit", "-f", "json", "-q", path],
                capture_output=True, text=True, timeout=20,
            )
            if b.stdout.strip():
                data = json.loads(b.stdout)
                for res in data.get("results", []):
                    issues.append({
                        "tool": "bandit",
                        "code": res.get("test_id"),
                        "message": res.get("issue_text"),
                        "line": res.get("line_number"),
                        "severity": res.get("issue_severity"),
                    })
        except FileNotFoundError:
            issues.append({"tool": "bandit", "note": "bandit not installed, skipped"})
        except Exception as e:  # noqa: BLE001
            issues.append({"tool": "bandit", "error": str(e)})

    blocking = [i for i in issues if "note" not in i and "error" not in i]
    return {"issues": issues, "clean": len(blocking) == 0}


@mcp.tool()
def check_style_guide(code: str) -> dict:
    """Check code against company style rules defined in policies.yaml."""
    policies = _load_policies()
    violations = []
    for rule in policies.get("style_rules", []):
        if re.search(rule["pattern"], code):
            violations.append({"rule": rule["name"], "message": rule["message"], "severity": rule.get("severity", "warning")})
    passed = not any(v["severity"] == "error" for v in violations)
    return {"violations": violations, "passed": passed}


@mcp.tool()
def check_security_rules(code: str) -> dict:
    """Check code against company security rules defined in policies.yaml."""
    policies = _load_policies()
    findings = []
    for rule in policies.get("security_rules", []):
        if re.search(rule["pattern"], code):
            findings.append({"rule": rule["name"], "message": rule["message"], "severity": rule.get("severity", "error")})
    return {"findings": findings, "passed": len(findings) == 0}


if __name__ == "__main__":
    mcp.run()
