"""Build a knowledge graph of topic clusters from the chunk embeddings.

Lightweight pipeline (no UMAP/HDBSCAN): build a cosine kNN graph over the
existing 768-dim chunk vectors, then run networkx Louvain community detection to
get topic clusters. Memory stays near-flat because the vector matrix is never
loaded into RAM — sqlite-vec keeps vectors on disk and we stream them one at a
time (KNN per chunk for edges; a single streaming pass for centroids).

All derived tables (``topiccluster``, ``clustermembership``, ``topicedge``,
``itemrecommendation``) plus the pre-serialized ``graphcache`` blob are wiped and
rewritten on each build. Runs on the worker, async/nightly, so latency does not
matter. Re-runs are cheap: an unchanged chunk fingerprint skips the whole build.
"""

from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict

from sqlalchemy import text as sql_text
from sqlmodel import Session, col, func, select

from app.config import get_settings
from app.db import session_scope
from app.models import (
    Chunk,
    ClusterMembership,
    GraphCache,
    ItemRecommendation,
    TopicCluster,
    TopicEdge,
)

logger = logging.getLogger(__name__)

# Drop communities smaller than this (noise) — unless that would leave none.
MIN_CLUSTER_CHUNKS = 2
# How many member chunks to sample per cluster for keyword extraction (bounds
# the text scanned for labels on very large clusters).
KEYWORD_SAMPLE = 300
# Max keywords surfaced per cluster.
KEYWORD_TOP_N = 8

# A pragmatic stopword set for the mixed Chinese/English corpus. CJK terms are
# emitted as adjacent-character bigrams (single chars are too ambiguous to be
# useful topic labels).
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "then", "so", "for", "of", "to",
    "in", "on", "at", "by", "is", "are", "was", "were", "be", "been", "being",
    "this", "that", "these", "those", "it", "its", "they", "them", "their", "we",
    "you", "your", "he", "she", "his", "her", "i", "me", "my", "as", "with",
    "from", "about", "into", "than", "too", "very", "can", "will", "just", "not",
    "no", "do", "does", "did", "have", "has", "had", "what", "which", "who",
    "when", "where", "why", "how", "all", "some", "more", "most", "other", "one",
    "也", "了", "的", "是", "在", "我", "有", "和", "就", "不", "人", "都",
    "一", "一个", "这个", "那个", "他们", "我们", "你们", "什么", "可以",
    "这样", "这种", "因为", "所以", "但是", "如果", "已经", "还有", "就是",
    "这", "那", "它", "他", "她", "你",
}

_LATIN_RE = re.compile(r"[A-Za-z][A-Za-z0-9'+\-]{2,}")
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]{2,}")


def tokenize(text: str) -> list[str]:
    """Extract candidate topic terms: latin words + CJK character bigrams."""
    if not text:
        return []
    terms: list[str] = []
    for word in _LATIN_RE.findall(text):
        word = word.lower()
        if word not in _STOPWORDS:
            terms.append(word)
    for run in _CJK_RUN_RE.findall(text):
        for i in range(len(run) - 1):
            bigram = run[i : i + 2]
            if bigram not in _STOPWORDS:
                terms.append(bigram)
    return terms


def keywords_from_counter(counter: Counter, top_n: int = KEYWORD_TOP_N) -> list[str]:
    return [term for term, _ in counter.most_common(top_n)]


def label_from_keywords(keywords: list[str], fallback_index: int) -> str:
    if keywords:
        return " · ".join(keywords[:3])
    return f"Topic {fallback_index + 1}"


def _fingerprint(session: Session) -> str:
    """Content fingerprint of the chunk table; identical => nothing to rebuild."""
    count = int(session.exec(select(func.count()).select_from(Chunk)).one() or 0)
    max_id = int(session.exec(select(func.coalesce(func.max(Chunk.id), 0))).one() or 0)
    max_created = session.exec(select(func.max(Chunk.created_at))).one()
    return f"{count}:{max_id}:{max_created}"


def _to_vector(blob):
    """Decode a sqlite-vec embedding cell into a numpy float32 array."""
    import numpy as np

    if isinstance(blob, (bytes, bytearray, memoryview)):
        return np.frombuffer(bytes(blob), dtype=np.float32)
    if isinstance(blob, str):
        import json

        return np.asarray(json.loads(blob), dtype=np.float32)
    return np.asarray(blob, dtype=np.float32)


def _select_chunk_ids(session: Session, cap: int) -> dict[int, int]:
    """Return an ordered {chunk_id: item_id} map, capped to the most recent
    ``cap`` chunks for very large libraries."""
    rows = session.exec(
        select(Chunk.id, Chunk.item_id).order_by(col(Chunk.id).desc()).limit(cap)
    ).all()
    # Restore ascending order for stable, reproducible processing.
    return {int(cid): int(item_id) for cid, item_id in reversed(rows)}


