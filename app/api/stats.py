"""Aggregate processing/usage statistics for the dashboard."""

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlmodel import Session, func, select

from app.db import get_session
from app.models import Item, StageName, StageRun
from app.schemas import StatsRead

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("", response_model=StatsRead)
def get_stats(session: Session = Depends(get_session)) -> StatsRead:
    total_items = session.exec(select(func.count()).select_from(Item)).one()

    by_status: dict[str, int] = defaultdict(int)
    for status, count in session.exec(
        select(Item.status, func.count()).group_by(Item.status)
    ).all():
        by_status[status.value] = count

    by_platform: dict[str, int] = defaultdict(int)
    for platform, count in session.exec(
        select(Item.platform, func.count()).group_by(Item.platform)
    ).all():
        by_platform[platform.value] = count

    avg_stage: dict[str, float] = {}
    total_stage: dict[str, float] = {}
    for stage, avg_ms, sum_ms in session.exec(
        select(
            StageRun.stage,
            func.avg(StageRun.duration_ms),
            func.sum(StageRun.duration_ms),
        ).group_by(StageRun.stage)
    ).all():
        avg_stage[stage.value] = float(avg_ms or 0)
        total_stage[stage.value] = float(sum_ms or 0)

    def _sum(column, *stages: StageName) -> int:
        stmt = select(func.coalesce(func.sum(column), 0))
        if stages:
            stmt = stmt.where(StageRun.stage.in_([s for s in stages]))
        return int(session.exec(stmt).one() or 0)

    openrouter_requests = _sum(StageRun.request_count, StageName.transcribe)
    openrouter_tokens = _sum(StageRun.total_tokens, StageName.transcribe)
    gemini_tokens = _sum(StageRun.total_tokens, StageName.summarize, StageName.gemini_audio)
    http_429_total = _sum(StageRun.http_429_count)
    total_cost = float(session.exec(
        select(func.coalesce(func.sum(StageRun.cost_usd), 0.0))
    ).one() or 0.0)

    return StatsRead(
        total_items=int(total_items or 0),
        items_by_status=dict(by_status),
        items_by_platform=dict(by_platform),
        avg_stage_ms=avg_stage,
        total_stage_ms=total_stage,
        openrouter_requests=openrouter_requests,
        openrouter_tokens=openrouter_tokens,
        gemini_tokens=gemini_tokens,
        total_cost_usd=total_cost,
        http_429_total=http_429_total,
    )
