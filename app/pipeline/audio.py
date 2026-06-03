"""ffmpeg-based audio utilities: probing and chunking."""

from __future__ import annotations

import subprocess
from pathlib import Path


def probe_duration(path: str | Path) -> float:
    """Return audio duration in seconds (0.0 if unknown)."""
    out = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1",
            str(path),
        ],
        capture_output=True, text=True, check=False,
    )
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def split_audio(path: str | Path, chunk_seconds: int, workdir: Path) -> list[Path]:
    """Split audio into mono 16kHz mp3 chunks suitable for STT.

    Mono/16kHz downsampling matches what STT models use and keeps the
    base64 payload (and thus rate-limit pressure) small.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    pattern = str(workdir / "chunk_%04d.mp3")
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(path),
            "-vn", "-ac", "1", "-ar", "16000",
            "-f", "segment",
            "-segment_time", str(chunk_seconds),
            "-c:a", "libmp3lame", "-q:a", "5",
            pattern,
        ],
        check=True,
    )
    return sorted(workdir.glob("chunk_*.mp3"))