def _build_knn_graph(id_to_item: dict[int, int], k: int, threshold: float):
    """Stream a sparse cosine kNN graph + cross-article edge weights.

    Each chunk's top-k neighbors come from sqlite-vec's on-disk brute-force KNN,
    so peak memory is the sparse graph, never the full vector matrix.
    """
    import networkx as nx

    graph: nx.Graph = nx.Graph()
    item_pairs: dict[tuple[int, int], float] = defaultdict(float)
    ids = list(id_to_item)
    with session_scope() as session:
        for cid in ids:
            blob = session.exec(
                sql_text("SELECT embedding FROM chunk_vec WHERE rowid = :rid").bindparams(rid=cid)
            ).first()
            if blob is None:
                continue
            neighbors = session.exec(
                sql_text(
                    "SELECT rowid, distance FROM chunk_vec "
                    "WHERE embedding MATCH :q ORDER BY distance LIMIT :n"
                ).bindparams(q=blob[0], n=k + 1)
            ).all()
            item_a = id_to_item[cid]
            for nid, distance in neighbors:
                nid = int(nid)
                if nid == cid or nid not in id_to_item:
                    continue
                # Cosine similarity from unit-vector L2 distance.
                sim = 1.0 - (float(distance) ** 2) / 2.0
                if sim < threshold:
                    continue
                if graph.has_edge(cid, nid):
                    if sim > graph[cid][nid]["weight"]:
                        graph[cid][nid]["weight"] = sim
                else:
                    graph.add_edge(cid, nid, weight=sim)
                item_b = id_to_item[nid]
                if item_a != item_b:
                    key = (item_a, item_b) if item_a < item_b else (item_b, item_a)
                    item_pairs[key] += sim
    return graph, item_pairs


def _communities(graph, resolution: float) -> list[list[int]]:
    from networkx.algorithms.community import louvain_communities

    if graph.number_of_edges() == 0:
        return []
    comms = louvain_communities(graph, weight="weight", resolution=resolution, seed=42)
    kept = [sorted(c) for c in comms if len(c) >= MIN_CLUSTER_CHUNKS]
    if not kept:
        kept = [sorted(c) for c in comms]
    # Largest topics first for stable, readable ordering.
    kept.sort(key=len, reverse=True)
    return kept


def _centroids(chunk_cluster: dict[int, int], n_clusters: int, dim: int):
    import numpy as np

    sums = np.zeros((n_clusters, dim), dtype=np.float64)
    counts = np.zeros(n_clusters, dtype=np.float64)
    wanted = set(chunk_cluster)
    with session_scope() as session:
        rows = session.exec(sql_text("SELECT rowid, embedding FROM chunk_vec"))
        for rowid, blob in rows:
            rowid = int(rowid)
            if rowid not in wanted:
                continue
            vec = _to_vector(blob)
            if vec.shape[0] != dim:
                continue
            sums[chunk_cluster[rowid]] += vec
            counts[chunk_cluster[rowid]] += 1
    centroids = sums / np.maximum(counts[:, None], 1.0)
    norms = np.linalg.norm(centroids, axis=1, keepdims=True)
    return centroids / np.maximum(norms, 1e-9)


def _cluster_keywords(chunk_cluster: dict[int, int], n_clusters: int) -> list[list[str]]:
    counters = [Counter() for _ in range(n_clusters)]
    sampled = defaultdict(int)
    wanted = set(chunk_cluster)
    with session_scope() as session:
        rows = session.exec(select(Chunk.id, Chunk.text))
        for cid, text in rows:
            cid = int(cid)
            if cid not in wanted:
                continue
            cl = chunk_cluster[cid]
            if sampled[cl] >= KEYWORD_SAMPLE:
                continue
            sampled[cl] += 1
            counters[cl].update(tokenize(text or ""))
    return [keywords_from_counter(c) for c in counters]


def _edges(centroids, threshold: float, top_k: int) -> dict[tuple[int, int], float]:
    import numpy as np

    n = centroids.shape[0]
    pairs: dict[tuple[int, int], float] = {}
    if n < 2:
        return pairs
    sim = centroids @ centroids.T
    for i in range(n):
        order = np.argsort(-sim[i])
        kept = 0
        for j in order:
            j = int(j)
            if j == i:
                continue
            w = float(sim[i, j])
            if w < threshold:
                break
            key = (i, j) if i < j else (j, i)
            if key not in pairs or w > pairs[key]:
                pairs[key] = w
            kept += 1
            if kept >= top_k:
                break
    return pairs


def _recommendations(
    item_pairs: dict[tuple[int, int], float], top_k: int
) -> dict[int, list[tuple[int, float]]]:
    neighbors: dict[int, list[tuple[int, float]]] = defaultdict(list)
    for (a, b), w in item_pairs.items():
        neighbors[a].append((b, w))
        neighbors[b].append((a, w))
    return {
        item: sorted(rel, key=lambda t: t[1], reverse=True)[:top_k]
        for item, rel in neighbors.items()
    }


