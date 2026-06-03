"""Subtitle parsing helpers (VTT and YouTube json3) into segment lists."""

from __future__ import annotations

import json
import re

_TS = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[.,](\d{1,3})")


def _ts_to_seconds(ts: str) -> float:
    m = _TS.search(ts)
    if not m:
        return 0.0
    h, mm, ss, ms = m.groups()
    return int(h) * 3600 + int(mm) * 60 + int(ss) + int(ms.ljust(3, "0")) / 1000.0


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)  # strip <c> / <00:00:00.000> tags
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    return text.strip()


def parse_vtt(content: str) -> list[dict]:
    """Parse a WebVTT document into deduplicated segments."""
    segments: list[dict] = []
    blocks = re.split(r"\n\s*\n", content.strip())
    last_text = ""
    for block in blocks:
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        time_line = next((ln for ln in lines if "-->" in ln), None)
        if time_line is None:
            continue
        start_raw, _, end_raw = time_line.partition("-->")
        start = _ts_to_seconds(start_raw.strip())
        end = _ts_to_seconds(end_raw.strip().split(" ")[0])
        text_lines = lines[lines.index(time_line) + 1:]
        text = _clean(" ".join(text_lines))
        if not text or text == last_text:
            continue
        last_text = text
        segments.append({"start": round(start, 2), "end": round(end, 2), "text": text})
    segments.sort(key=lambda s: s["start"])
    return segments


def parse_json3(content: str) -> list[dict]:
    """Parse YouTube json3 caption format into segments."""
    data = json.loads(content)
    segments: list[dict] = []
    for event in data.get("events", []):
        segs = event.get("segs")
        if not segs:
            continue
        text = _clean("".join(s.get("utf8", "") for s in segs))
        if not text:
            continue
        start = event.get("tStartMs", 0) / 1000.0
        dur = event.get("dDurationMs", 0) / 1000.0
        segments.append({"start": round(start, 2), "end": round(start + dur, 2), "text": text})
    # YouTube occasionally returns json3 events out of chronological order,
    # which breaks downstream coverage/timestamp logic; sort defensively.
    segments.sort(key=lambda s: s["start"])
    return segments
