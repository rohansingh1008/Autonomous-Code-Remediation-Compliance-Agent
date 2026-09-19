"""
LLM abstraction used by the agent graph.

- AnthropicLLM: real calls to the Anthropic Messages API.
- MockLLM: a small deterministic stand-in used automatically when no API key
  is configured, so the *entire pipeline* (ingest -> analyze -> patch ->
  validate -> comply -> PR) can be demoed with zero credentials. It knows how
  to fix the bundled demo bug (a ZeroDivisionError) and safely no-ops
  otherwise. Swap in the real LLM by setting ANTHROPIC_API_KEY.
"""

import os


class LLMClient:
    def complete(self, system: str, user: str) -> str:
        raise NotImplementedError


class AnthropicLLM(LLMClient):
    def __init__(self, model: str | None = None):
        import anthropic

        self.client = anthropic.Anthropic()
        self.model = model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

    def complete(self, system: str, user: str) -> str:
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=4000,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(block.text for block in resp.content if block.type == "text")


class MockLLM(LLMClient):
    """Deterministic offline stand-in. No network, no key required."""

    def complete(self, system: str, user: str) -> str:
        if system.startswith("ANALYZE"):
            return (
                "Root cause: divide() performs a / b with no guard on b == 0, "
                "so a zero denominator raises an unhandled ZeroDivisionError instead "
                "of a controlled, callable-facing error."
            )

        if system.startswith("PATCH"):
            code = user.split("CURRENT FILE CONTENT:\n", 1)[-1]
            if "def divide(a, b):" in code and "b == 0" not in code:
                code = code.replace(
                    "def divide(a, b):\n    return a / b",
                    "def divide(a, b):\n"
                    "    if b == 0:\n"
                    "        raise ValueError(\"b must not be zero\")\n"
                    "    return a / b",
                )
            return code

        return "OK"


def get_llm() -> LLMClient:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return AnthropicLLM()
    return MockLLM()
