"""Ingest stage: resolve a URL to a platform and create a queued Item."""

from __future__ import annotations

from sqlmodel import Session, select

from app.adapters.registry import detect_platform, normalize_url
from app.models import Item, ItemStatus, Platform


def create_item_from_url(
    session: Session,
    url: str,
    *,
    platform: Platform | None = None,
    subscription_id: int | None = None,
    title: str | None = None,
    external_id: str | None = None,
) -> Item:
    """Create (or return existing) Item for a URL and mark it queued."""
    url = normalize_url(url)
    if not url:
        raise ValueError("empty url")

    existing = session.exec(select(Item).where(Item.source_url == url)).first()
    if existing is not None:
        return existing

    item = Item(
        platform=platform or detect_platform(url),
        source_url=url,
        title=title,
        external_id=external_id,
        subscription_id=subscription_id,
        status=ItemStatus.queued,
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return item
