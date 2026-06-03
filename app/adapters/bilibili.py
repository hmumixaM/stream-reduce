"""Bilibili adapter (yt-dlp). Gated content needs YT_DLP_COOKIES_FILE."""

from __future__ import annotations

from app.adapters.danmaku import fetch_bilibili_danmaku
from app.adapters.ytdlp_base import YtDlpAdapter


class BilibiliAdapter(YtDlpAdapter):
    name = "bilibili"
    # Bilibili returns HTTP 412 without a browser Referer.
    extra_headers = {"Referer": "https://www.bilibili.com/"}

    def get_danmaku(self, url: str) -> list[dict] | None:
        return fetch_bilibili_danmaku(url) or None
