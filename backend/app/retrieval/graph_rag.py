"""Graph RAG retrieval module.

Implements a five-step pipeline:
  1. semantic_search      — embed query, cosine NN via sqlite-vec
  2. fts_search           — BM25 keyword search, stopword-filtered, cap=5
  3. rrf_merge            — rank-fusion of semantic + FTS into unified scores
  4. expand_calls_neighbors — depth-1 CALLS expansion from semantic seeds only,
                              propagated score = parent_rrf_score × 0.6 decay
  5. mmr_diversify        — MMR final selection over unified + neighbor pool

graph_rag_retrieve orchestrates all steps and returns (list[CodeNode], stats_dict).
"""

from __future__ import annotations

import logging
import re
import sqlite3

import networkx as nx
import sqlite_vec

from app.core.model_factory import get_embedding_client
from app.models.schemas import CodeNode
from app.retrieval.reranker import cross_encode_rerank

logger = logging.getLogger(__name__)


def semantic_search(
    query: str,
    repo_path: str,
    top_k: int,
    db_path: str,
    min_similarity: float = 0.15,
) -> list[tuple[str, float]]:
    """Embed query and return top_k (node_id, score) pairs via sqlite-vec cosine search.

    The embedding client is instantiated lazily inside this function body so that
    importing this module does not raise a ValidationError when API keys
    are absent (e.g. during test collection). This matches the lazy-init pattern
    from embedder.py.

    Returns list[tuple[str, float]] — node_id + similarity score pairs.
    Full CodeNode hydration is deferred to graph_rag_retrieve which reads from G.nodes.

    Args:
        query:          Natural language query string to embed.
        repo_path:      Repository root path to scope the sqlite-vec search.
        top_k:          Number of nearest-neighbour results to return.
        db_path:        Path to the SQLite database file.
        min_similarity: Drop nodes with cosine similarity below this threshold
                        before they enter the candidate pool (default 0.15).

    Returns:
        List of (node_id, score) tuples sorted by descending similarity score.
        Score is 1.0 - cosine_distance (0=identical, 2=opposite maps to 1.0→-1.0).
        Nodes below min_similarity are excluded.
    """
    query_vec = get_embedding_client().embed([query])[0]
    query_bytes = sqlite_vec.serialize_float32(query_vec)

    conn = sqlite3.connect(db_path)
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        rows = conn.execute(
            """
            SELECT meta.node_id, vec.distance
            FROM code_embeddings_vec vec
            JOIN code_embeddings_meta meta ON meta.vec_rowid = vec.rowid
            WHERE meta.repo_path = ?
            AND vec.embedding MATCH ?
            AND k = ?
            ORDER BY vec.distance
            """,
            (repo_path, query_bytes, top_k),
        ).fetchall()
    finally:
        conn.close()

    # distance is cosine distance (0=identical, 2=opposite); convert to similarity score
    results = [(row[0], float(1.0 - row[1])) for row in rows]
    return [(node_id, score) for node_id, score in results if score >= min_similarity]


def expand_calls_neighbors(
    seed_ids: list[str],
    seed_scores: dict[str, float],
    G: nx.DiGraph,
    callers_cap: int = 5,
    callees_cap: int = 5,
    decay: float = 0.6,
) -> dict[str, float]:
    """Depth-1 CALLS expansion from semantic seeds with propagated scoring.

    For each seed, fetches its direct callers (predecessors) and callees
    (successors) connected by CALLS edges only — IMPORTS edges are excluded
    to prevent cross-file pollution. Neighbors are capped by pagerank to
    prefer structurally central nodes over peripheral ones.

    Propagated score formula:
        propagated_score = max(parent_rrf_score for parents that brought in node) × decay

    A node brought in by multiple parents takes the best parent's score.
    This means neighbors of strong semantic seeds compete fairly against
    mid-tier seeds, while neighbors of weak seeds stay appropriately subordinate.

    Args:
        seed_ids:    List of semantic seed node IDs to expand from.
        seed_scores: RRF-unified scores for each seed (used as parent scores).
        G:           The code DiGraph with node attributes including pagerank.
        callers_cap: Max callers (predecessors) to add per seed, ordered by pagerank desc.
        callees_cap: Max callees (successors) to add per seed, ordered by pagerank desc.
        decay:       Score decay factor applied to parent score (default 0.6).

    Returns:
        Dict mapping neighbor node_id -> propagated_score. Seeds themselves
        are not included — the caller merges this with unified_scores.
    """
    neighbors: dict[str, float] = {}

    for seed_id in seed_ids:
        if seed_id not in G:
            logger.warning("seed node %s not in graph, skipping", seed_id)
            continue
        parent_score = seed_scores.get(seed_id, 0.0)
        propagated = parent_score * decay

        callees = [
            n for n in G.successors(seed_id)
            if G[seed_id][n].get("type") == "CALLS"
        ]
        callees.sort(key=lambda n: G.nodes[n].get("pagerank", 0.0) if n in G else 0.0, reverse=True)
        for n in callees[:callees_cap]:
            neighbors[n] = max(neighbors.get(n, 0.0), propagated)

        callers = [
            n for n in G.predecessors(seed_id)
            if G[n][seed_id].get("type") == "CALLS"
        ]
        callers.sort(key=lambda n: G.nodes[n].get("pagerank", 0.0) if n in G else 0.0, reverse=True)
        for n in callers[:callers_cap]:
            neighbors[n] = max(neighbors.get(n, 0.0), propagated)

    return neighbors


