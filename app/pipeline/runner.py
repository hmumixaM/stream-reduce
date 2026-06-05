"""Top-level pipeline orchestration executed by RQ workers."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.config import get_settings
from app.db import session_scope
from app.models import (
    Item,
    ItemStatus,
    StageName,
    Transcript,
    TranscriptSource,
)
from app.pipeline.metrics import StageTracker
from app.runtime_config import effective_llm_model, effective_stt_model

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


def _relative_media_path(audio_path: str, settings) -> str:
    """Path of a downloaded file relative to the media dir (for /media serving)."""
    from pathlib import Path as _Path

    p = _Path(audio_path)
    try:
        return str(p.relative_to(settings.resolved_media_dir))
    except ValueError:
        return p.name


def _download_decodable(adapter, url: str, dest_dir, expected, attempts: int = 3):
    """Download audio and verify it actually DECODES to ~the full length.

    Bilibili (especially under batch load) intermittently returns a file that is
    byte-complete but corrupt mid-stream; its container header still claims the
    full duration, so a header-based size/duration check passes while only the
    first minutes are decodable. We decode-verify each download and re-fetch a
    clean copy a few times — a fresh download almost always succeeds. The file is
    deleted between attempts so yt-dlp's resume (continuedl) can't keep a bad copy.

    Returns (Path, decodable_seconds). Raises TruncatedAudioError if every
    attempt is still short.
    """
    from pathlib import Path as _Path

    from app.pipeline.audio import decodable_duration
    from app.pipeline.transcribe import TruncatedAudioError

    decodable = 0.0
    for attempt in range(1, attempts + 1):
        path = _Path(adapter.download_audio(url, dest_dir))
        decodable = decodable_duration(path)
        if not expected or decodable >= expected * 0.9:
            return path, decodable
        logger.warning(
            "download attempt %d/%d for %s decoded only %.0fs of %ss (%.0f%%); "
            "re-downloading a clean copy",
            attempt, attempts, url, decodable, expected,
            decodable / expected * 100 if expected else 0,
        )
        path.unlink(missing_ok=True)
    raise TruncatedAudioError(
        f"incomplete audio after {attempts} downloads: only {decodable:.0f}s of "
        f"expected {expected}s decodable — Bilibili kept returning a corrupt stream"
    )


def process_item(item_id: int) -> None:
    """Run the full ingest -> transcribe -> summarize pipeline for one item."""
    from app.adapters.registry import get_adapter
    from app.pipeline.summarize import summarize_item
    from app.pipeline.transcribe import transcribe_audio

    settings = get_settings()

    with session_scope() as s:
        item = s.get(Item, item_id)
        if item is None:
            logger.warning("process_item: item %s not found", item_id)
            return
        item.status = ItemStatus.fetching
        item.started_at = _now()
        item.error = None
        s.add(item)
        source_url = item.source_url
        platform = item.platform

    adapter = get_adapter(platform)

    try:
        # --- Stage: download / fetch metadata + native transcript ---
        audio_path = None
        native_segments = None
        native_lang = None
        with session_scope() as s:
            with StageTracker(s, item_id, StageName.download, provider=adapter.name) as tracker:
                from app.zh import to_simplified

                meta = adapter.fetch_metadata(source_url)
                item = s.get(Item, item_id)
                item.title = to_simplified(meta.title or "") or item.title
                item.author = to_simplified(meta.author or "") or item.author
                item.description = to_simplified(meta.description or "") or item.description
                item.duration_s = meta.duration_s or item.duration_s
                item.external_id = meta.external_id or item.external_id
                if meta.view_count is not None:
                    item.view_count = meta.view_count
                if meta.like_count is not None:
                    item.like_count = meta.like_count
                if meta.dislike_count is not None:
                    item.dislike_count = meta.dislike_count
                thumb_url = meta.thumbnail or item.thumbnail
                if thumb_url:
                    from app.media import download_thumbnail

                    local = download_thumbnail(thumb_url, item_id, platform)
                    item.thumbnail = local or thumb_url
                if meta.published_at:
                    item.published_at = meta.published_at
                s.add(item)

                danmaku = adapter.get_danmaku(source_url)
                if danmaku:
                    from app.pipeline.danmaku import save_danmaku

                    save_danmaku(item_id, danmaku)

                lang = settings.default_language or None
                native = adapter.get_native_transcript(source_url, lang)
                if native and native.segments:
                    native_segments = native.segments
                    native_lang = native.language
                    tracker.set_chunks(0)
                else:
                    # Download and decode-verify in one step: the container
                    # header can claim the full duration even when the stream is
                    # truncated/corrupt, so we decode the file and re-fetch a
                    # clean copy a few times before giving up (see helper).
                    expected = meta.duration_s or item.duration_s
                    path, decodable = _download_decodable(
                        adapter, source_url, settings.resolved_media_dir, expected
                    )
                    audio_path = str(path)
                    item.media_bytes = path.stat().st_size
                    item.audio_duration_s = decodable or None
                    item.media_path = _relative_media_path(audio_path, settings)
                    s.add(item)

        # Optional last-resort path: hand the audio straight to Gemini when no
        # transcript is available and transcription is not configured.
        use_gemini_audio = (
            native_segments is None
            and settings.enable_gemini_audio_fallback
            and not settings.openrouter_api_key
        )
        if use_gemini_audio:
            from app.pipeline.summarize import summarize_via_gemini_audio

            with session_scope() as s:
                item = s.get(Item, item_id)
                item.status = ItemStatus.summarizing
                s.add(item)
            with session_scope() as s:
                with StageTracker(
                    s, item_id, StageName.gemini_audio,
                    provider="litellm", model=effective_llm_model(),
                ) as tracker:
                    summarize_via_gemini_audio(s, item_id, audio_path, tracker)
            with session_scope() as s:
                item = s.get(Item, item_id)
                item.status = ItemStatus.done
                item.completed_at = _now()
                s.add(item)
            logger.info("process_item %s completed via gemini audio", item_id)
            return

        if native_segments is not None:
            with session_scope() as s:
                _store_transcript(s, item_id, native_lang, TranscriptSource.native, native_segments)
        else:
            # --- Stage: transcribe via OpenRouter ---
            with session_scope() as s:
                item = s.get(Item, item_id)
                item.status = ItemStatus.transcribing
                expected_duration = item.duration_s or item.audio_duration_s
                s.add(item)
            with session_scope() as s:
                with StageTracker(
                    s, item_id, StageName.transcribe,
                    provider="openrouter", model=effective_stt_model(),
                ) as tracker:
                    result = transcribe_audio(
                        audio_path, tracker, expected_duration=expected_duration
                    )
                _store_transcript(
                    s, item_id, result.language,
                    TranscriptSource.openrouter_whisper, result.segments,
                )

        # --- Stage: summarize via Gemini ---
        with session_scope() as s:
            item = s.get(Item, item_id)
            item.status = ItemStatus.summarizing
            s.add(item)
        with session_scope() as s:
            with StageTracker(
                s, item_id, StageName.summarize,
                provider="litellm", model=effective_llm_model(),
            ) as tracker:
                summarize_item(s, item_id, tracker)

        # --- Stage: embed transcript + summary for semantic search ---
        _embed_stage(item_id)

        with session_scope() as s:
            item = s.get(Item, item_id)
            item.status = ItemStatus.done
            item.completed_at = _now()
            item.error = None
            s.add(item)
        logger.info("process_item %s completed", item_id)

    except Exception as exc:  # noqa: BLE001 - record failure, let RQ see it
        logger.exception("process_item %s failed", item_id)
        from app.pipeline.transcribe import TruncatedAudioError

        # A truncated/corrupt download keeps the full byte size, so yt-dlp would
        # treat it as "already downloaded" and skip on retry. Delete it so the
        # next attempt fetches a clean copy.
        truncated = isinstance(exc, TruncatedAudioError) and bool(audio_path)
        if truncated:
            from pathlib import Path as _Path

            _Path(audio_path).unlink(missing_ok=True)
            logger.info("removed truncated audio for item %s to force re-download", item_id)
        with session_scope() as s:
            item = s.get(Item, item_id)
            if item is not None:
                item.status = ItemStatus.error
                item.error = f"{type(exc).__name__}: {exc}"[:4000]
                item.retry_count += 1
                if truncated:
                    item.media_bytes = 0
                    item.audio_duration_s = None
                    item.media_path = None
                s.add(item)
        raise


def _store_transcript(session, item_id: int, language, source: TranscriptSource,
                      segments: list[dict]) -> None:
    from sqlmodel import select

    from app.zh import to_simplified

    # Normalize Chinese transcripts to Simplified regardless of the source
    # (e.g. Taiwan zh-TW native subtitles arrive Traditional).
    segments = [{**seg, "text": to_simplified(seg.get("text", ""))} for seg in segments]
    existing = session.exec(select(Transcript).where(Transcript.item_id == item_id)).first()
    text = "\n".join(seg.get("text", "") for seg in segments).strip()
    if existing is not None:
        existing.language = language
        existing.source = source
        existing.segments = segments
        existing.text = text
        session.add(existing)
    else:
        session.add(Transcript(
            item_id=item_id,
            language=language,
            source=source,
            segments=segments,
            text=text,
        ))


def resummarize_item(item_id: int) -> None:
    """Re-run only the summarize stage using the existing transcript."""
    from app.pipeline.summarize import summarize_item

    with session_scope() as s:
        item = s.get(Item, item_id)
        if item is None:
            return
        item.status = ItemStatus.summarizing
        item.error = None
        s.add(item)
    try:
        with session_scope() as s:
            with StageTracker(
                s, item_id, StageName.summarize,
                provider="litellm", model=effective_llm_model(),
            ) as tracker:
                summarize_item(s, item_id, tracker)
        _embed_stage(item_id)
        with session_scope() as s:
            item = s.get(Item, item_id)
            item.status = ItemStatus.done
            item.completed_at = _now()
            s.add(item)
    except Exception as exc:  # noqa: BLE001
        with session_scope() as s:
            item = s.get(Item, item_id)
            if item is not None:
                item.status = ItemStatus.error
                item.error = f"{type(exc).__name__}: {exc}"[:4000]
                s.add(item)
        raise


def _embed_stage(item_id: int) -> None:
    """Run the (optional) embedding stage. Auxiliary: a failure here is logged
    but never fails the item, which has already been transcribed + summarized."""
    settings = get_settings()
    if not settings.enable_embeddings:
        return
    from app import db

    if not db.VEC_AVAILABLE:
        return
    try:
        from app.pipeline.embed import embed_item

        with session_scope() as s:
            with StageTracker(
                s, item_id, StageName.embed,
                provider="litellm", model=settings.embedding_model,
            ) as tracker:
                embed_item(s, item_id, tracker)
    except Exception:  # noqa: BLE001
        logger.exception("embedding stage failed for item %s (non-fatal)", item_id)


def poll_subscription(subscription_id: int) -> int:
    """Check a subscription feed and enqueue any new items. Returns count enqueued."""
    from app.pipeline.subscriptions import poll_one

    return poll_one(subscription_id)
