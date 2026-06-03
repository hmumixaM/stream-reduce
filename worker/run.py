"""RQ worker entrypoint.

Run with: `uv run stream-reduce-worker` or `python -m worker.run`.
"""

from __future__ import annotations

import logging

from rq import SimpleWorker

from app.db import init_db
from app.queue import QUEUE_NAME, get_queue, get_redis


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    init_db()
    # SimpleWorker (no fork) keeps SQLite + connections sane inside containers
    # and serializes work so OpenRouter rate limits are respected.
    worker = SimpleWorker([get_queue()], connection=get_redis())
    logging.getLogger(__name__).info("worker listening on queue '%s'", QUEUE_NAME)
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
