"""Read-side helpers for the paragraph-similarity knowledge graph.

Serialization + filtered aggregation shared by the build job (which pre-renders
the unfiltered graph into ``graphcache``), the REST API, and the static mirror.
The unfiltered case is a single cache read; filtered requests re-aggregate the
small node/link tables in-process (no recompute, no vectors).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlmodel import Session, col, select

from app.models import (
    GraphCache,
    GraphLink,
    GraphParagraph,
    Item,
    ItemRecommendation,
    Platform,
    utcnow,
)


@dataclass
class GraphFilters:
    """Live-app filters mirroring Library. Archived is excluded by default."""

    include_archived: bool = False
    favorite: bool = False
    folders: list[int] = field(default_factory=list)
    platform: str | None = None

    def is_unfiltered(self) -> bool:
        return (
            not self.include_archived
            and not self.favorite
            and not self.folders
            and not self.platform
        )


def _allowed_item_ids(session: Session, filters: GraphFilters) -> set[int]:
    stmt = select(Item.id)
    if not filters.include_archived:
        stmt = stmt.where(Item.is_archived == False)  # noqa: E712
    if filters.favorite:
        stmt = stmt.where(Item.is_favorite == True)  # noqa: E712
    if filters.folders:
        stmt = stmt.where(col(Item.group_id).in_(filters.folders))
    if filters.platform:
        stmt = stmt.where(Item.platform == Platform(filters.platform))
    return {int(i) for i in session.exec(stmt).all()}


def aggregate_graph(
    session: Session,
    *,
    allowed_item_ids: set[int] | None,
    build_id: int | None = None,
    built_at: datetime | None = None,
) -> dict:
    """Build the paragraph-graph payload from the node/link tables, optionally
    restricted to a set of item ids (``None`` => the full, unfiltered graph)."""
    node_stmt = select(GraphParagraph)
    if allowed_item_ids is not None:
        node_stmt = node_stmt.where(col(GraphParagraph.item_id).in_(allowed_item_ids or {-1}))
    paragraphs = session.exec(node_stmt).all()

    item_ids = {p.item_id for p in paragraphs}
    items = session.exec(select(Item).where(col(Item.id).in_(item_ids or {-1}))).all()
    item_by_id = {i.id: i for i in items}

    nodes: list[dict] = []
    surviving: set[int] = set()
    for p in paragraphs:
        item = item_by_id.get(p.item_id)
        if item is None:
            continue
        surviving.add(p.chunk_id)
        nodes.append(
            {
                "id": p.chunk_id,
                "item_id": p.item_id,
                "title": item.title,
                "platform": item.platform.value,
                "field": p.field,
                "text": p.text,
                "community": p.community,
                "degree": p.degree,
            }
        )

    edges: list[dict] = []
    for link in session.exec(select(GraphLink)).all():
        if link.src_chunk_id in surviving and link.dst_chunk_id in surviving:
            edges.append(
                {"source": link.src_chunk_id, "target": link.dst_chunk_id, "weight": link.weight}
            )

    cache = session.get(GraphCache, 1)
    return {
        "build_id": build_id if build_id is not None else (cache.build_id if cache else 0),
        "built_at": (
            (built_at or (cache.built_at if cache else None) or utcnow()).isoformat()
        ),
        "nodes": nodes,
        "edges": edges,
    }


def get_graph(session: Session, filters: GraphFilters | None = None) -> dict:
    """Unfiltered => the pre-serialized cache blob (zero compute). Filtered =>
    a cheap node/link re-aggregation."""
    if filters is None or filters.is_unfiltered():
        cache = session.get(GraphCache, 1)
        if cache is not None and cache.blob:
            import json

            return json.loads(cache.blob)
        return aggregate_graph(session, allowed_item_ids=None)
    allowed = _allowed_item_ids(session, filters)
    return aggregate_graph(session, allowed_item_ids=allowed)


def focus_node(session: Session, item_id: int) -> int | None:
    """A representative paragraph node for an item (most-connected one), so a
    ``/graph?focus=<itemId>`` deep link can center on the article."""
    rows = session.exec(
        select(GraphParagraph)
        .where(GraphParagraph.item_id == item_id)
        .order_by(col(GraphParagraph.degree).desc())
    ).first()
    return rows.chunk_id if rows is not None else None


def related_items(session: Session, item_id: int, *, limit: int = 8) -> list[dict]:
    """Recommended related articles for an item (excludes archived)."""
    recs = session.exec(
        select(ItemRecommendation)
        .where(ItemRecommendation.item_id == item_id)
        .order_by(col(ItemRecommendation.score).desc())
        .limit(limit * 2)
    ).all()
    out: list[dict] = []
    for rec in recs:
        item = session.get(Item, rec.related_item_id)
        if item is None or item.is_archived:
            continue
        out.append(
            {
                "id": item.id,
                "item_id": item.id,
                "title": item.title,
                "platform": item.platform.value,
                "author": item.author,
                "thumbnail": item.thumbnail,
                "source_url": item.source_url,
                "score": rec.score,
            }
        )
        if len(out) >= limit:
            break
    return out
