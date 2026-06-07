"""Read-side helpers for the topic-cluster knowledge graph.

Serialization + filtered aggregation shared by the build job (which pre-renders
the unfiltered graph into ``graphcache``), the REST API, and the static mirror.
The unfiltered case is a single cache read; filtered requests re-aggregate the
small ``clustermembership`` table in-process (no re-clustering, no vectors).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlmodel import Session, col, select

from app.models import (
    ClusterMembership,
    GraphCache,
    Item,
    ItemRecommendation,
    Platform,
    TopicCluster,
    TopicEdge,
    utcnow,
)

# Member items embedded directly in each graph node for instant render; the rest
# are fetched lazily via the cluster-items endpoint (or embedded in full in the
# mirror's graph.json).
NODE_ITEM_PREVIEW = 12


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


def _item_brief(item: Item, *, weight: float = 0.0, chunk_count: int = 0) -> dict:
    return {
        "id": item.id,
        "item_id": item.id,
        "title": item.title,
        "platform": item.platform.value,
        "author": item.author,
        "thumbnail": item.thumbnail,
        "source_url": item.source_url,
        "weight": round(weight, 4),
        "chunk_count": chunk_count,
    }


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
    """Build the graph payload from normalized tables, optionally restricted to a
    set of item ids (``None`` => the full, unfiltered graph)."""
    clusters = session.exec(select(TopicCluster)).all()
    cluster_by_id = {c.id: c for c in clusters}

    mem_stmt = select(ClusterMembership)
    if allowed_item_ids is not None:
        mem_stmt = mem_stmt.where(col(ClusterMembership.item_id).in_(allowed_item_ids or {-1}))
    memberships = session.exec(mem_stmt).all()

    by_cluster: dict[int, list[ClusterMembership]] = {}
    item_ids: set[int] = set()
    for m in memberships:
        by_cluster.setdefault(m.cluster_id, []).append(m)
        item_ids.add(m.item_id)

    items = session.exec(select(Item).where(col(Item.id).in_(item_ids or {-1}))).all()
    item_by_id = {i.id: i for i in items}

    nodes: list[dict] = []
    surviving: set[int] = set()
    for cluster_id, mems in by_cluster.items():
        cluster = cluster_by_id.get(cluster_id)
        if cluster is None:
            continue
        mems = sorted(mems, key=lambda m: m.weight, reverse=True)
        preview = [
            _item_brief(item_by_id[m.item_id], weight=m.weight, chunk_count=m.chunk_count)
            for m in mems[:NODE_ITEM_PREVIEW]
            if m.item_id in item_by_id
        ]
        if not preview:
            continue
        surviving.add(cluster_id)
        nodes.append(
            {
                "id": cluster_id,
                "label": cluster.label,
                "keywords": cluster.keywords,
                "size": cluster.size,
                "item_count": len(mems),
                "items": preview,
            }
        )

    edges: list[dict] = []
    for e in session.exec(select(TopicEdge)).all():
        if e.src_cluster_id in surviving and e.dst_cluster_id in surviving:
            edges.append(
                {"source": e.src_cluster_id, "target": e.dst_cluster_id, "weight": e.weight}
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
    a cheap membership re-aggregation."""
    if filters is None or filters.is_unfiltered():
        cache = session.get(GraphCache, 1)
        if cache is not None and cache.blob:
            import json

            return json.loads(cache.blob)
        return aggregate_graph(session, allowed_item_ids=None)
    allowed = _allowed_item_ids(session, filters)
    return aggregate_graph(session, allowed_item_ids=allowed)


def cluster_items(
    session: Session,
    cluster_id: int,
    *,
    offset: int = 0,
    limit: int = 50,
    filters: GraphFilters | None = None,
) -> list[dict]:
    """Paginated full member list for a cluster (the panel's 'Show all')."""
    stmt = select(ClusterMembership).where(ClusterMembership.cluster_id == cluster_id)
    if filters is not None and not filters.is_unfiltered():
        allowed = _allowed_item_ids(session, filters)
        stmt = stmt.where(col(ClusterMembership.item_id).in_(allowed or {-1}))
    stmt = stmt.order_by(col(ClusterMembership.weight).desc()).offset(offset).limit(limit)
    mems = session.exec(stmt).all()
    item_by_id = {
        i.id: i
        for i in session.exec(
            select(Item).where(col(Item.id).in_([m.item_id for m in mems] or [-1]))
        ).all()
    }
    return [
        _item_brief(item_by_id[m.item_id], weight=m.weight, chunk_count=m.chunk_count)
        for m in mems
        if m.item_id in item_by_id
    ]


def primary_cluster(session: Session, item_id: int) -> int | None:
    """The cluster an item belongs to most strongly (for graph focus jumps)."""
    m = session.exec(
        select(ClusterMembership)
        .where(ClusterMembership.item_id == item_id)
        .order_by(col(ClusterMembership.weight).desc())
    ).first()
    return m.cluster_id if m is not None else None


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
        brief = _item_brief(item)
        brief["score"] = rec.score
        out.append(brief)
        if len(out) >= limit:
            break
    return out
