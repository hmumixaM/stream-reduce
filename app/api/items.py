"""Item endpoints: add, list, detail, retry, regenerate, delete."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, col, select

from app.db import get_session
from app.models import Comment, Item, ItemStatus, Platform, StageRun, Summary, Transcript
from app.pipeline.ingest import create_item_from_url
from app.queue import enqueue_item, enqueue_resummarize
from app.schemas import (
    AddItemRequest,
    CommentCreate,
    CommentRead,
    ItemDetail,
    ItemRead,
    StageRunRead,
    SummaryRead,
    TranscriptRead,
)

router = APIRouter(prefix="/api/items", tags=["items"])


@router.post("", response_model=list[ItemRead])
def add_items(payload: AddItemRequest, session: Session = Depends(get_session)) -> list[Item]:
    raw = list(payload.urls or [])
    if payload.url:
        raw.append(payload.url)
    # Each entry may hold several URLs separated by whitespace/newlines/commas.
    urls = [u for entry in raw for u in re.split(r"[\s,]+", entry.strip()) if u]
    if not urls:
        raise HTTPException(status_code=400, detail="no urls provided")

    created: list[Item] = []
    seen_ids: set[int] = set()
    for url in urls:
        item = create_item_from_url(session, url)  # normalizes + dedups vs DB
        if item.id in seen_ids:
            continue
        seen_ids.add(item.id)
        enqueue_item(item.id)
        created.append(item)
    return created


_SORT_COLUMNS = {
    "added": Item.created_at,
    "published": Item.published_at,
    "views": Item.view_count,
    "likes": Item.like_count,
    "duration": Item.duration_s,
}


@router.get("", response_model=list[ItemRead])
def list_items(
    session: Session = Depends(get_session),
    status: ItemStatus | None = None,
    platform: Platform | None = None,
    q: str | None = None,
    favorite: bool | None = None,
    archived: bool | None = None,
    sort: str = "added",
    order: str = "desc",
    limit: int = Query(default=100, le=500),
    offset: int = 0,
) -> list[Item]:
    stmt = select(Item)
    if status is not None:
        stmt = stmt.where(Item.status == status)
    if platform is not None:
        stmt = stmt.where(Item.platform == platform)
    if favorite is not None:
        stmt = stmt.where(Item.is_favorite == favorite)
    if archived is not None:
        stmt = stmt.where(Item.is_archived == archived)
    if q:
        stmt = stmt.where(col(Item.title).ilike(f"%{q}%"))

    sort_col = col(_SORT_COLUMNS.get(sort, Item.created_at))
    ordering = sort_col.asc() if order == "asc" else sort_col.desc()
    # Keep a stable secondary key so rows with NULL/equal sort values stay deterministic.
    stmt = stmt.order_by(ordering, col(Item.created_at).desc()).offset(offset).limit(limit)
    return list(session.exec(stmt).all())


@router.get("/{item_id}", response_model=ItemDetail)
def get_item(item_id: int, session: Session = Depends(get_session)) -> ItemDetail:
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    summary = session.exec(select(Summary).where(Summary.item_id == item_id)).first()
    transcript = session.exec(
        select(Transcript).where(Transcript.item_id == item_id)
    ).first()
    stages = session.exec(
        select(StageRun).where(StageRun.item_id == item_id).order_by(col(StageRun.id))
    ).all()
    comments = session.exec(
        select(Comment).where(Comment.item_id == item_id).order_by(col(Comment.created_at))
    ).all()
    detail = ItemDetail.model_validate(item, from_attributes=True)
    detail.summary = SummaryRead.model_validate(summary, from_attributes=True) if summary else None
    detail.transcript = (
        TranscriptRead.model_validate(transcript, from_attributes=True) if transcript else None
    )
    detail.stages = [StageRunRead.model_validate(s, from_attributes=True) for s in stages]
    detail.comments = [CommentRead.model_validate(c, from_attributes=True) for c in comments]
    return detail


@router.post("/{item_id}/retry", response_model=ItemRead)
def retry_item(item_id: int, session: Session = Depends(get_session)) -> Item:
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    item.status = ItemStatus.queued
    item.error = None
    session.add(item)
    session.commit()
    session.refresh(item)
    enqueue_item(item.id)
    return item


@router.post("/{item_id}/regenerate", response_model=ItemRead)
def regenerate_summary(item_id: int, session: Session = Depends(get_session)) -> Item:
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    transcript = session.exec(
        select(Transcript).where(Transcript.item_id == item_id)
    ).first()
    if transcript is None:
        # No transcript yet: run the full pipeline instead.
        item.status = ItemStatus.queued
        session.add(item)
        session.commit()
        enqueue_item(item.id)
    else:
        # Flip status synchronously so the client immediately sees it is
        # reprocessing and resumes polling for the new summary.
        item.status = ItemStatus.summarizing
        item.error = None
        session.add(item)
        session.commit()
        enqueue_resummarize(item.id)
    session.refresh(item)
    return item


@router.post("/{item_id}/favorite", response_model=ItemRead)
def toggle_favorite(item_id: int, session: Session = Depends(get_session)) -> Item:
    item = _get_or_404(session, item_id)
    item.is_favorite = not item.is_favorite
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


@router.post("/{item_id}/archive", response_model=ItemRead)
def toggle_archive(item_id: int, session: Session = Depends(get_session)) -> Item:
    item = _get_or_404(session, item_id)
    item.is_archived = not item.is_archived
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


@router.post("/{item_id}/comments", response_model=CommentRead)
def add_comment(
    item_id: int, payload: CommentCreate, session: Session = Depends(get_session)
) -> Comment:
    _get_or_404(session, item_id)
    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=400, detail="empty comment")
    comment = Comment(item_id=item_id, body=body)
    session.add(comment)
    session.commit()
    session.refresh(comment)
    return comment


@router.delete("/{item_id}/comments/{comment_id}")
def delete_comment(
    item_id: int, comment_id: int, session: Session = Depends(get_session)
) -> dict:
    comment = session.get(Comment, comment_id)
    if comment is None or comment.item_id != item_id:
        raise HTTPException(status_code=404, detail="comment not found")
    session.delete(comment)
    session.commit()
    return {"ok": True}


@router.delete("/{item_id}")
def delete_item(item_id: int, session: Session = Depends(get_session)) -> dict:
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    for model in (Summary, Transcript, StageRun, Comment):
        for row in session.exec(select(model).where(model.item_id == item_id)).all():
            session.delete(row)
    session.delete(item)
    session.commit()
    return {"ok": True}


def _get_or_404(session: Session, item_id: int) -> Item:
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    return item
