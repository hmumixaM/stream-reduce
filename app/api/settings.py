"""Settings endpoint: read effective config and update runtime model overrides."""

from __future__ import annotations

from fastapi import APIRouter

from app.config import get_settings
from app.runtime_config import (
    LLM_MODEL_OPTIONS,
    STT_MODEL_OPTIONS,
    effective_llm_model,
    effective_stt_model,
    effective_summary_map_model,
    set_overrides,
)
from app.schemas import SettingsRead, SettingsUpdate

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _read() -> SettingsRead:
    s = get_settings()
    return SettingsRead(
        llm_base_url=s.llm_base_url,
        llm_model=effective_llm_model(),
        stt_model=effective_stt_model(),
        summary_map_model=effective_summary_map_model(),
        llm_model_default=s.llm_model,
        stt_model_default=s.stt_model,
        summary_map_model_default=s.summary_map_model,
        llm_model_options=LLM_MODEL_OPTIONS,
        stt_model_options=STT_MODEL_OPTIONS,
        transcribe_chunk_seconds=s.transcribe_chunk_seconds,
        transcribe_rate_limit=s.transcribe_rate_limit,
        default_language=s.default_language,
        enable_gemini_audio_fallback=s.enable_gemini_audio_fallback,
        has_openrouter_key=bool(s.openrouter_api_key),
        has_llm_key=bool(s.llm_api_key),
    )


@router.get("", response_model=SettingsRead)
def read_settings() -> SettingsRead:
    return _read()


@router.put("", response_model=SettingsRead)
def update_settings(payload: SettingsUpdate) -> SettingsRead:
    set_overrides(
        {
            "llm_model": payload.llm_model,
            "stt_model": payload.stt_model,
            "summary_map_model": payload.summary_map_model,
        }
    )
    return _read()
