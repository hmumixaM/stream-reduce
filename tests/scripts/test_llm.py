"""Live smoke test: LiteLLM Gemini endpoint connectivity.

Run manually:  uv run python tests/scripts/test_llm.py
Requires LLM_API_KEY / LLM_BASE_URL in the environment / .env.
"""

from __future__ import annotations

from app.llm import generate_text


def main() -> None:
    result = generate_text("Reply with exactly: pong")
    print("text:", result.text)
    print(
        "tokens (p/c/t):",
        result.prompt_tokens, result.completion_tokens, result.total_tokens,
    )
    print("latency_ms:", result.latency_ms)


if __name__ == "__main__":
    main()
