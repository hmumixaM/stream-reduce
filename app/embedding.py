"""Embedding client for the LiteLLM proxy (OpenAI-compatible /embeddings).

The same proxy that serves Gemini chat models also exposes Vertex AI's
``text-embedding-005`` (768-dim) through the OpenAI ``/embeddings`` API. We talk
to it directly over httpx so we can batch inputs and capture token usage. The
embedding model runs remotely, so this adds no local model memory — only the
in-flight batch of vectors lives in RAM.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import httpx

from app.config import get_settings


@dataclass
class EmbedResult:
    vectors: list[list[float]] = field(default_factory=list)
    prompt_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0


def l2_normalize(vector: list[float]) -> list[float]:
    """Unit-normalize a vector so sqlite-vec's L2 distance ranks like cosine.

    Vertex embeddings are not guaranteed unit-norm; normalizing both stored and
    query vectors makes L2 ordering equivalent to cosine similarity.
    """
    norm = sum(v * v for v in vector) ** 0.5
    if norm == 0:
        return vector
    return [v / norm for v in vector]


def _endpoint() -> str:
    return get_settings().resolved_embedding_base_url.rstrip("/") + "/embeddings"


def _headers() -> dict:
    settings = get_settings()
    key = settings.resolved_embedding_api_key
    if not key:
        raise RuntimeError("No embedding API key configured (set EMBEDDING_API_KEY or LLM_API_KEY)")
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _post_batch(texts: list[str], model: str) -> tuple[list[list[float]], int, int, int]:
    payload = {"model": model, "input": texts}
    start = time.monotonic()
    with httpx.Client(timeout=120) as client:
        resp = client.post(_endpoint(), json=payload, headers=_headers())
        resp.raise_for_status()
        data = resp.json()
    latency_ms = int((time.monotonic() - start) * 1000)
    # Preserve request order regardless of how the proxy orders ``data``.
    rows = sorted(data["data"], key=lambda d: d.get("index", 0))
    vectors = [row["embedding"] for row in rows]
    usage = data.get("usage") or {}
    prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
    total_tokens = int(usage.get("total_tokens", prompt_tokens) or prompt_tokens)
    return vectors, prompt_tokens, total_tokens, latency_ms


def embed_texts(texts: list[str], *, model: str | None = None) -> EmbedResult:
    """Embed a list of texts, batching to bound peak memory and request size."""
    settings = get_settings()
    model = model or settings.embedding_model
    batch_size = max(1, settings.embed_batch_size)

    result = EmbedResult()
    if not texts:
        return result
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        vectors, prompt_tokens, total_tokens, latency_ms = _post_batch(batch, model)
        result.vectors.extend(vectors)
        result.prompt_tokens += prompt_tokens
        result.total_tokens += total_tokens
        result.latency_ms += latency_ms
    return result


def embed_query(text: str, *, model: str | None = None) -> list[float]:
    """Embed a single search query and return its vector."""
    return embed_texts([text], model=model).vectors[0]
