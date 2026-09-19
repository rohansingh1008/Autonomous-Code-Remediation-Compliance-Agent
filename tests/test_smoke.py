import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.llm import MockLLM  # noqa: E402


def test_policies_file_exists():
    assert os.path.exists(os.path.join("config", "policies.yaml"))


def test_demo_repo_files_exist():
    assert os.path.exists(os.path.join("demo_repo", "app", "calculator.py"))
    assert os.path.exists(os.path.join("demo_repo", "tickets", "ticket_001.json"))


def test_mock_llm_analyzes():
    llm = MockLLM()
    out = llm.complete("ANALYZE: ...", "TICKET: ZeroDivisionError\nFILE:\ndef divide(a,b): return a/b")
    assert "ZeroDivisionError" in out or "zero" in out.lower()


def test_mock_llm_patches_divide_by_zero_bug():
    llm = MockLLM()
    original = "def divide(a, b):\n    return a / b\n"
    user = f"CURRENT FILE CONTENT:\n{original}"
    patched = llm.complete("PATCH: ...", user)
    assert "if b == 0" in patched
    assert "raise ValueError" in patched


def test_mock_llm_is_idempotent_on_already_patched_code():
    llm = MockLLM()
    already_patched = (
        "def divide(a, b):\n"
        "    if b == 0:\n"
        "        raise ValueError(\"b must not be zero\")\n"
        "    return a / b\n"
    )
    user = f"CURRENT FILE CONTENT:\n{already_patched}"
    patched = llm.complete("PATCH: ...", user)
    assert patched.count("if b == 0") == 1
