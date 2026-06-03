"""Unit tests for subtitle parsing and platform detection."""

from __future__ import annotations

from app.adapters.registry import detect_platform
from app.adapters.subtitles import parse_json3, parse_vtt
from app.models import Platform


def test_parse_vtt_dedup():
    vtt = """WEBVTT

00:00:01.000 --> 00:00:03.000
Hello

00:00:03.000 --> 00:00:05.000
Hello

00:00:05.000 --> 00:00:06.000
World"""
    segs = parse_vtt(vtt)
    assert [s["text"] for s in segs] == ["Hello", "World"]
    assert segs[0]["start"] == 1.0


def test_parse_json3():
    content = (
        '{"events":[{"tStartMs":1000,"dDurationMs":2000,"segs":[{"utf8":"Hi "},{"utf8":"there"}]}]}'
    )
    segs = parse_json3(content)
    assert segs == [{"start": 1.0, "end": 3.0, "text": "Hi there"}]


def test_detect_platform():
    assert detect_platform("https://youtu.be/x") == Platform.youtube
    assert detect_platform("https://www.bilibili.com/video/BV1") == Platform.bilibili
    assert detect_platform("https://podcasts.apple.com/us/podcast/x/id1?i=2") == Platform.apple_podcast
    assert detect_platform("https://www.xiaoyuzhoufm.com/episode/abc") == Platform.xiaoyuzhou
    assert detect_platform("https://example.com/x.mp3") == Platform.rss
