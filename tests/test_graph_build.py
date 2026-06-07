"""Tests for the topic-cluster knowledge graph.

Pure helpers run anywhere; the end-to-end build test spins up an isolated
sqlite-vec engine (skipped when the extension is unavailable) and exercises the
whole pipeline: kNN graph -> Louvain -> memberships, edges, recommendations, and
the serialized blob.
"""

from __future__ import annotations

from collections import Counter

import pytest

from app.pipeline.graph_build import (
    keywords_from_counter,
    label_from_keywords,
    tokenize,
)


def test_tokenize_latin_filters_stopwords():
    terms = tokenize("The quick brown fox and the lazy dog")
    assert "quick" in terms and "brown" in terms
    assert "the" not in terms and "and" not in terms


def test_tokenize_cjk_bigrams():
    terms = tokenize("机器学习模型")
    assert "机器" in terms and "学习" in terms


def test_keywords_and_label():
    kws = keywords_from_counter(Counter({"python": 5, "async": 3, "fastapi": 2}), top_n=2)
    assert kws == ["python", "async"]
    assert label_from_keywords(kws, 0) == "python · async"
    assert label_from_keywords([], 4) == "Topic 5"


def _vec_engine(tmp_path):
    """An isolated engine with sqlite-vec loaded on every connection."""
    sqlite_vec = pytest.importorskip("sqlite_vec")
    from sqlalchemy import create_engine, event
    from sqlmodel import SQLModel

    url = f"sqlite:///{tmp_path / 'graph_test.db'}"
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _load(dbapi_connection, _record):  # noqa: ANN001
        dbapi_connection.enable_load_extension(True)
        sqlite_vec.load(dbapi_connection)
        dbapi_connection.enable_load_extension(False)

    import app.models  # noqa: F401  register tables

    SQLModel.metadata.create_all(engine)
    return engine


def test_build_graph_end_to_end(tmp_path, monkeypatch):
    sqlite_vec = pytest.importorskip("sqlite_vec")
    np = pytest.importorskip("numpy")
    pytest.importorskip("networkx")

    from sqlalchemy import text as sql_text
    from sqlmodel import Session

    import app.db as db
    from app.config import get_settings
    from app.embedding import l2_normalize
    from app.graph import get_graph, primary_cluster, related_items
    from app.models import Chunk, ChunkSource, Item, Platform

    dim = 8
    settings = get_settings()
    monkeypatch.setattr(settings, "embedding_dim", dim)
    monkeypatch.setattr(settings, "graph_knn_k", 6)
    monkeypatch.setattr(settings, "graph_sim_threshold", 0.3)
    monkeypatch.setattr(settings, "graph_edge_threshold", 0.9)
    monkeypatch.setattr(settings, "graph_louvain_resolution", 1.0)
    monkeypatch.setattr(settings, "enable_graph", True)
    monkeypatch.setattr(settings, "enable_embeddings", True)

    engine = _vec_engine(tmp_path)
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "VEC_AVAILABLE", True)

    with Session(engine) as s:
        s.exec(sql_text(f"CREATE VIRTUAL TABLE chunk_vec USING vec0(embedding float[{dim}])"))
        s.commit()

    # Two well-separated topics: items 1,2 (axis 0) and items 3,4 (axis 1).
    rng = np.random.default_rng(0)
    topics = {1: 0, 2: 0, 3: 1, 4: 1}
    with Session(engine) as s:
        for item_id in topics:
            s.add(Item(id=item_id, platform=Platform.youtube, source_url=f"http://x/{item_id}",
                       title=f"item{item_id}"))
        s.commit()
        for item_id, axis in topics.items():
            for _ in range(3):
                base = np.zeros(dim, dtype=np.float32)
                base[axis] = 1.0
                vec = base + rng.normal(0, 0.05, dim).astype(np.float32)
                chunk = Chunk(item_id=item_id, source=ChunkSource.transcript, field="transcript",
                              text=f"topic {axis} passage about subject{axis}")
                s.add(chunk)
                s.flush()
                s.exec(
                    sql_text("INSERT INTO chunk_vec(rowid, embedding) VALUES (:r, :e)").bindparams(
                        r=chunk.id, e=sqlite_vec.serialize_float32(l2_normalize(vec.tolist()))
                    )
                )
        s.commit()

    from app.pipeline.graph_build import build_graph

    result = build_graph(force=True)
    assert result.get("clusters", 0) >= 2
    assert result["items"] == 4

    with Session(engine) as s:
        graph = get_graph(s)
        assert len(graph["nodes"]) >= 2
        covered = {it["item_id"] for node in graph["nodes"] for it in node["items"]}
        assert covered == {1, 2, 3, 4}

        # Same-topic items recommend each other; cross-topic ones do not.
        rel1 = {r["item_id"] for r in related_items(s, 1)}
        assert 2 in rel1 and 3 not in rel1 and 4 not in rel1

        # An item resolves to a cluster (for graph focus jumps).
        assert primary_cluster(s, 1) is not None
        # Items 1 and 2 share a cluster.
        assert primary_cluster(s, 1) == primary_cluster(s, 2)
