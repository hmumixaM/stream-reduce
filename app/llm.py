"""LLM client for the LiteLLM proxy (OpenAI-compatible Chat Completions).

The proxy serves Gemini models (gemini-2.5-flash, gemini-3.5-flash, ...) through
an OpenAI-compatible API, matching the setup used by the agentflow reference
project. We talk to it directly over httpx so we can capture token usage.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from app.config import get_settings


@dataclass
class LlmResult:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0


def _endpoint() -> str:
    return get_settings().llm_base_url.rstrip("/") + "/chat/completions"


def _headers() -> dict:
    settings = get_settings()
    if not settings.llm_api_key:
        raise RuntimeError("LLM_API_KEY is not configured")
    return {
        "Authorization": f"Bearer {settings.llm_api_key}",
        "Content-Type": "application/json",
    }


def _parse(data: dict, latency_ms: int) -> LlmResult:
    content = data["choices"][0]["message"].get("content") or ""
    usage = data.get("usage") or {}
    return LlmResult(
        text=content,
        prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
        completion_tokens=int(usage.get("completion_tokens", 0) or 0),
        total_tokens=int(usage.get("total_tokens", 0) or 0),
        latency_ms=latency_ms,
    )


def generate_text(
    prompt: str,
    *,
    system: str | None = None,
    temperature: float | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
) -> LlmResult:
    settings = get_settings()
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    from app.runtime_config import effective_llm_model

    payload = {
        "model": model or effective_llm_model(),
        "messages": messages,
        "temperature": settings.llm_temperature if temperature is None else temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    start = time.monotonic()
    with httpx.Client(timeout=300) as client:
        resp = client.post(_endpoint(), json=payload, headers=_headers())
        resp.raise_for_status()
        data = resp.json()
    return _parse(data, int((time.monotonic() - start) * 1000))


def generate_with_audio(
    prompt: str,
    audio_b64: str,
    audio_format: str,
    *,
    system: str | None = None,
    model: str | None = None,
) -> LlmResult:
    """Send audio inline via the OpenAI-compatible multimodal content format."""
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "input_audio", "input_audio": {"data": audio_b64, "format": audio_format}},
        ],
    })
    from app.runtime_config import effective_llm_model

    payload = {"model": model or effective_llm_model(), "messages": messages}
    start = time.monotonic()
    with httpx.Client(timeout=600) as client:
        resp = client.post(_endpoint(), json=payload, headers=_headers())
        resp.raise_for_status()
        data = resp.json()
    return _parse(data, int((time.monotonic() - start) * 1000))
