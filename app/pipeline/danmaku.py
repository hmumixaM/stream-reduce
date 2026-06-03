"""Danmaku storage and sentiment/atmosphere summarization.

Danmaku are cached as JSON under ``media_dir/danmaku/{item_id}.json`` during the
download stage, then summarized separately from the spoken content so the report
can show the audience's overall mood.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.config import get_settings
from app.llm import generate_text
from app.models import Item
from app.pipeline.metrics import StageTracker
from app.pipeline.prompts import DANMAKU_SYSTEM, DANMAKU_TEMPLATE

logger = logging.getLogger(__name__)

_MAX_PROMPT_ITEMS = 3000


def _danmaku_dir() -> Path:
    return get_settings().resolved_media_dir / "danmaku"


def danmaku_path(item_id: int) -> Path:
    return _danmaku_dir() / f"{item_id}.json"


def save_danmaku(item_id: int, items: list[dict]) -> None:
    path = danmaku_path(item_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")


def load_danmaku(item_id: int) -> list[dict]:
    path = danmaku_path(item_id)
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _fmt_time(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60:02d}:{s % 60:02d}"


def _render_list(items: list[dict]) -> str:
    lines = [f"[{_fmt_time(d['time'])}] {d['text']}" for d in items[:_MAX_PROMPT_ITEMS]]
    return "\n".join(lines)


def summarize_danmaku(
    items: list[dict], tracker: StageTracker | None = None
) -> dict | None:
    """Run one LLM call to characterize the audience mood from danmaku."""
    if not items:
        return None
    prompt = DANMAKU_TEMPLATE.format(count=len(items), danmaku=_render_list(items))
    result = generate_text(prompt, system=DANMAKU_SYSTEM, max_tokens=4000)
    if tracker is not None:
        from app.runtime_config import effective_llm_model

        tracker.record_call(
            provider="litellm",
            model=effective_llm_model(),
            endpoint="generateContent",
            latency_ms=result.latency_ms,
            status_code=200,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            tokens=result.total_tokens,
        )
    text = result.text.strip()
    if text.startswith("```"):
        nl = text.find("\n")
        text = text[nl + 1 :] if nl != -1 else text
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    try:
        data = json.loads(text.strip("` \n"))
    except json.JSONDecodeError:
        logger.warning("danmaku summary was not valid JSON")
        return None
    data["count"] = len(items)
    return data


def render_danmaku_markdown(item: Item, danmaku: dict) -> list[str]:
    lines: list[str] = []
    count = danmaku.get("count")
    header = "## 弹幕氛围 (Danmaku mood)"
    if count:
        header += f" — {count} 条"
    lines.append(header)

    mood = danmaku.get("overall_mood")
    if mood:
        lines.append(mood)
        lines.append("")

    sentiment = danmaku.get("sentiment") or {}
    if sentiment:
        pos = sentiment.get("positive", 0)
        neu = sentiment.get("neutral", 0)
        neg = sentiment.get("negative", 0)
        lines.append(f"**整体情绪**：😊 正面 {pos}% · 😐 中性 {neu}% · 😞 负面 {neg}%")
        lines.append("")

    themes = danmaku.get("themes") or []
    if themes:
        lines.append("**热议点**")
        for t in themes:
            topic = t.get("topic", "")
            example = t.get("example")
            tail = f" —— “{example}”" if example else ""
            lines.append(f"- **{topic}**{tail}")
        lines.append("")

    highlights = danmaku.get("highlights") or []
    if highlights:
        lines.append("**代表弹幕**")
        for h in highlights:
            # Blank line between each so they render as separate blockquotes
            # rather than collapsing into one run-on paragraph.
            lines.append(f"> {h}")
            lines.append("")

    return lines