def mmr_diversify(
    scored: list[tuple[float, CodeNode]],
    max_nodes: int,
    diversity_penalty: float = 0.35,
) -> list[CodeNode]:
    """Maximal Marginal Relevance reranking using file_path as a cluster proxy.

    After score-based ranking, iteratively selects the next node that maximises
    relevance minus a diversity penalty proportional to how many nodes from the
    same file have already been selected. This prevents BFS graph clusters
    (e.g. all methods of one class) from dominating the final result set.

    diversity_penalty is subtracted once per already-selected node from the same
    file. A value of 0.35 means the third node from the same file needs a score
    advantage of 0.70 over a fresh-file node to be selected.

    Args:
        scored:           Pre-scored (score, CodeNode) list, sorted descending.
        max_nodes:        Maximum number of nodes to return.
        diversity_penalty: Per-duplicate penalty subtracted from score (default 0.35).

    Returns:
        Up to max_nodes CodeNode objects selected for both quality and diversity.
    """
    selected: list[CodeNode] = []
    file_counts: dict[str, int] = {}
    remaining = list(scored)  # mutable copy

    while remaining and len(selected) < max_nodes:
        best_idx, best_adjusted = 0, float("-inf")
        for i, (score, node) in enumerate(remaining):
            file_key = node.file_path or ""
            adjusted = score - diversity_penalty * file_counts.get(file_key, 0)
            if adjusted > best_adjusted:
                best_adjusted, best_idx = adjusted, i

        _, node = remaining.pop(best_idx)
        selected.append(node)
        file_key = node.file_path or ""
        file_counts[file_key] = file_counts.get(file_key, 0) + 1

    return selected


_FTS_STOPWORDS: frozenset[str] = frozenset({
    # Question words
    "how", "what", "when", "where", "why", "who", "which",
    # Common verbs
    "is", "are", "was", "were", "be", "been", "being",
    "do", "does", "did", "done", "have", "has", "had",
    "can", "could", "will", "would", "should", "may", "might",
    "use", "used", "using", "work", "works", "make", "makes",
    "add", "added", "get", "set", "run", "runs",
    # Prepositions / conjunctions
    "the", "and", "for", "with", "from", "into", "via",
    "that", "this", "these", "those", "its", "your",
    "you", "not", "also", "then", "than",
    # Code-adjacent noise (appear in nearly every file)
    "def", "class", "return", "import", "pass", "none",
    "true", "false", "self",
})


def rrf_merge(
    ranked_lists: list[list[tuple[str, float]]],
    k: int = 60,
) -> dict[str, float]:
    """Reciprocal Rank Fusion across multiple ranked retrieval result lists.

    RRF score = Σ  1 / (k + rank_i + 1)  for each list where the node appears.
    k=60 is the empirically robust constant that dampens very-high-rank advantages.

    Unlike max()-based merging, RRF is rank-based: immune to score scale differences
    between cosine similarity [0,1] and BM25 scores. A node that ranks high in
    multiple lists scores higher than one that tops only one list.

    Args:
        ranked_lists: Zero or more result lists, each sorted descending by score.
                      Empty lists are silently skipped.
        k:            Damping constant (default 60).

    Returns:
        Dict mapping node_id -> RRF score (unbounded; higher is better).
    """
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, (node_id, _) in enumerate(ranked):
            scores[node_id] = scores.get(node_id, 0.0) + 1.0 / (k + rank + 1)
    return scores


