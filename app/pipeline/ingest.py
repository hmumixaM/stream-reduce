"""Ingest stage: resolve a URL to a platform and create a queued Item."""

from __future__ import annotations

from sqlmodel import Session, select

from app.adapters.registry import detect_platform, get_adapter, normalize_url
from app.models import Item, ItemGroup, ItemStatus, Platform
from app.pipeline.playlist import playlist_candidates


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


def create_group_from_url(
    session: Session, url: str
) -> tuple[ItemGroup, list[Item]] | None:
    """If `url` is a playlist/collection, expand it into a group + queued items.

    Returns (group, items) or None when `url` is not a (non-empty) playlist.
    Items already present are reused and (re)attached to the group.
    """
    candidates = playlist_candidates(url)
    if not candidates:
        return None

    platform = detect_platform(url)
    adapter = get_adapter(platform)
    info = None
    for candidate in candidates:
        info = adapter.extract_entries(candidate)
        if info:
            break
    if not info:
        return None

    group = None
    if info.get("external_id"):
        group = session.exec(
            select(ItemGroup).where(ItemGroup.external_id == info["external_id"])
        ).first()
    if group is None:
        group = ItemGroup(
            platform=platform,
            external_id=info.get("external_id"),
            source_url=url,
            title=info.get("title"),
        )
        session.add(group)
        session.commit()
        session.refresh(group)
    elif info.get("title") and group.title != info["title"]:
        group.title = info["title"]

    items: list[Item] = []
    for position, entry in enumerate(info["entries"]):
        item = create_item_from_url(
            session, entry["source_url"], title=entry.get("title")
        )
        item.group_id = group.id
        item.group_position = position
        session.add(item)
        items.append(item)
    group.item_count = len(items)
    session.add(group)
    session.commit()
    for item in items:
        session.refresh(item)
    return group, items
