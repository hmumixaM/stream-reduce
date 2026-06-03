"""Fetch Bilibili 弹幕 (danmaku / bullet comments).

Bilibili exposes a representative danmaku pool as XML at
``comment.bilibili.com/{cid}.xml``. The ``cid`` is resolved from the video's
BV id via the public view API.
"""

from __future__ import annotations

import logging
import re

import httpx

logger = logging.getLogger(__name__)

_BV_RE = re.compile(r"(BV[0-9A-Za-z]+)")
_DM_RE = re.compile(r'<d p="([^"]+)">([^<]*)</d>')
_VIEW_API = "https://api.bilibili.com/x/web-interface/view"
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_HEADERS = {"User-Agent": _UA, "Referer": "https://www.bilibili.com/"}


def _bvid(url: str) -> str | None:
    m = _BV_RE.search(url)
    return m.group(1) if m else None


def fetch_bilibili_danmaku(url: str, max_items: int = 4000) -> list[dict]:
    """Return danmaku as [{"time": float, "text": str}] sorted by time.

    Returns [] on any failure; danmaku are optional and must never break ingest.
    """
    bvid = _bvid(url)
    if not bvid:
        return []
    try:
        view = httpx.get(
            _VIEW_API, params={"bvid": bvid}, headers=_HEADERS, timeout=30
        )
        view.raise_for_status()
        cid = view.json()["data"]["cid"]
        resp = httpx.get(
            f"https://comment.bilibili.com/{cid}.xml", headers=_HEADERS, timeout=30
        )
        resp.raise_for_status()
    except (httpx.HTTPError, KeyError, ValueError):
        logger.warning("danmaku fetch failed for %s", url, exc_info=True)
        return []

    resp.encoding = "utf-8"
    items: list[dict] = []
    for attrs, text in _DM_RE.findall(resp.text):
        text = text.strip()
        if not text:
            continue
        items.append({"time": float(attrs.split(",")[0]), "text": text})
    items.sort(key=lambda d: d["time"])
    return items[:max_items]
