"""Detect playlist/collection URLs and expand them into their entries.

A *playlist URL* is one that points at a collection of videos/episodes rather
than a single one: a YouTube `/playlist?list=...`, a Bilibili 合集/系列/收藏夹,
an Apple Podcasts show page, or a Xiaoyuzhou (小宇宙) podcast page. A bare
`watch?v=...&list=...` or an Apple/Xiaoyuzhou *episode* URL is deliberately
treated as a single item.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse


def playlist_candidates(url: str) -> list[str]:
    """Return yt-dlp-extractable playlist URLs for `url`, or [] if it's not one.

    Several candidates may be returned (e.g. Bilibili "lists" can be a 合集 or a
    系列); callers should try them in order and use the first that yields entries.
    """
    url = (url or "").strip()
    if not url:
        return []
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    query = parse_qs(parsed.query)

    # --- YouTube: only real /playlist pages, not watch?v=...&list=... ---
    if any(h in host for h in ("youtube.com", "youtube-nocookie.com")):
        if parsed.path.rstrip("/") == "/playlist":
            list_id = (query.get("list") or [""])[0]
            if list_id:
                return [f"https://www.youtube.com/playlist?list={list_id}"]
        return []

    # --- Bilibili collections / series / favourites ---
    if host == "space.bilibili.com":
        # New unified UI: /<mid>/lists?sid=<sid>  or  /<mid>/lists/<sid>
        m = re.match(r"/(\d+)/lists(?:/(\d+))?", parsed.path)
        if m:
            mid = m.group(1)
            sid = m.group(2) or (query.get("sid") or [""])[0]
            if sid:
                collection = (
                    f"https://space.bilibili.com/{mid}/channel/collectiondetail?sid={sid}"
                )
                series = (
                    f"https://space.bilibili.com/{mid}/channel/seriesdetail?sid={sid}"
                )
                # 合集 (season) and 系列 (series) share the /lists/<sid> shape but
                # live in SEPARATE sid namespaces, so the same number resolves to
                # two unrelated lists. Honor ?type= so we try the right one first;
                # the other stays as a fallback for mislabeled URLs.
                list_type = (query.get("type") or [""])[0].lower()
                if list_type == "series":
                    return [series, collection]
                return [collection, series]
        # Already-canonical collection / series / favourites URLs.
        if any(
            seg in parsed.path
            for seg in ("collectiondetail", "seriesdetail")
        ) or parsed.path.rstrip("/").endswith("/favlist"):
            return [url]
        return []

    # Classic medialist playlists, e.g. bilibili.com/medialist/detail/ml<id>
    if "bilibili.com" in host and parsed.path.startswith("/medialist"):
        return [url]

    # --- Apple Podcasts show page (all episodes) ---
    # A show is /podcast/<slug>/id<digits>; an episode adds ?i=<episode_id>.
    if "podcasts.apple.com" in host or "podcast.apple.com" in host:
        if re.search(r"/id\d+", parsed.path) and "i" not in query:
            return [url]
        return []

    # --- Xiaoyuzhou (小宇宙) podcast page (recent episodes) ---
    if host.endswith("xiaoyuzhoufm.com"):
        if re.match(r"/podcast/[0-9a-fA-F]+", parsed.path):
            return [url]
        return []

    return []


def is_playlist_url(url: str) -> bool:
    return bool(playlist_candidates(url))
