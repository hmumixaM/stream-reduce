"""Per-stage timing and usage tracking.

A `StageTracker` opens a `stage_run` row, records timing/usage as work proceeds,
and rolls the totals up into the parent `item` aggregates on close.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlmodel import Session

from app.config import get_settings
from app.models import ApiCall, Item, StageName, StageRun, StageStatus


@dataclass
class Usage:
    request_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    http_429_count: int = 0
    calls: list[ApiCall] = field(default_factory=list)


class StageTracker:
    """Context manager that records a single stage attempt."""

    def __init__(self, session: Session, item_id: int, stage: StageName,
                 provider: str | None = None, model: str | None = None):
        self.session = session
        self.item_id = item_id
        self.stage = stage
        self.provider = provider
        self.model = model
        self._start = 0.0
        self.run: StageRun | None = None
        self.usage = Usage()

    def __enter__(self) -> StageTracker:
        self._start = time.monotonic()
        self.run = StageRun(
            item_id=self.item_id,
            stage=self.stage,
            status=StageStatus.running,
            provider=self.provider,
            model=self.model,
            attempts=1,
        )
        self.session.add(self.run)
        self.session.commit()
        self.session.refresh(self.run)
        return self

    def set_chunks(self, total: int) -> None:
        assert self.run is not None
        self.run.chunk_count = total
        self.session.add(self.run)
        self.session.commit()

    def chunk_progress(self, done: int) -> None:
        assert self.run is not None
        self.run.chunk_done = done
        self.session.add(self.run)
        self.session.commit()

    def record_call(self, *, provider: str, model: str | None, endpoint: str,
                    latency_ms: int, status_code: int | None, tokens: int = 0,
                    prompt_tokens: int = 0, completion_tokens: int = 0,
                    cost_usd: float = 0.0, is_429: bool = False) -> None:
        self.usage.request_count += 1
        self.usage.prompt_tokens += prompt_tokens
        self.usage.completion_tokens += completion_tokens
        self.usage.total_tokens += tokens or (prompt_tokens + completion_tokens)
        self.usage.cost_usd += cost_usd
        if is_429:
            self.usage.http_429_count += 1
        if get_settings().track_api_calls:
            call = ApiCall(
                stage_run_id=self.run.id if self.run else None,
                item_id=self.item_id,
                provider=provider,
                model=model,
                endpoint=endpoint,
                latency_ms=latency_ms,
                status_code=status_code,
                tokens=tokens or (prompt_tokens + completion_tokens),
                cost_usd=cost_usd,
            )
            self.session.add(call)
            self.session.commit()

    def __exit__(self, exc_type, exc, tb) -> bool:
        assert self.run is not None
        run = self.run
        run.finished_at = datetime.now(UTC)
        run.duration_ms = int((time.monotonic() - self._start) * 1000)
        run.request_count = self.usage.request_count
        run.prompt_tokens = self.usage.prompt_tokens
        run.completion_tokens = self.usage.completion_tokens
        run.total_tokens = self.usage.total_tokens
        run.cost_usd = self.usage.cost_usd
        run.http_429_count = self.usage.http_429_count
        if exc_type is not None:
            run.status = StageStatus.error
            run.error = f"{exc_type.__name__}: {exc}"[:4000]
        else:
            run.status = StageStatus.done
        self.session.add(run)
        self.session.commit()

        # Roll up into item aggregates.
        item = self.session.get(Item, self.item_id)
        if item is not None:
            item.total_processing_ms += run.duration_ms
            item.total_api_requests += run.request_count
            item.total_tokens += run.total_tokens
            item.total_cost_usd += run.cost_usd
            self.session.add(item)
            self.session.commit()
        return False  # never suppress exceptions
