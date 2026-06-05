"""Semantic search REST endpoint over embedded transcript + summary chunks."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from app.db import get_session
from app.search import SearchUnavailableError, semantic_search

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("")
def search(
    q: str = Query(..., min_length=1, description="natural-language query"),
    k: int = Query(10, ge=1, le=50),
    source: str | None = Query(None, description="filter: transcript | summary"),
    item_id: int | None = Query(None, description="restrict to a single item"),
    session: Session = Depends(get_session),
) -> list[dict]:
    try:
        hits = semantic_search(session, q, k=k, item_id=item_id, source=source)
    except SearchUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return [hit.to_dict() for hit in hits]
