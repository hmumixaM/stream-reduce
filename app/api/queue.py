"""Queue view: items currently being processed or failed, with live progress."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session, col, select

from app.db import get_session
from app.models import Item, ItemStatus, StageRun, StageStatus
from app.schemas import QueueItemRead

router = APIRouter(prefix="/api/queue", tags=["queue"])

ACTIVE = (
    ItemStatus.queued,
    ItemStatus.fetching,
    ItemStatus.transcribing,
    ItemStatus.summarizing,
)


@router.get("", response_model=list[QueueItemRead])
def list_queue(session: Session = Depends(get_session)) -> list[QueueItemRead]:
    statuses = [s.value for s in ACTIVE] + [ItemStatus.error.value]
    stmt = (
        select(Item)
        .where(col(Item.status).in_(statuses))
        .order_by(col(Item.enqueued_at).desc())
    )
    items = session.exec(stmt).all()
    out: list[QueueItemRead] = []
    for item in items:
        running = session.exec(
            select(StageRun)
            .where(StageRun.item_id == item.id, StageRun.status == StageStatus.running)
            .order_by(col(StageRun.id).desc())
        ).first()
        q = QueueItemRead.model_validate(item, from_attributes=True)
        if running is not None:
            q.current_stage = running.stage
            q.chunk_done = running.chunk_done
            q.chunk_count = running.chunk_count
        out.append(q)
    return out