def fts_search(query: str, repo_path: str, top_k: int, db_path: str) -> list[tuple[str, float]]:
    """FTS5 keyword search over indexed symbol names for the given repo.

    Tokenises the query into identifier-like words, strips stopwords, and runs
    a BM25 search over the code_fts table (indexed columns: name, embedding_text).
    Complements semantic search by catching exact/prefix matches that vector
    similarity may miss (e.g. the user types a precise function name).

    Stopword filtering prevents common question words ("how", "what", "use", etc.)
    from flooding the FTS seed set with unrelated matches before BFS expansion.

    Results are scored in [0, 0.85] so that perfect FTS matches rank below
    perfect semantic matches (score 1.0) when the two are merged.

    Returns list[tuple[str, float]] — (node_id, score) pairs, or [] if no
    meaningful keywords remain after stopword filtering.
    """
    # Extract identifier-like tokens; skip very short words to avoid FTS noise
    words = re.findall(r"[a-zA-Z_]\w*", query)
    words = [w for w in words if len(w) > 2 and w.lower() not in _FTS_STOPWORDS]
    if not words:
        return []

    # OR joins give broad recall; FTS5 BM25 ranking handles relevance ordering
    fts_query = " OR ".join(words)

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT f.node_id, f.rank
            FROM code_fts f
            JOIN code_embeddings_meta m ON m.node_id = f.node_id
            WHERE code_fts MATCH ? AND m.repo_path = ?
            ORDER BY rank
            LIMIT ?
            """,
            (fts_query, repo_path, top_k),
        ).fetchall()
    except sqlite3.OperationalError:
        # FTS5 MATCH can raise on certain query strings (special chars, empty vocab)
        return []
    finally:
        conn.close()

    if not rows:
        return []

    # BM25 rank is negative (more negative = better). Normalise to [0, 0.85]:
    #   best result  → 0.85
    #   worst result → proportionally lower
    min_rank = min(r[1] for r in rows)
    if min_rank == 0:
        return [(row[0], 0.5) for row in rows]
    return [(row[0], min(0.85, abs(row[1]) / abs(min_rank) * 0.85)) for row in rows]


def graph_rag_retrieve(
    query: str,
    repo_path: str,
    G: nx.DiGraph,
    db_path: str,
    max_nodes: int = 10,
    hop_depth: int = 1,
    use_cross_encoder: bool = True,
) -> tuple[list[CodeNode], dict]:
    """Orchestrate the Graph RAG retrieval pipeline.

    Step 1 — semantic_search: embed query, cosine NN top-max_nodes.
    Step 2 — fts_search: BM25 keyword search, stopword-filtered, cap=5.
    Step 3 — rrf_merge: rank-fusion of semantic + FTS into unified scores.
    Step 4 — expand_calls_neighbors: depth-1 CALLS-only expansion from
              semantic seeds; each neighbor scored by parent_rrf × 0.6.
              IMPORTS edges excluded to prevent cross-file pollution.
    Step 5 — combine candidate pool: seeds take RRF score, neighbors take
              propagated score (seeds win on overlap).
    Step 5b — cross-encoder rerank (optional): jointly scores (query, node_text)
              pairs over the top 2×max_nodes candidates for more accurate relevance
              discrimination. Skipped if use_cross_encoder=False or CE raises.
    Step 6 — mmr_diversify: diversity-aware final selection.

    hop_depth is retained in the signature for call-site compatibility but
    is ignored internally — expansion is always depth-1 CALLS only.

    Args:
        query:              Natural language query string.
        repo_path:          Repository root path to scope the sqlite-vec search.
        G:                  The code call/import DiGraph with full node attributes.
        db_path:            Path to the SQLite database file.
        max_nodes:          Maximum number of CodeNode objects to return (default 10).
        hop_depth:          Ignored. Retained for call-site compatibility.
        use_cross_encoder:  If True (default), rerank the top 2×max_nodes candidates
                            with the cross-encoder before MMR. Falls back to score
                            order if the model raises.

    Returns:
        Tuple of:
          - list[CodeNode]: Top max_nodes reranked CodeNode objects.
          - dict: Stats dict per spec (seed_count, semantic_seeds, fts_seeds,
                  fts_new, neighbor_count, candidate_pool, returned_count,
                  cross_encoder_used).
    """
    # Step 1: semantic vector search
    semantic_results = semantic_search(query, repo_path, top_k=max_nodes, db_path=db_path)
    semantic_seed_ids = [node_id for node_id, _ in semantic_results]
    semantic_count = len(semantic_results)

    # Step 2: FTS keyword search (no BFS expansion)
    fts_results = fts_search(query, repo_path, top_k=5, db_path=db_path)
    fts_count = len(fts_results)

    # Step 3: RRF merge — immune to scale differences between cosine and BM25
    unified_scores = rrf_merge([semantic_results, fts_results])
    semantic_set = set(semantic_seed_ids)
    fts_new = sum(1 for nid, _ in fts_results if nid not in semantic_set)

    logger.info(
        "retrieval seeds: semantic=%d fts=%d (fts_new=%d) total=%d",
        semantic_count, fts_count, fts_new, len(unified_scores),
    )

    # Step 4: CALLS depth-1 expansion from semantic seeds only
    expanded_neighbors = expand_calls_neighbors(semantic_seed_ids, unified_scores, G)

    # Step 5: combine candidate pool — seeds overwrite neighbors on overlap
    candidate_pool: dict[str, float] = dict(expanded_neighbors)
    candidate_pool.update(unified_scores)  # RRF scores are higher than propagated

    # Test-file penalty applied after merge so it affects both seeds and neighbors
    _TEST_PENALTY = 0.5
    _penalised = 0
    for node_id in list(candidate_pool):
        file_part = node_id.split("::")[0].lower()
        if "test" in file_part or "spec" in file_part:
            candidate_pool[node_id] *= _TEST_PENALTY
            _penalised += 1
    if _penalised:
        logger.debug("test-file penalty applied to %d nodes", _penalised)

    # Hydrate CodeNode objects from graph attributes
    scored: list[tuple[float, CodeNode]] = []
    for node_id, score in candidate_pool.items():
        if node_id not in G:
            continue
        attrs = G.nodes[node_id]
        try:
            node = CodeNode(**{k: v for k, v in attrs.items() if k in CodeNode.model_fields})
            scored.append((score, node))
        except Exception as exc:
            logger.debug("skipping node %s — CodeNode construction failed: %s", node_id, exc)
            continue
    scored.sort(key=lambda x: x[0], reverse=True)

    # Step 5b: Cross-encoder rerank — jointly scores (query, node_text) pairs for
    # more accurate relevance discrimination than cosine similarity alone.
    # Operates on top 2*max_nodes candidates; MMR enforces file diversity after.
    ce_used = False
    ce_floor_dropped = 0
    if use_cross_encoder and scored:
        try:
            scored = cross_encode_rerank(query, scored[:max_nodes * 2], top_n=max_nodes * 2)
            ce_used = True
            # Drop CE-negative nodes before MMR — FILCO-style score floor.
            # cross-encoder/ms-marco-MiniLM-L-6-v2 treats 0 as the relevance boundary;
            # positive = relevant, negative = not relevant.
            pre_floor = len(scored)
            scored = [(ce_score, node) for ce_score, node in scored if ce_score > 0.0]
            ce_floor_dropped = pre_floor - len(scored)
            if ce_floor_dropped:
                logger.debug("CE floor dropped %d nodes with score ≤ 0", ce_floor_dropped)
        except Exception as exc:
            logger.warning("cross-encoder rerank failed, using score order: %s", exc)

    # Step 6: MMR diversity selection
    nodes = mmr_diversify(scored, max_nodes)

    stats = {
        "seed_count": len(unified_scores),
        "semantic_seeds": semantic_count,
        "fts_seeds": fts_count,
        "fts_new": fts_new,
        "neighbor_count": len(expanded_neighbors),
        "candidate_pool": len(candidate_pool),
        "returned_count": len(nodes),
        "cross_encoder_used": ce_used,
        "ce_floor_dropped": ce_floor_dropped,
    }
    return nodes, stats
