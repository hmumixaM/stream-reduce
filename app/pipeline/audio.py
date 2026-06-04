"""ffmpeg-based audio utilities: probing and chunking."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

_FFMPEG_TIME = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")


def probe_duration(path: str | Path) -> float:
    """Return the container-reported audio duration in seconds (0.0 if unknown).

    This trusts the file header/moov, which can claim the full length even when
    the stream is truncated or corrupt mid-file. Use decodable_duration() when
    you need the *real* playable length.
    """
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


def decodable_duration(path: str | Path) -> float:
    """Return how many seconds ffmpeg can actually DECODE from the file.

    Unlike probe_duration (which trusts the container header), this fully decodes
    the audio stream and reports how far it got. A byte-complete but mid-stream
    corrupt download — a common Bilibili flaky-CDN failure whose header still
    advertises the full duration — reports its true (short) decodable length here.
    """
    proc = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-v", "error", "-stats",
            "-i", str(path), "-vn", "-f", "null", "-",
        ],
        capture_output=True, text=True, check=False,
    )
    matches = _FFMPEG_TIME.findall(proc.stderr)
    if not matches:
        return 0.0
    hours, minutes, seconds = matches[-1]
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


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
