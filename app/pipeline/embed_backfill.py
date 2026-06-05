"""One-shot backfill: embed every existing item that has content but no chunks.

Idempotent and memory-frugal — processes one item at a time in its own session,
and ``embed_item`` itself skips items whose chunks are already up to date (same
content hashes). Safe to re-run; intended to be run once after deploying the
embeddings feature.

Usage:
    uv run python -m app.pipeline.embed_backfill          # backfill missing
    uv run python -m app.pipeline.embed_backfill --all     # re-embed everything
"""

from __future__ import annotations

import argparse
import logging

from sqlmodel import select

from app.config import get_settings
from app.db import init_db, session_scope
from app.models import Chunk, StageName, Summary, Transcript
from app.pipeline.metrics import StageTracker

logger = logging.getLogger(__name__)


def _item_ids_with_content(session) -> list[int]:
    ids: set[int] = set()
    ids.update(session.exec(select(Transcript.item_id)).all())
    ids.update(session.exec(select(Summary.item_id)).all())
    return sorted(ids)


def _already_embedded(session, item_id: int) -> bool:
    return (
        session.exec(select(Chunk.id).where(Chunk.item_id == item_id).limit(1)).first()
        is not None
    )


def backfill(force: bool = False) -> dict:
    from app import db as _db
    from app.pipeline.embed import embed_item

    init_db()
    settings = get_settings()
    if not settings.enable_embeddings or not _db.VEC_AVAILABLE:
        raise RuntimeError(
            "Cannot backfill: embeddings disabled or sqlite-vec unavailable. "
            "Set ENABLE_EMBEDDINGS=true and ensure `uv sync` installed sqlite-vec."
        )

    with session_scope() as session:
        item_ids = _item_ids_with_content(session)

    processed = 0
    skipped = 0
    failed = 0
    total_chunks = 0
    for item_id in item_ids:
        try:
            with session_scope() as session:
                if not force and _already_embedded(session, item_id):
                    skipped += 1
                    continue
                with StageTracker(
                    session, item_id, StageName.embed,
                    provider="litellm", model=settings.embedding_model,
                ) as tracker:
                    total_chunks += embed_item(session, item_id, tracker)
                processed += 1
                logger.info("backfilled item %s (%d/%d)", item_id, processed, len(item_ids))
        except Exception:  # noqa: BLE001 - one bad item must not abort the whole run
            failed += 1
            # Item's chunks were rolled back, so a later re-run retries it.
            logger.exception("backfill failed for item %s; continuing", item_id)

    result = {
        "items_total": len(item_ids),
        "items_embedded": processed,
        "items_skipped": skipped,
        "items_failed": failed,
        "chunks_written": total_chunks,
    }
    logger.info("backfill complete: %s", result)
    return result


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Backfill chunk embeddings.")
    parser.add_argument(
        "--all", dest="force", action="store_true",
        help="re-embed every item, even those already embedded",
    )
    args = parser.parse_args()
    result = backfill(force=args.force)
    print(
        f"Embedded {result['items_embedded']} item(s) "
        f"({result['chunks_written']} chunks); "
        f"skipped {result['items_skipped']} already-embedded; "
        f"failed {result['items_failed']}; "
        f"{result['items_total']} item(s) with content total."
    )


if __name__ == "__main__":
    main()
