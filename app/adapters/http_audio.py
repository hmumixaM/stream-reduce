"""Helpers for downloading remote audio files over HTTP."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

import httpx

_AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".wav", ".ogg", ".flac", ".opus", ".mp4", ".m4b"}


def looks_like_audio(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in _AUDIO_EXTS)


def _ext_from(url: str, content_type: str | None) -> str:
    path = urlparse(url).path.lower()
    for ext in _AUDIO_EXTS:
        if path.endswith(ext):
            return ext
    if content_type:
        if "mpeg" in content_type:
            return ".mp3"
        if "mp4" in content_type or "m4a" in content_type or "aac" in content_type:
            return ".m4a"
        if "wav" in content_type:
            return ".wav"
        if "ogg" in content_type:
            return ".ogg"
    return ".audio"


def download_url(url: str, dest_dir: Path, basename: str) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", basename)[:80] or "audio"
    with httpx.stream("GET", url, follow_redirects=True, timeout=120) as resp:
        resp.raise_for_status()
        ext = _ext_from(str(resp.url), resp.headers.get("content-type"))
        dest = dest_dir / f"{safe}{ext}"
        with open(dest, "wb") as fh:
            for chunk in resp.iter_bytes(chunk_size=1 << 16):
                fh.write(chunk)
    return dest
