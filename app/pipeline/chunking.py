"""Turn transcripts and summaries into embeddable chunks with locators.

Each chunk carries enough provenance (source, field, timestamps, char offsets)
that a semantic-search hit can be traced back to the exact span of original
text — and, for transcripts, deep-linked to the moment in the media. Chunks are
intentionally kept small (``embed_chunk_chars``) so peak memory stays low.

These are pure functions: no DB, no network. Embedding + persistence happen in
``app/pipeline/embed.py``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.config import get_settings
from app.models import ChunkSource


@dataclass
class ChunkSpec:
    source: ChunkSource
    field: str
    text: str
    start_s: float | None = None
    end_s: float | None = None
    char_start: int | None = None
    char_end: int | None = None

    def content_hash(self, model: str) -> str:
        norm = " ".join(self.text.split())
        payload = f"{self.source.value}|{self.field}|{model}|{norm}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _clean(text: str | None) -> str:
    return (text or "").strip()


def chunk_transcript(segments: list[dict], max_chars: int | None = None) -> list[ChunkSpec]:
    """Window timestamped segments into ~``max_chars`` chunks.

    Char offsets index into the newline-joined transcript text (matching how
    ``Transcript.text`` is built), so a hit maps back to an exact span.
    """
    max_chars = max_chars or get_settings().embed_chunk_chars
    specs: list[ChunkSpec] = []

    cur_lines: list[str] = []
    cur_start: float | None = None
    cur_end: float | None = None
    char_cursor = 0  # running offset into the joined transcript text
    chunk_char_start = 0

    def flush() -> None:
        nonlocal cur_lines, cur_start, cur_end, chunk_char_start
        if not cur_lines:
            return
        text = "\n".join(cur_lines).strip()
        if text:
            specs.append(
                ChunkSpec(
                    source=ChunkSource.transcript,
                    field="transcript",
                    text=text,
                    start_s=cur_start,
                    end_s=cur_end,
                    char_start=chunk_char_start,
                    char_end=char_cursor,
                )
            )
        cur_lines = []
        cur_start = None
        cur_end = None

    for seg in segments:
        line = _clean(seg.get("text"))
        seg_len = len(line)
        # +1 accounts for the newline join between segments.
        if cur_lines and (char_cursor - chunk_char_start) + seg_len > max_chars:
            flush()
            chunk_char_start = char_cursor
        if not cur_lines:
            chunk_char_start = char_cursor
            cur_start = seg.get("start")
        cur_lines.append(line)
        cur_end = seg.get("end", cur_end)
        char_cursor += seg_len + 1  # +1 for the "\n" separator

    flush()
    return specs


def _window_text(text: str, field: str, max_chars: int) -> list[ChunkSpec]:
    """Split a long prose block into paragraph-aligned windows."""
    text = _clean(text)
    if not text:
        return []
    if len(text) <= max_chars:
        return [ChunkSpec(source=ChunkSource.summary, field=field, text=text)]

    specs: list[ChunkSpec] = []
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    buf: list[str] = []
    size = 0
    for para in paragraphs:
        if buf and size + len(para) > max_chars:
            specs.append(
                ChunkSpec(source=ChunkSource.summary, field=field, text="\n\n".join(buf))
            )
            buf = []
            size = 0
        buf.append(para)
        size += len(para) + 2
    if buf:
        specs.append(ChunkSpec(source=ChunkSource.summary, field=field, text="\n\n".join(buf)))
    return specs


def _flatten(value: object) -> str:
    """Render a structured-summary value (str / list / dict) into plain text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        return " — ".join(_flatten(v) for v in value.values() if _flatten(v))
    if isinstance(value, (list, tuple)):
        return "\n".join(_flatten(v) for v in value if _flatten(v))
    return str(value)


# Structured fields whose list entries each become their own chunk.
_LIST_FIELDS = ("key_points", "quotes", "outline", "entities")
# Structured prose fields that get windowed.
_PROSE_FIELDS = ("tldr", "walkthrough", "background", "atmosphere", "danmaku")


def chunk_summary(structured: dict | None, markdown: str | None) -> list[ChunkSpec]:
    """Build summary chunks from structured fields plus the rendered markdown."""
    max_chars = get_settings().embed_chunk_chars
    specs: list[ChunkSpec] = []
    structured = structured or {}

    for field in _PROSE_FIELDS:
        specs.extend(_window_text(_flatten(structured.get(field)), field, max_chars))

    for field in _LIST_FIELDS:
        value = structured.get(field)
        if not isinstance(value, (list, tuple)):
            continue
        singular = field[:-1] if field.endswith("s") else field
        for entry in value:
            text = _flatten(entry)
            if text:
                specs.append(ChunkSpec(source=ChunkSource.summary, field=singular, text=text))

    # Also embed the rendered markdown body so prose phrasing is searchable.
    specs.extend(_window_text(markdown or "", "markdown", max_chars))
    return specs
