"""Improved Graph RAG retrieval pipeline.

Extends the baseline graph_rag_retrieve with four improvements:

  1. HyDE query expansion  — generates a hypothetical code answer to bridge
     the NL-to-code vocabulary gap before semantic search.
  2. RRF seed fusion       — replaces max()-score merging with Reciprocal Rank
     Fusion across semantic, HyDE, and FTS result lists, then normalises to [0,1].
  3. BFS score threshold   — only BFS-expands seeds whose normalised RRF score
     meets or exceeds `bfs_score_threshold`, cutting noise from weak seeds.
  4. Cross-encoder rerank  — replaces MMR with a cross-encoder that jointly reads
     (query, context) to produce accurate relevance scores for final selection.
"""

from __future__ import annotations

import logging

import networkx as nx

from app.models.schemas import CodeNode
from app.retrieval.graph_rag import (
    expand_via_graph,
    fts_search,
    mmr_diversify,
    rerank_and_assemble,
    rrf_merge,
    semantic_search,
)
from app.retrieval.query_expansion import hyde_expand
from app.retrieval.reranker import cross_encode_rerank

logger = logging.getLogger(__name__)

_TEST_PENALTY = 0.5


async def improved_graph_rag_retrieve(
    query: str,
    repo_path: str,
    G: nx.DiGraph,
    db_path: str,
    max_nodes: int = 10,
    hop_depth: int = 1,
    use_hyde: bool = True,
    use_cross_encoder: bool = True,
    bfs_score_threshold: float = 0.45,
) -> tuple[list[CodeNode], dict]:
    """Improved Graph RAG: HyDE + RRF + BFS-threshold + cross-encoder rerank.

    Args:
        query:               Original user query string.
        repo_path:           Repository root path for scoped DB queries.
        G:                   Code call/import DiGraph with full node attributes.
        db_path:             Path to the SQLite database file.
        max_nodes:           Final number of CodeNode objects to return.
        hop_depth:           BFS depth for graph expansion from strong seeds.
        use_hyde:            Generate a hypothetical code snippet pre-retrieval.
                             Falls back gracefully if the LLM call fails.
        use_cross_encoder:   Apply cross-encoder as the final selection step.
                             Falls back to MMR if False.
        bfs_score_threshold: Min raw semantic similarity score for BFS expansion.
                             Seeds below this threshold are added to the candidate pool
                             directly without expanding their graph neighbours.

    Returns:
        Tuple of (list[CodeNode], stats_dict).
    """
    # ── 1. HyDE expansion ────────────────────────────────────────────────────
    hyde_text = ""
    if use_hyde:
        hyde_text = await hyde_expand(query)

    # ── 2. Semantic search (original + HyDE) ─────────────────────────────────
    seed_results = semantic_search(query, repo_path, top_k=max_nodes, db_path=db_path)
    semantic_seed_ids = {node_id for node_id, _ in seed_results}

    hyde_results: list[tuple[str, float]] = []
    if hyde_text:
        hyde_results = semantic_search(hyde_text, repo_path, top_k=max_nodes, db_path=db_path)

    # ── 3. FTS keyword search ─────────────────────────────────────────────────
    fts_results = fts_search(query, repo_path, top_k=5, db_path=db_path)

    # ── 4. RRF merge + normalise to [0, 1] ───────────────────────────────────
    lists_to_merge = [lst for lst in [seed_results, hyde_results, fts_results] if lst]
    rrf_scores = rrf_merge(lists_to_merge)
    max_rrf = max(rrf_scores.values()) if rrf_scores else 1.0
    seed_scores: dict[str, float] = {
        nid: s / max_rrf for nid, s in rrf_scores.items()
    }

    # ── 5. Test-file penalty ─────────────────────────────────────────────────
    penalised = 0
    for node_id in list(seed_scores):
        file_part = node_id.split("::")[0].lower()
        if "test" in file_part or "spec" in file_part:
            seed_scores[node_id] *= _TEST_PENALTY
            penalised += 1
    if penalised:
        logger.debug("test-file penalty applied to %d seeds", penalised)

    # ── 6. BFS expansion with score threshold ────────────────────────────────
    # Use raw semantic similarity scores (not RRF-normalised) for BFS gating,
    # since the threshold is meant to filter weak query-relevance candidates.
    raw_semantic_scores: dict[str, float] = dict(seed_results)
    strong_seeds = [
        nid for nid in semantic_seed_ids
        if raw_semantic_scores.get(nid, 0.0) >= bfs_score_threshold
    ]
    expanded = expand_via_graph(strong_seeds, G, hop_depth)
    expanded.update(seed_scores.keys())  # add all seeds (weak + FTS-only) directly

    logger.info(
        "improved_rag: semantic=%d hyde=%d fts=%d strong_bfs=%d expanded=%d",
        len(semantic_seed_ids), len(hyde_results), len(fts_results),
        len(strong_seeds), len(expanded),
    )

    # ── 7. Dual-score rerank over 2× candidate pool ───────────────────────────
    scored = rerank_and_assemble(expanded, seed_scores, G, max_nodes * 2)

    # ── 8. Final selection ────────────────────────────────────────────────────
    if use_cross_encoder and scored:
        reranked = cross_encode_rerank(query, scored, top_n=max_nodes)
        nodes = [n for _, n in reranked]
    else:
        nodes = mmr_diversify(scored, max_nodes)

    stats = {
        "seed_count": len(seed_scores),
        "semantic_seeds": len(semantic_seed_ids),
        "fts_seeds": len(fts_results),
        "hyde_used": bool(hyde_text),
        "expanded_count": len(expanded),
        "returned_count": len(nodes),
        "hop_depth": hop_depth,
        "strong_bfs_seeds": len(strong_seeds),
    }
    return nodes, stats
