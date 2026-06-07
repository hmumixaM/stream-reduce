"""Knowledge-graph REST endpoints: topic clusters, members, related articles."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.db import get_session
from app.graph import (
    GraphFilters,
    cluster_items,
    get_graph,
    primary_cluster,
    related_items,
)
from app.queue import enqueue_graph_build

router = APIRouter(tags=["graph"])


def _parse_folders(folders: str | None) -> list[int]:
    if not folders:
        return []
    return [int(f) for f in folders.split(",") if f.strip().lstrip("-").isdigit()]


@router.get("/api/graph")
def read_graph(
    archived: bool = False,
    favorite: bool = False,
    folders: str | None = Query(None, description="comma-separated folder ids"),
    platform: str | None = None,
    session: Session = Depends(get_session),
) -> dict:
    filters = GraphFilters(
        include_archived=archived,
        favorite=favorite,
        folders=_parse_folders(folders),
        platform=platform or None,
    )
    return get_graph(session, filters)


@router.get("/api/graph/clusters/{cluster_id}/items")
def read_cluster_items(
    cluster_id: int,
    offset: int = 0,
    limit: int = Query(default=50, le=200),
    archived: bool = False,
    favorite: bool = False,
    folders: str | None = None,
    platform: str | None = None,
    session: Session = Depends(get_session),
) -> list[dict]:
    filters = GraphFilters(
        include_archived=archived,
        favorite=favorite,
        folders=_parse_folders(folders),
        platform=platform or None,
    )
    return cluster_items(session, cluster_id, offset=offset, limit=limit, filters=filters)


@router.get("/api/graph/items/{item_id}/cluster")
def read_item_cluster(item_id: int, session: Session = Depends(get_session)) -> dict:
    return {"cluster_id": primary_cluster(session, item_id)}


@router.post("/api/graph/rebuild")
def rebuild_graph() -> dict:
    job_id = enqueue_graph_build(force=True)
    return {"ok": True, "job_id": job_id}


@router.get("/api/items/{item_id}/related")
def read_related(
    item_id: int,
    limit: int = Query(default=8, ge=1, le=24),
    session: Session = Depends(get_session),
) -> list[dict]:
    return related_items(session, item_id, limit=limit)
