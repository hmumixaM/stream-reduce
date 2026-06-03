"""Runtime-editable model overrides, shared across web + worker via the DB.

Env vars provide the defaults; the UI can override the transcription and summary
models at runtime. Overrides are read per-use (no caching) so a change made in the
web process takes effect on the worker's next job.
"""

from __future__ import annotations

from app.config import get_settings
from app.db import session_scope
from app.models import AppSetting, utcnow

# Keys persisted in the AppSetting table.
KEY_STT_MODEL = "stt_model"
KEY_LLM_MODEL = "llm_model"
KEY_SUMMARY_MAP_MODEL = "summary_map_model"

OVERRIDABLE_KEYS = (KEY_STT_MODEL, KEY_LLM_MODEL, KEY_SUMMARY_MAP_MODEL)

# Curated suggestions surfaced in the UI (free-text entry is still allowed).
STT_MODEL_OPTIONS = [
    "openai/whisper-large-v3-turbo",
    "openai/whisper-1",
    "openai/gpt-4o-transcribe",
    "openai/gpt-4o-mini-transcribe",
    "google/chirp-3",
]
LLM_MODEL_OPTIONS = [
    "gemini-3.5-flash",
    "gemini-3.1-pro-preview",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
]


def get_overrides() -> dict[str, str]:
    with session_scope() as s:
        rows = s.query(AppSetting).all()
        return {r.key: r.value for r in rows if r.key in OVERRIDABLE_KEYS}


def set_overrides(values: dict[str, str | None]) -> None:
    with session_scope() as s:
        for key, value in values.items():
            if key not in OVERRIDABLE_KEYS:
                continue
            row = s.get(AppSetting, key)
            if value is None or value == "":
                if row is not None:
                    s.delete(row)
                continue
            if row is None:
                s.add(AppSetting(key=key, value=value))
            else:
                row.value = value
                row.updated_at = utcnow()
                s.add(row)


def _effective(key: str, default: str) -> str:
    return get_overrides().get(key, default)


def effective_stt_model() -> str:
    return _effective(KEY_STT_MODEL, get_settings().stt_model)


def effective_llm_model() -> str:
    return _effective(KEY_LLM_MODEL, get_settings().llm_model)


def effective_summary_map_model() -> str:
    return _effective(KEY_SUMMARY_MAP_MODEL, get_settings().summary_map_model)
