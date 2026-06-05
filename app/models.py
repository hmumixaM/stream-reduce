"""SQLModel tables for stream-reduce."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from sqlalchemy import Column, Text
from sqlalchemy import Enum as SAEnum
from sqlmodel import JSON, Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


class Platform(str, Enum):
    youtube = "youtube"
    bilibili = "bilibili"
    apple_podcast = "apple_podcast"
    xiaoyuzhou = "xiaoyuzhou"
    rss = "rss"
    unknown = "unknown"


class ItemStatus(str, Enum):
    queued = "queued"
    fetching = "fetching"
    transcribing = "transcribing"
    summarizing = "summarizing"
    done = "done"
    error = "error"


class TranscriptSource(str, Enum):
    native = "native"
    openrouter_whisper = "openrouter_whisper"
    gemini = "gemini"


class StageName(str, Enum):
    download = "download"
    transcribe = "transcribe"
    summarize = "summarize"
    gemini_audio = "gemini_audio"
    embed = "embed"


class ChunkSource(str, Enum):
    transcript = "transcript"
    summary = "summary"


class StageStatus(str, Enum):
    running = "running"
    done = "done"
    error = "error"


class Subscription(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    platform: Platform = Field(
        sa_column=Column(SAEnum(Platform), nullable=False, default=Platform.rss)
    )
    feed_url: str = Field(index=True)
    title: str | None = None
    interval_minutes: int = 60
    enabled: bool = True
    last_checked_at: datetime | None = None
    last_seen_guid: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class ItemGroup(SQLModel, table=True):
    """A folder of items. Either ingested together (a YouTube playlist or a
    Bilibili 合集/系列, with external_id + source_url set) or created by the user
    as a manual folder (source_url left empty). Items keep a `group_id` +
    `group_position` back-reference."""

    id: int | None = Field(default=None, primary_key=True)
    platform: Platform = Field(
        sa_column=Column(SAEnum(Platform), nullable=False, default=Platform.unknown)
    )
    external_id: str | None = Field(default=None, index=True)
    source_url: str = Field(default="", index=True)
    title: str | None = None
    item_count: int = 0
    created_at: datetime = Field(default_factory=utcnow)


class Item(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    platform: Platform = Field(
        sa_column=Column(SAEnum(Platform), nullable=False, default=Platform.unknown)
    )
    source_url: str = Field(index=True)
    external_id: str | None = Field(default=None, index=True)
    title: str | None = None
    author: str | None = None
    description: str | None = Field(default=None, sa_column=Column(Text))
    duration_s: int | None = None
    published_at: datetime | None = None
    thumbnail: str | None = None

    # Engagement metrics captured at crawl time (None when unavailable).
    view_count: int | None = Field(default=None, index=True)
    like_count: int | None = None
    dislike_count: int | None = None
    status: ItemStatus = Field(
        sa_column=Column(SAEnum(ItemStatus), nullable=False, default=ItemStatus.queued)
    )
    error: str | None = Field(default=None, sa_column=Column(Text))
    subscription_id: int | None = Field(default=None, foreign_key="subscription.id", index=True)

    # Playlist / collection grouping (None for standalone items).
    group_id: int | None = Field(default=None, foreign_key="itemgroup.id", index=True)
    group_position: int | None = None

    # Collection flags
    is_favorite: bool = Field(default=False, index=True)
    is_archived: bool = Field(default=False, index=True)

    # Downloaded-media metrics (to judge download completeness)
    media_bytes: int = 0
    audio_duration_s: float | None = None
    # Path of the retained downloaded audio, relative to the media dir (so it can
    # be served at /media/<media_path>, inspected, and deleted from the UI).
    media_path: str | None = None

    # Aggregate processing metrics (rolled up from stage_run)
    enqueued_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    total_processing_ms: int = 0
    total_api_requests: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    retry_count: int = 0

    created_at: datetime = Field(default_factory=utcnow)


class Transcript(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    item_id: int = Field(foreign_key="item.id", index=True)
    language: str | None = None
    source: TranscriptSource = Field(
        sa_column=Column(SAEnum(TranscriptSource), nullable=False)
    )
    # list of {"start": float, "end": float, "text": str}
    segments: list = Field(default_factory=list, sa_column=Column(JSON))
    text: str = Field(default="", sa_column=Column(Text))
    created_at: datetime = Field(default_factory=utcnow)


class Summary(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    item_id: int = Field(foreign_key="item.id", index=True)
    model: str = ""
    prompt_version: str = ""
    markdown: str = Field(default="", sa_column=Column(Text))
    # {"tldr": str, "key_points": [...], "outline": [...], "quotes": [...], "entities": [...]}
    structured: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)


class Chunk(SQLModel, table=True):
    """A semantically-embeddable slice of an item's transcript or summary.

    Vectors live in the ``chunk_vec`` sqlite-vec virtual table keyed by
    ``rowid == chunk.id``; this row carries the text plus locators so a search
    hit can be traced back to the exact source span (timestamp / deep-link).
    Chunks are derived data: they are freely regenerated, never the source of
    truth, and rebuilding them never touches transcript/summary/item rows.
    """

    id: int | None = Field(default=None, primary_key=True)
    item_id: int = Field(foreign_key="item.id", index=True)
    source: ChunkSource = Field(sa_column=Column(SAEnum(ChunkSource), nullable=False))
    # Fine-grained provenance: transcript / tldr / key_point / quote / outline /
    # markdown — lets future knowledge-graph logic weight chunks by kind.
    field: str = ""
    chunk_index: int = 0
    text: str = Field(default="", sa_column=Column(Text))
    # Transcript locators (None for summary chunks).
    start_s: float | None = None
    end_s: float | None = None
    # Character offsets into the source text (None when not applicable).
    char_start: int | None = None
    char_end: int | None = None
    token_count: int = 0
    # sha256 of (normalized text + model); enables idempotent backfill/skip.
    content_hash: str = Field(default="", index=True)
    embedding_model: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class StageRun(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    item_id: int = Field(foreign_key="item.id", index=True)
    stage: StageName = Field(sa_column=Column(SAEnum(StageName), nullable=False))
    status: StageStatus = Field(
        sa_column=Column(SAEnum(StageStatus), nullable=False, default=StageStatus.running)
    )
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    duration_ms: int = 0
    attempts: int = 0
    provider: str | None = None
    model: str | None = None
    request_count: int = 0
    chunk_count: int = 0
    chunk_done: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    http_429_count: int = 0
    error: str | None = Field(default=None, sa_column=Column(Text))


class Comment(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    item_id: int = Field(foreign_key="item.id", index=True)
    body: str = Field(sa_column=Column(Text))
    created_at: datetime = Field(default_factory=utcnow)


class AppSetting(SQLModel, table=True):
    """Runtime-editable overrides (key/value) layered on top of env defaults."""

    key: str = Field(primary_key=True)
    value: str = Field(sa_column=Column(Text))
    updated_at: datetime = Field(default_factory=utcnow)


class ApiCall(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    stage_run_id: int | None = Field(default=None, foreign_key="stagerun.id", index=True)
    item_id: int | None = Field(default=None, foreign_key="item.id", index=True)
    provider: str = ""
    model: str | None = None
    endpoint: str | None = None
    latency_ms: int = 0
    status_code: int | None = None
    tokens: int = 0
    cost_usd: float = 0.0
    created_at: datetime = Field(default_factory=utcnow)
