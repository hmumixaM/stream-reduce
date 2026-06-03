"""Chinese text helpers: normalize everything to Simplified Chinese."""

from __future__ import annotations

import functools


@functools.lru_cache(maxsize=1)
def _t2s():
    from opencc import OpenCC

    return OpenCC("t2s")  # Traditional -> Simplified


def has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def to_simplified(text: str) -> str:
    """Convert Traditional Chinese to Simplified; leave other text untouched."""
    if not text or not has_cjk(text):
        return text
    return _t2s().convert(text)
