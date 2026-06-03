"""Subscription polling: fetch a feed, dedupe, and enqueue new items."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import feedparser

from app.adapters.registry import detect_platform
from app.db import session_scope
from app.models import Platform, Subscription
from app.pipeline.ingest import create_item_from_url
from app.queue import enqueue_item

logger = logging.getLogger(__name__)

# Cap how many new items a single poll will enqueue (avoid flooding on first run).
MAX_NEW_PER_POLL = 10


def _entry_guid(entry) -> str | None:
    return getattr(entry, "id", None) or getattr(entry, "link", None)


def _entry_audio(entry) -> str | None:
    for enc in getattr(entry, "enclosures", []) or []:
        href = enc.get("href")
        etype = (enc.get("type") or "").lower()
        if href and ("audio" in etype or "video" in etype or not etype):
            return href
    return None


def _entry_url_and_platform(entry, feed_platform: Platform) -> tuple[str | None, Platform]:
    """Pick the best URL for processing and its platform."""
    link = getattr(entry, "link", None)
    audio = _entry_audio(entry)
    # If the feed links to a supported video page, prefer that (richer metadata
    # and native transcripts). Otherwise use the audio enclosure directly.
    if link:
        platform = detect_platform(link)
        if platform in (Platform.youtube, Platform.bilibili):
            return link, platform
    if audio:
        return audio, Platform.rss
    return link, detect_platform(link) if link else Platform.rss


def _published(entry) -> datetime | None:
    if getattr(entry, "published_parsed", None):
        return datetime(*entry.published_parsed[:6], tzinfo=UTC)
    return None


def poll_one(subscription_id: int) -> int:
    """Poll a single subscription, enqueue new items, return count enqueued."""
    with session_scope() as s:
        sub = s.get(Subscription, subscription_id)
        if sub is None or not sub.enabled:
            return 0
        feed_url = sub.feed_url
        last_seen = sub.last_seen_guid
        feed_platform = sub.platform

    parsed = feedparser.parse(feed_url)
    entries = parsed.entries or []
    if not entries:
        logger.info("subscription %s: no entries", subscription_id)
        with session_scope() as s:
            sub = s.get(Subscription, subscription_id)
            if sub:
                sub.last_checked_at = datetime.now(UTC)
                s.add(sub)
        return 0

    newest_guid = _entry_guid(entries[0])
    new_entries = []
    for entry in entries:
        guid = _entry_guid(entry)
        if last_seen is not None and guid == last_seen:
            break
        new_entries.append(entry)
    # On the very first poll, only take the latest item to avoid a backlog flood.
    if last_seen is None:
        new_entries = new_entries[:1]
    else:
        new_entries = new_entries[:MAX_NEW_PER_POLL]

    enqueued = 0
    for entry in reversed(new_entries):  # oldest first
        url, platform = _entry_url_and_platform(entry, feed_platform)
        if not url:
            continue
        with session_scope() as s:
            item = create_item_from_url(
                s, url,
                platform=platform,
                subscription_id=subscription_id,
                title=getattr(entry, "title", None),
                external_id=_entry_guid(entry),
            )
            published = _published(entry)
            if published and item.published_at is None:
                item.published_at = published
                s.add(item)
            item_id = item.id
            is_new = item.status.value == "queued" and item.started_at is None
        if is_new:
            enqueue_item(item_id)
            enqueued += 1

    with session_scope() as s:
        sub = s.get(Subscription, subscription_id)
        if sub:
            sub.last_checked_at = datetime.now(UTC)
            if newest_guid:
                sub.last_seen_guid = newest_guid
            if not sub.title and parsed.feed:
                sub.title = parsed.feed.get("title")
            s.add(sub)

    logger.info("subscription %s: enqueued %s new items", subscription_id, enqueued)
    return enqueued
