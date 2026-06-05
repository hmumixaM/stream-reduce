"""Static public-mirror tooling for stream-reduce.

`export` pulls content from a running stream-reduce REST API and writes the
static JSON bundle the mirror SPA reads; `sync` orchestrates tunnel -> build ->
export -> deploy to Cloudflare Pages. Neither touches the live database.
"""
