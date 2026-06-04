"""OpenRouter speech-to-text with ffmpeg chunking, rate limiting, and 429 backoff."""

from __future__ import annotations

import base64
import logging
import random
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from app.config import get_settings
from app.pipeline.audio import probe_duration, split_audio
from app.pipeline.metrics import StageTracker

logger = logging.getLogger(__name__)


class TruncatedAudioError(RuntimeError):
    """Raised when the decodable audio is far shorter than the expected length.

    Signals a corrupt/incomplete download whose container header may still claim
    the full duration. The runner deletes the file so a retry re-downloads it.
    """


@dataclass
class TranscribeResult:
    language: str | None = None
    segments: list[dict] = field(default_factory=list)
    text: str = ""


class RateLimiter:
    """Simple minimum-interval limiter (requests per minute)."""

    def __init__(self, per_minute: int):
        self.min_interval = 60.0 / per_minute if per_minute > 0 else 0.0
        self._last = 0.0

    def wait(self) -> None:
        if self.min_interval <= 0:
            return
        elapsed = time.monotonic() - self._last
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last = time.monotonic()


def transcribe_audio(
    audio_path: str,
    tracker: StageTracker | None = None,
    expected_duration: float | None = None,
) -> TranscribeResult:
    settings = get_settings()
    if not settings.openrouter_api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not configured")

    limiter = RateLimiter(settings.transcribe_rate_limit)
    with tempfile.TemporaryDirectory(prefix="sr_chunks_") as tmp:
        workdir = Path(tmp)
        chunks = split_audio(audio_path, settings.transcribe_chunk_seconds, workdir)
        if not chunks:
            raise RuntimeError(f"no audio chunks produced from {audio_path}")

        # Chunks are re-encoded (i.e. fully decoded) by ffmpeg, so their summed
        # length is the REAL transcribable audio — unlike the container header,
        # which can claim the full duration even when the stream is truncated
        # (a common flaky-CDN download failure). Bail out loudly so the item is
        # retried instead of silently summarizing only the first minutes.
        chunk_durations = [probe_duration(c) for c in chunks]
        decodable = sum(chunk_durations)
        if expected_duration and decodable < expected_duration * 0.9:
            raise TruncatedAudioError(
                f"truncated audio: only {decodable:.0f}s decodable of expected "
                f"{expected_duration:.0f}s ({decodable / expected_duration:.0%}); "
                "the download is incomplete — will retry"
            )
        if tracker is not None:
            tracker.set_chunks(len(chunks))

        segments: list[dict] = []
        offset = 0.0
        language: str | None = None
        with httpx.Client(timeout=300) as client:
            for idx, chunk in enumerate(chunks):
                limiter.wait()
                duration = chunk_durations[idx]
                text, detected = _transcribe_chunk(client, chunk, settings, tracker)
                language = language or detected
                if text:
                    segments.append({
                        "start": round(offset, 2),
                        "end": round(offset + duration, 2),
                        "text": text.strip(),
                    })
                offset += duration
                if tracker is not None:
                    tracker.chunk_progress(idx + 1)

    full_text = "\n".join(s["text"] for s in segments)
    return TranscribeResult(language=language, segments=segments, text=full_text)


def _transcribe_chunk(
    client: httpx.Client, chunk: Path, settings, tracker: StageTracker | None
) -> tuple[str, str | None]:
    from app.runtime_config import effective_stt_model

    model = effective_stt_model()
    audio_b64 = base64.b64encode(chunk.read_bytes()).decode("ascii")
    payload: dict = {
        "model": model,
        "input_audio": {"data": audio_b64, "format": "mp3"},
    }
    if settings.default_language:
        payload["language"] = settings.default_language

    url = f"{settings.openrouter_base_url}/audio/transcriptions"
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": settings.openrouter_referer,
        "X-Title": settings.openrouter_title,
    }

    backoff = 2.0
    last_exc: Exception | None = None
    for _attempt in range(settings.transcribe_max_retries):
        start = time.monotonic()
        try:
            resp = client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:  # network errors -> retry
            last_exc = exc
            time.sleep(backoff + random.uniform(0, 1))
            backoff *= 2
            continue
        latency_ms = int((time.monotonic() - start) * 1000)

        if resp.status_code == 429 or resp.status_code >= 500:
            if tracker is not None:
                tracker.record_call(
                    provider="openrouter", model=model,
                    endpoint="/audio/transcriptions", latency_ms=latency_ms,
                    status_code=resp.status_code, is_429=resp.status_code == 429,
                )
            retry_after = resp.headers.get("retry-after")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else backoff
            logger.warning(
                "STT %s on %s, retry in %.1fs", resp.status_code, chunk.name, delay
            )
            time.sleep(delay + random.uniform(0, 1))
            backoff *= 2
            continue

        resp.raise_for_status()
        data = resp.json()
        usage = data.get("usage") or {}
        if tracker is not None:
            tracker.record_call(
                provider="openrouter", model=model,
                endpoint="/audio/transcriptions", latency_ms=latency_ms,
                status_code=resp.status_code,
                tokens=int(usage.get("total_tokens", 0) or 0),
                cost_usd=float(usage.get("cost", 0) or 0),
            )
        text = data.get("text") or ""
        language = data.get("language")
        return text, language

    raise RuntimeError(
        f"transcription failed for {chunk.name} after {settings.transcribe_max_retries} attempts"
    ) from last_exc
