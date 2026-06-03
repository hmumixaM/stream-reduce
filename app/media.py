"""Local media (thumbnail) caching so images load same-origin.

Some platforms (notably Bilibili's hdslb.com CDN) hotlink-protect their images
with a Referer check, so they 403 when loaded directly from our UI. We download
them server-side with the right headers and serve them from /media.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx

from app.config import get_settings
from app.models import Platform

logger = logging.getLogger(__name__)

MEDIA_ROUTE = "/media"
THUMB_SUBDIR = "thumbs"

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_REFERERS = {
    Platform.bilibili: "https://www.bilibili.com/",
    Platform.xiaoyuzhou: "https://www.xiaoyuzhoufm.com/",
}
_EXT_BY_TYPE = {"jpeg": ".jpg", "jpg": ".jpg", "png": ".png", "webp": ".webp", "gif": ".gif"}


def _ext(url: str, content_type: str | None) -> str:
    path = urlparse(url).path.lower()
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        if path.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    if content_type:
        for key, ext in _EXT_BY_TYPE.items():
            if key in content_type:
                return ext
    return ".jpg"


def download_thumbnail(url: str, item_id: int, platform: Platform) -> str | None:
    """Download a thumbnail locally and return its served path, or None on failure."""
    if not url:
        return None
    settings = get_settings()
    dest_dir = settings.resolved_media_dir / THUMB_SUBDIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": _UA}
    referer = _REFERERS.get(platform)
    if referer:
        headers["Referer"] = referer
    try:
        resp = httpx.get(url, headers=headers, follow_redirects=True, timeout=30)
        resp.raise_for_status()
    except httpx.HTTPError:
        # A missing thumbnail must never fail the pipeline.
        logger.warning("thumbnail download failed for item %s", item_id, exc_info=True)
        return None
    ext = _ext(str(resp.url), resp.headers.get("content-type"))
    path = dest_dir / f"{item_id}{ext}"
    path.write_bytes(resp.content)
    return f"{MEDIA_ROUTE}/{THUMB_SUBDIR}/{path.name}"