def _wipe(session: Session) -> None:
    for table in ("clustermembership", "topicedge", "itemrecommendation", "topiccluster"):
        session.exec(sql_text(f"DELETE FROM {table}"))


def build_graph(force: bool = False) -> dict:
    """(Re)build the topic-cluster knowledge graph. Returns a summary dict."""
    settings = get_settings()
    from app import db

    if not settings.enable_graph or not settings.enable_embeddings or not db.VEC_AVAILABLE:
        logger.info("graph build skipped (disabled or sqlite-vec unavailable)")
        return {"skipped": True, "reason": "disabled"}

    with session_scope() as session:
        fingerprint = _fingerprint(session)
        cache = session.get(GraphCache, 1)
        if (
            not force
            and cache is not None
            and cache.fingerprint == fingerprint
            and cache.cluster_count > 0
        ):
            logger.info("graph build skipped (fingerprint unchanged: %s)", fingerprint)
            return {"skipped": True, "reason": "unchanged", "fingerprint": fingerprint}
        id_to_item = _select_chunk_ids(session, settings.graph_max_chunks)
        build_id = (cache.build_id + 1) if cache is not None else 1

    if not id_to_item:
        logger.info("graph build: no chunks to cluster")
        return {"skipped": True, "reason": "no_chunks"}

    graph, item_pairs = _build_knn_graph(
        id_to_item, settings.graph_knn_k, settings.graph_sim_threshold
    )
    communities = _communities(graph, settings.graph_louvain_resolution)
    if not communities:
        logger.info("graph build: no communities found")
        return {"skipped": True, "reason": "no_communities"}

    chunk_cluster: dict[int, int] = {}
    for idx, comm in enumerate(communities):
        for cid in comm:
            chunk_cluster[cid] = idx
    n_clusters = len(communities)

    item_cluster_counts: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    item_total: dict[int, int] = defaultdict(int)
    for cid, cl in chunk_cluster.items():
        it = id_to_item[cid]
        item_cluster_counts[it][cl] += 1
        item_total[it] += 1

    centroids = _centroids(chunk_cluster, n_clusters, settings.embedding_dim)
    keywords = _cluster_keywords(chunk_cluster, n_clusters)
    edge_pairs = _edges(centroids, settings.graph_edge_threshold, settings.graph_edge_top_k)
    recs = _recommendations(item_pairs, settings.graph_related_top_k)

    with session_scope() as session:
        _wipe(session)
        local_to_db: dict[int, int] = {}
        for idx, comm in enumerate(communities):
            item_count = len({id_to_item[c] for c in comm})
            cluster = TopicCluster(
                build_id=build_id,
                label=label_from_keywords(keywords[idx], idx),
                keywords=keywords[idx],
                size=len(comm),
                item_count=item_count,
            )
            session.add(cluster)
            session.flush()
            local_to_db[idx] = cluster.id

        for item_id, clmap in item_cluster_counts.items():
            for cl, cnt in clmap.items():
                session.add(
                    ClusterMembership(
                        cluster_id=local_to_db[cl],
                        item_id=item_id,
                        chunk_count=cnt,
                        weight=cnt / max(item_total[item_id], 1),
                    )
                )

        for (i, j), w in edge_pairs.items():
            a, b = local_to_db[i], local_to_db[j]
            src, dst = (a, b) if a < b else (b, a)
            session.add(TopicEdge(src_cluster_id=src, dst_cluster_id=dst, weight=round(w, 4)))

        for item_id, rel in recs.items():
            for other, score in rel:
                session.add(
                    ItemRecommendation(
                        item_id=item_id, related_item_id=other, score=round(score, 4)
                    )
                )
        session.flush()

        # Pre-serialize the unfiltered graph for zero-compute reads (live unified
        # view + the static mirror).
        from app.graph import aggregate_graph

        blob = aggregate_graph(session, allowed_item_ids=None, build_id=build_id)
        import json

        if cache is None:
            cache = GraphCache(id=1)
        cache = session.get(GraphCache, 1) or GraphCache(id=1)
        cache.build_id = build_id
        cache.blob = json.dumps(blob, ensure_ascii=False)
        cache.fingerprint = fingerprint
        cache.cluster_count = n_clusters
        cache.item_count = len(item_total)
        from app.models import utcnow

        cache.built_at = utcnow()
        session.add(cache)

    result = {
        "build_id": build_id,
        "clusters": n_clusters,
        "items": len(item_total),
        "edges": len(edge_pairs),
        "recommendations": sum(len(r) for r in recs.values()),
        "fingerprint": fingerprint,
    }
    logger.info("graph build complete: %s", result)
    return result


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    import argparse

    from app.db import init_db

    parser = argparse.ArgumentParser(description="Build the topic-cluster knowledge graph.")
    parser.add_argument("--force", action="store_true", help="rebuild even if unchanged")
    args = parser.parse_args()
    init_db()
    result = build_graph(force=args.force)
    print(result)


if __name__ == "__main__":
    main()
