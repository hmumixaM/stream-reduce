"""Unit tests for playlist/collection URL detection (no network)."""

from __future__ import annotations

from app.pipeline.playlist import is_playlist_url, playlist_candidates

SERIES = "https://space.bilibili.com/14145636/channel/seriesdetail?sid=4891774"
COLLECTION = "https://space.bilibili.com/14145636/channel/collectiondetail?sid=4891774"


def test_bilibili_series_prefers_seriesdetail():
    # 合集 (season) and 系列 (series) share /lists/<sid> but live in separate
    # sid namespaces; ?type=series must resolve to the series, not a same-numbered
    # collection.
    cands = playlist_candidates(
        "https://space.bilibili.com/14145636/lists/4891774?type=series"
    )
    assert cands[0] == SERIES
    assert COLLECTION in cands


def test_bilibili_season_prefers_collectiondetail():
    cands = playlist_candidates(
        "https://space.bilibili.com/14145636/lists/4891774?type=season"
    )
    assert cands[0] == COLLECTION


def test_bilibili_lists_defaults_to_collection_first():
    cands = playlist_candidates("https://space.bilibili.com/14145636/lists/4891774")
    assert cands[0] == COLLECTION


def test_bilibili_lists_query_sid_with_type():
    cands = playlist_candidates(
        "https://space.bilibili.com/14145636/lists?sid=4891774&type=series"
    )
    assert cands[0] == SERIES


def test_youtube_watch_with_list_is_single_video():
    assert playlist_candidates(
        "https://www.youtube.com/watch?v=abc123&list=PL999"
    ) == []


def test_youtube_playlist_page_is_playlist():
    cands = playlist_candidates("https://www.youtube.com/playlist?list=PL999")
    assert cands == ["https://www.youtube.com/playlist?list=PL999"]


def test_non_playlist_url():
    assert is_playlist_url("https://www.bilibili.com/video/BV1jTedzREds") is False
