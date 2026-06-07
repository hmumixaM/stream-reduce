"""APScheduler that periodically polls subscriptions and enqueues new items."""

from __future__ import annotations

import logging
from datetime import UTC

from apscheduler.schedulers.background import BackgroundScheduler
from sqlmodel import select

from app.config import get_settings
from app.db import session_scope
from app.models import Subscription
from app.queue import enqueue_graph_build, enqueue_poll

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None
# How often the scheduler wakes up to check which subscriptions are due.
TICK_SECONDS = 60


def _tick() -> None:
    """Enqueue polls for subscriptions whose interval has elapsed."""
    from datetime import datetime, timedelta

    now = datetime.now(UTC)
    due_ids: list[int] = []
    with session_scope() as s:
        subs = s.exec(select(Subscription).where(Subscription.enabled == True)).all()  # noqa: E712
        for sub in subs:
            last = sub.last_checked_at
            if last is not None and last.tzinfo is None:
                last = last.replace(tzinfo=UTC)
            due = last is None or (now - last) >= timedelta(minutes=sub.interval_minutes)
            if due:
                due_ids.append(sub.id)
    for sub_id in due_ids:
        try:
            enqueue_poll(sub_id)
        except Exception:  # noqa: BLE001
            logger.exception("failed to enqueue poll for subscription %s", sub_id)


def _graph_tick() -> None:
    """Enqueue a nightly knowledge-graph rebuild (the job itself skips when the
    chunk fingerprint is unchanged, so this is cheap to fire periodically)."""
    try:
        enqueue_graph_build(force=False)
    except Exception:  # noqa: BLE001
        logger.exception("failed to enqueue graph build")


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    settings = get_settings()
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(_tick, "interval", seconds=TICK_SECONDS, id="poll_subscriptions",
                      next_run_time=None, max_instances=1, coalesce=True)
    if settings.enable_graph and settings.enable_embeddings:
        hours = max(1, settings.graph_rebuild_hours)
        scheduler.add_job(_graph_tick, "interval", hours=hours, id="graph_build",
                          next_run_time=None, max_instances=1, coalesce=True)
    scheduler.start()
    _scheduler = scheduler
    logger.info("subscription scheduler started (tick=%ss)", TICK_SECONDS)
    return scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
