"""YouTube adapter (yt-dlp)."""

from __future__ import annotations

from app.adapters.ytdlp_base import YtDlpAdapter


class YouTubeAdapter(YtDlpAdapter):
    name = "youtube"
