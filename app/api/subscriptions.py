"""Subscription endpoints: add, list, toggle, poll-now, delete."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, col, select

from app.config import get_settings
from app.db import get_session
from app.models import Subscription
from app.queue import enqueue_poll
from app.schemas import AddSubscriptionRequest, SubscriptionRead

router = APIRouter(prefix="/api/subscriptions", tags=["subscriptions"])


@router.post("", response_model=SubscriptionRead)
def add_subscription(
    payload: AddSubscriptionRequest, session: Session = Depends(get_session)
) -> Subscription:
    feed_url = payload.feed_url.strip()
    if not feed_url:
        raise HTTPException(status_code=400, detail="feed_url required")
    existing = session.exec(
        select(Subscription).where(Subscription.feed_url == feed_url)
    ).first()
    if existing is not None:
        return existing
    sub = Subscription(
        feed_url=feed_url,
        title=payload.title,
        interval_minutes=payload.interval_minutes
        or get_settings().default_poll_interval_minutes,
    )
    session.add(sub)
    session.commit()
    session.refresh(sub)
    return sub


@router.get("", response_model=list[SubscriptionRead])
def list_subscriptions(session: Session = Depends(get_session)) -> list[Subscription]:
    return list(
        session.exec(select(Subscription).order_by(col(Subscription.created_at).desc())).all()
    )


@router.post("/{sub_id}/toggle", response_model=SubscriptionRead)
def toggle_subscription(sub_id: int, session: Session = Depends(get_session)) -> Subscription:
    sub = session.get(Subscription, sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="subscription not found")
    sub.enabled = not sub.enabled
    session.add(sub)
    session.commit()
    session.refresh(sub)
    return sub


@router.post("/{sub_id}/poll")
def poll_now(sub_id: int, session: Session = Depends(get_session)) -> dict:
    sub = session.get(Subscription, sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="subscription not found")
    enqueue_poll(sub_id)
    return {"ok": True}


@router.delete("/{sub_id}")
def delete_subscription(sub_id: int, session: Session = Depends(get_session)) -> dict:
    sub = session.get(Subscription, sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="subscription not found")
    session.delete(sub)
    session.commit()
    return {"ok": True}
