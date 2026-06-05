"""Semantic search over embedded transcript + summary chunks.

Embeds the query with the same model used at index time, runs a KNN scan on the
``chunk_vec`` sqlite-vec table, and joins back to ``chunk`` + ``item`` so each
hit carries the original text plus a locator (timestamp / deep-link) the caller
(agent, REST, UI) can use to jump to the source.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from sqlalchemy import text as sql_text
from sqlmodel import Session, col, select

from app.config import get_settings
from app.models import Chunk, Item, Platform


@dataclass
class SearchHit:
    chunk_id: int
    item_id: int
    title: str | None
    source_url: str
    platform: str
    author: str | None
    source: str
    field: str
    text: str
    start_s: float | None
    end_s: float | None
    deep_link: str | None
    score: float

    def to_dict(self) -> dict:
        return asdict(self)


def deep_link(item: Item, seconds: float | None) -> str | None:
    """A URL that jumps to ``seconds`` in the source media, when supported."""
    if not item.source_url:
        return None
    if seconds is not None and item.platform in (Platform.youtube, Platform.bilibili):
        sep = "&" if "?" in item.source_url else "?"
        return f"{item.source_url}{sep}t={int(seconds)}s"
    return item.source_url


class SearchUnavailableError(RuntimeError):
    """Raised when semantic search is requested but the vec index is unavailable."""


def semantic_search(
    session: Session,
    query: str,
    *,
    k: int = 10,
    item_id: int | None = None,
    source: str | None = None,
) -> list[SearchHit]:
    settings = get_settings()
    from app import db as _db

    if not settings.enable_embeddings or not _db.VEC_AVAILABLE:
        raise SearchUnavailableError(
            "semantic search is unavailable (embeddings disabled or sqlite-vec not loaded)"
        )
    query = (query or "").strip()
    if not query:
        return []

    import sqlite_vec

    from app.embedding import embed_query, l2_normalize

    vector = l2_normalize(embed_query(query))
    serialized = sqlite_vec.serialize_float32(vector)

    # Over-fetch when filtering, since the KNN limit is applied before the join.
    filtering = item_id is not None or source is not None
    n = max(k * 10, 100) if filtering else k

    rows = session.exec(
        sql_text(
            "SELECT rowid, distance FROM chunk_vec "
            "WHERE embedding MATCH :q ORDER BY distance LIMIT :n"
        ).bindparams(q=serialized, n=n)
    ).all()
    if not rows:
        return []

    distance_by_id = {int(r[0]): float(r[1]) for r in rows}
    ordered_ids = [int(r[0]) for r in rows]

    chunks = session.exec(select(Chunk).where(col(Chunk.id).in_(ordered_ids))).all()
    chunk_by_id = {c.id: c for c in chunks}
    item_cache: dict[int, Item | None] = {}

    hits: list[SearchHit] = []
    for cid in ordered_ids:
        chunk = chunk_by_id.get(cid)
        if chunk is None:
            continue
        if item_id is not None and chunk.item_id != item_id:
            continue
        if source is not None and chunk.source.value != source:
            continue
        if chunk.item_id not in item_cache:
            item_cache[chunk.item_id] = session.get(Item, chunk.item_id)
        item = item_cache[chunk.item_id]
        if item is None:
            continue
        distance = distance_by_id.get(cid, 0.0)
        hits.append(
            SearchHit(
                chunk_id=cid,
                item_id=chunk.item_id,
                title=item.title,
                source_url=item.source_url,
                platform=item.platform.value,
                author=item.author,
                source=chunk.source.value,
                field=chunk.field,
                text=chunk.text,
                start_s=chunk.start_s,
                end_s=chunk.end_s,
                deep_link=deep_link(item, chunk.start_s),
                # Cosine similarity in [-1, 1] from unit-vector L2 distance.
                score=round(1.0 - (distance**2) / 2.0, 4),
            )
        )
        if len(hits) >= k:
            break
    return hits
