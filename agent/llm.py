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


class GroqLLM(LLMClient):
    def __init__(self, model: str | None = None):
        from groq import Groq

        self.client = Groq()  # reads GROQ_API_KEY from env
        self.model = model or os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

    def complete(self, system: str, user: str) -> str:
        resp = self.client.chat.completions.create(
            model=self.model,
            max_tokens=4000,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content or ""


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
    """
    Provider selection:
      - LLM_PROVIDER=groq | anthropic | mock  -> explicit override
      - otherwise: GROQ_API_KEY set -> Groq; ANTHROPIC_API_KEY set -> Anthropic;
        neither -> offline MockLLM.
    """
    provider = os.environ.get("LLM_PROVIDER", "").lower()

    if provider == "groq" or (not provider and os.environ.get("GROQ_API_KEY")):
        return GroqLLM()
    if provider == "anthropic" or (not provider and os.environ.get("ANTHROPIC_API_KEY")):
        return AnthropicLLM()
    return MockLLM()
