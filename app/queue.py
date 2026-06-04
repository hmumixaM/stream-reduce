"""Redis + RQ queue setup and enqueue helpers."""

from __future__ import annotations

from functools import lru_cache

from redis import Redis
from rq import Queue, Retry

from app.config import get_settings

QUEUE_NAME = "stream-reduce"
# Long-form audio transcription + summarization can take a while.
JOB_TIMEOUT = 60 * 90
# Backstop for transient failures (flaky CDN download, provider 5xx) that slip
# past the in-pipeline retries: re-run the whole job with a short backoff.
ITEM_RETRY = Retry(max=2, interval=[120, 600])


@lru_cache
def get_redis() -> Redis:
    return Redis.from_url(get_settings().redis_url)


@lru_cache
def get_queue() -> Queue:
    return Queue(QUEUE_NAME, connection=get_redis(), default_timeout=JOB_TIMEOUT)


def enqueue_item(item_id: int) -> str:
    """Enqueue full processing of an item. Returns the RQ job id."""
    job = get_queue().enqueue(
        "app.pipeline.runner.process_item",
        item_id,
        job_id=f"item-{item_id}",
        result_ttl=3600,
        failure_ttl=86400,
        retry=ITEM_RETRY,
    )
    return job.id


def enqueue_resummarize(item_id: int) -> str:
    job = get_queue().enqueue(
        "app.pipeline.runner.resummarize_item",
        item_id,
        result_ttl=3600,
        failure_ttl=86400,
    )
    return job.id


def enqueue_poll(subscription_id: int) -> str:
    job = get_queue().enqueue(
        "app.pipeline.runner.poll_subscription",
        subscription_id,
        result_ttl=3600,
    )
    return job.id
