"""FastAPI application: REST API + static SPA hosting."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import items, queue, settings, stats, subscriptions
from app.config import PROJECT_ROOT, get_settings
from app.db import init_db
from app.media import MEDIA_ROUTE

FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    # Only the web process should run the scheduler (not workers).
    if os.getenv("RUN_SCHEDULER", "1") == "1":
        from app.scheduler import shutdown_scheduler, start_scheduler

        start_scheduler()
        try:
            yield
        finally:
            shutdown_scheduler()
    else:
        yield


app = FastAPI(title="stream-reduce", version="0.1.0", lifespan=lifespan)

app.include_router(items.router)
app.include_router(queue.router)
app.include_router(subscriptions.router)
app.include_router(stats.router)
app.include_router(settings.router)


@app.get("/api/health")
def health() -> dict:
    from app.runtime_config import effective_llm_model, effective_stt_model

    return {
        "status": "ok",
        "stt_model": effective_stt_model(),
        "llm_model": effective_llm_model(),
    }


def _mount_media() -> None:
    settings = get_settings()
    media_root = settings.resolved_media_dir
    media_root.mkdir(parents=True, exist_ok=True)
    app.mount(MEDIA_ROUTE, StaticFiles(directory=media_root), name="media")


_mount_media()


def _mount_spa() -> None:
    if not FRONTEND_DIST.exists():
        return
    assets = FRONTEND_DIST / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):  # noqa: ANN202
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")


_mount_spa()


def run() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    run()
