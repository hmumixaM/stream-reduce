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


def test_apple_show_is_playlist():
    url = "https://podcasts.apple.com/us/podcast/openai-podcast/id1820330260"
    assert playlist_candidates(url) == [url]


def test_apple_episode_is_single_item():
    # An episode URL carries ?i=<episode_id> and must not expand.
    assert (
        playlist_candidates(
            "https://podcasts.apple.com/us/podcast/openai-podcast/id1820330260?i=1000771190131"
        )
        == []
    )


def test_xiaoyuzhou_podcast_is_playlist():
    url = "https://www.xiaoyuzhoufm.com/podcast/5e73a1a9418a84a0468aa0bd"
    assert playlist_candidates(url) == [url]


def test_xiaoyuzhou_episode_is_single_item():
    assert (
        playlist_candidates(
            "https://www.xiaoyuzhoufm.com/episode/6714dc9cdb2cf827578d4c9e"
        )
        == []
    )


def test_non_playlist_url():
    assert is_playlist_url("https://www.bilibili.com/video/BV1jTedzREds") is False
