"""Embed an item's transcript + summary into the chunk vector index.

Run as a pipeline stage after summarization (and on resummarize/backfill). The
work is idempotent: if the chunk set for an item is unchanged (same content
hashes) we skip embedding entirely, so re-runs cost nothing. Regeneration only
ever rewrites derived ``chunk`` / ``chunk_vec`` rows — never transcript,
summary, or item rows.
"""

from __future__ import annotations

import logging

from sqlalchemy import text as sql_text
from sqlmodel import Session, select

from app.config import get_settings
from app.models import Chunk, Summary, Transcript
from app.pipeline.chunking import ChunkSpec, chunk_summary, chunk_transcript
from app.pipeline.metrics import StageTracker

logger = logging.getLogger(__name__)


def _build_specs(session: Session, item_id: int) -> list[ChunkSpec]:
    specs: list[ChunkSpec] = []
    transcript = session.exec(
        select(Transcript).where(Transcript.item_id == item_id)
    ).first()
    if transcript and transcript.segments:
        specs.extend(chunk_transcript(transcript.segments))
    summary = session.exec(select(Summary).where(Summary.item_id == item_id)).first()
    if summary:
        specs.extend(chunk_summary(summary.structured, summary.markdown))
    return specs


def _delete_existing(session: Session, item_id: int) -> None:
    existing = session.exec(select(Chunk).where(Chunk.item_id == item_id)).all()
    if not existing:
        return
    ids = [c.id for c in existing if c.id is not None]
    if ids:
        placeholders = ",".join(str(i) for i in ids)
        session.exec(sql_text(f"DELETE FROM chunk_vec WHERE rowid IN ({placeholders})"))
    for chunk in existing:
        session.delete(chunk)
    session.flush()


def embed_item(session: Session, item_id: int, tracker: StageTracker | None = None) -> int:
    """(Re)build embeddings for one item. Returns the number of chunks written."""
    from app import db

    settings = get_settings()
    if not settings.enable_embeddings or not db.VEC_AVAILABLE:
        logger.info("embeddings disabled or sqlite-vec unavailable; skipping item %s", item_id)
        return 0

    model = settings.embedding_model
    specs = _build_specs(session, item_id)
    if tracker is not None:
        tracker.set_chunks(len(specs))
    if not specs:
        _delete_existing(session, item_id)
        return 0

    new_hashes = {spec.content_hash(model) for spec in specs}
    existing = session.exec(select(Chunk).where(Chunk.item_id == item_id)).all()
    if existing and {c.content_hash for c in existing} == new_hashes:
        logger.info("item %s chunks unchanged (%d); skipping re-embed", item_id, len(specs))
        if tracker is not None:
            tracker.chunk_progress(len(specs))
        return len(specs)

    from app.embedding import embed_texts

    result = embed_texts([spec.text for spec in specs], model=model)
    if len(result.vectors) != len(specs):
        raise RuntimeError(
            f"embedding count mismatch for item {item_id}: "
            f"{len(result.vectors)} vectors for {len(specs)} chunks"
        )
    if tracker is not None:
        tracker.record_call(
            provider="litellm",
            model=model,
            endpoint="embeddings",
            latency_ms=result.latency_ms,
            status_code=200,
            prompt_tokens=result.prompt_tokens,
            tokens=result.total_tokens,
        )

    _delete_existing(session, item_id)

    import sqlite_vec

    from app.embedding import l2_normalize

    for index, (spec, vector) in enumerate(zip(specs, result.vectors, strict=True)):
        vector = l2_normalize(vector)
        chunk = Chunk(
            item_id=item_id,
            source=spec.source,
            field=spec.field,
            chunk_index=index,
            text=spec.text,
            start_s=spec.start_s,
            end_s=spec.end_s,
            char_start=spec.char_start,
            char_end=spec.char_end,
            token_count=max(1, len(spec.text) // 4),
            content_hash=spec.content_hash(model),
            embedding_model=model,
        )
        session.add(chunk)
        session.flush()  # assign chunk.id for the vec rowid
        session.exec(
            sql_text("INSERT INTO chunk_vec(rowid, embedding) VALUES (:rid, :emb)").bindparams(
                rid=chunk.id, emb=sqlite_vec.serialize_float32(vector)
            )
        )
        if tracker is not None and (index + 1) % 20 == 0:
            tracker.chunk_progress(index + 1)

    if tracker is not None:
        tracker.chunk_progress(len(specs))
    logger.info("embedded item %s into %d chunks", item_id, len(specs))
    return len(specs)
