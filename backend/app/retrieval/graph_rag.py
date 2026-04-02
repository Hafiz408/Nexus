"""Graph RAG retrieval module for Phase 8.

Implements a three-step pipeline:
  1. semantic_search  — embed query, cosine similarity via sqlite-vec (RAG-01)
  2. expand_via_graph — BFS expansion in both directions via ego_graph (RAG-02)
  3. rerank_and_assemble — score-weighted reranking using exact RAG-03 formula

graph_rag_retrieve orchestrates all three steps and returns (list[CodeNode], stats_dict).
"""

from __future__ import annotations

import logging
import re
import sqlite3

import networkx as nx
import sqlite_vec

from app.core.model_factory import get_embedding_client
from app.models.schemas import CodeNode

logger = logging.getLogger(__name__)


def semantic_search(query: str, repo_path: str, top_k: int, db_path: str) -> list[tuple[str, float]]:
    """Embed query and return top_k (node_id, score) pairs via sqlite-vec cosine search.

    The embedding client is instantiated lazily inside this function body so that
    importing this module does not raise a ValidationError when API keys
    are absent (e.g. during test collection). This matches the lazy-init pattern
    from embedder.py.

    Returns list[tuple[str, float]] — node_id + similarity score pairs.
    Full CodeNode hydration is deferred to graph_rag_retrieve which reads from G.nodes.

    Args:
        query:     Natural language query string to embed.
        repo_path: Repository root path to scope the sqlite-vec search.
        top_k:     Number of nearest-neighbour results to return.
        db_path:   Path to the SQLite database file.

    Returns:
        List of (node_id, score) tuples sorted by descending similarity score.
        Score is 1.0 - cosine_distance (0=identical, 2=opposite maps to 1.0→-1.0).
    """
    query_vec = get_embedding_client().embed([query])[0]
    query_bytes = sqlite_vec.serialize_float32(query_vec)

    conn = sqlite3.connect(db_path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    try:
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
    return [(row[0], float(1.0 - row[1])) for row in rows]


def expand_via_graph(
    seed_node_ids: list[str],
    G: nx.DiGraph,
    hop_depth: int,
    edge_types: list[str] | None = None,
) -> set[str]:
    """BFS expansion from seed nodes in both in- and out-edge directions.

    Uses nx.ego_graph(undirected=True) which calls G.to_undirected() internally
    before BFS — this covers both predecessors (callers) and successors (callees)
    in one call, up to hop_depth hops.

    If edge_types is provided, a zero-copy subgraph view is created first via
    nx.subgraph_view to restrict traversal to only those edge types.

    Args:
        seed_node_ids: List of node IDs to start BFS from.
        G:             The code call/import DiGraph.
        hop_depth:     Number of hops to traverse in each direction.
        edge_types:    Optional list of edge type strings to restrict traversal.
                       None means traverse all edge types.

    Returns:
        Deduplicated set of node IDs reachable from any seed within hop_depth.
    """
    if edge_types is not None:
        # Zero-copy filtered view — avoids copying the full graph
        G_work = nx.subgraph_view(
            G,
            filter_edge=lambda u, v: G[u][v].get("type") in edge_types,
        )
    else:
        G_work = G

    expanded: set[str] = set()
    for node_id in seed_node_ids:
        if node_id not in G_work:
            logger.warning("seed node %s not in graph, skipping", node_id)
            continue
        # ego_graph with undirected=True treats all edges as bidirectional,
        # correctly including both callers (predecessors) and callees (successors).
        # DO NOT use nx.bfs_tree — it only follows outgoing edges on a DiGraph.
        subgraph = nx.ego_graph(G_work, node_id, radius=hop_depth, undirected=True)
        expanded.update(subgraph.nodes())

    return expanded


def rerank_and_assemble(
    expanded_node_ids: set[str],
    seed_scores: dict[str, float],
    G: nx.DiGraph,
    max_nodes: int,
) -> list[CodeNode]:
    """Score each expanded node and return top max_nodes as CodeNode objects.

    Applies the exact RAG-03 formula verbatim:
        score = (semantic_score if seed else 0.3) + (0.2 * pagerank) + (0.1 * in_degree_norm)

    in_degree_norm = node in_degree / max in_degree across all expanded nodes.
    Zero-division guard: max_in_degree defaults to 1 when all nodes have in_degree 0.

    Full CodeNode objects are reconstructed from G.nodes[node_id] attributes —
    the graph stores complete model_dump from the ingestion pipeline, whereas
    code_embeddings_meta only stores (node_id, name, file_path, line_start, line_end).

    Args:
        expanded_node_ids: Set of node IDs from expand_via_graph.
        seed_scores:       Dict mapping seed node_id -> cosine similarity score.
        G:                 The code DiGraph with full node attribute dicts.
        max_nodes:         Maximum number of CodeNode objects to return.

    Returns:
        Top max_nodes CodeNode objects sorted by descending composite score.
    """
    # Compute max in_degree for normalisation — guard against zero-division.
    # Use `or 1` so that a list of all-zeros also yields max_in_degree=1.
    in_degrees = [G.nodes[n].get("in_degree", 0) for n in expanded_node_ids if n in G]
    max_in_degree = (max(in_degrees) if in_degrees else 0) or 1

    scored: list[tuple[float, CodeNode]] = []
    for node_id in expanded_node_ids:
        if node_id not in G:
            continue
        attrs = G.nodes[node_id]

        # Exact RAG-03 formula — do not modify
        semantic = seed_scores.get(node_id, 0.3)  # 0.3 fallback for non-seed nodes
        pagerank = attrs.get("pagerank", 0.0)
        in_degree_norm = attrs.get("in_degree", 0) / max_in_degree
        score = semantic + (0.2 * pagerank) + (0.1 * in_degree_norm)

        # Reconstruct CodeNode from graph attributes (complete model_dump stored there)
        node = CodeNode(**{k: v for k, v in attrs.items() if k in CodeNode.model_fields})
        scored.append((score, node))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [node for _, node in scored[:max_nodes]]


def fts_search(query: str, repo_path: str, top_k: int, db_path: str) -> list[tuple[str, float]]:
    """FTS5 keyword search over indexed symbol names for the given repo.

    Tokenises the query into identifier-like words and runs a BM25 search
    over the code_fts table (indexed column: name). Complements semantic
    search by catching exact/prefix matches that vector similarity may miss
    (e.g. the user types a precise function name).

    Results are scored in [0, 0.85] so that perfect FTS matches rank below
    perfect semantic matches (score 1.0) when the two are merged.

    Returns list[tuple[str, float]] — (node_id, score) pairs.
    """
    # Extract identifier-like tokens; skip very short words to avoid FTS noise
    words = re.findall(r"[a-zA-Z_]\w*", query)
    words = [w for w in words if len(w) > 2]
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
) -> tuple[list[CodeNode], dict]:
    """Orchestrate the full 3-step Graph RAG retrieval pipeline.

    Step 1 — dual search: embed query (semantic) + FTS5 keyword search.
              Results are merged; per-node score = max(semantic, fts).
    Step 2 — expand_via_graph: BFS expand seed node set by hop_depth hops.
    Step 3 — rerank_and_assemble: score-weighted reranking, return top max_nodes.

    Args:
        query:     Natural language query string.
        repo_path: Repository root path to scope the sqlite-vec search.
        G:         The code call/import DiGraph with full node attributes.
        db_path:   Path to the SQLite database file.
        max_nodes: Maximum number of CodeNode objects to return (default 10).
        hop_depth: BFS depth for graph expansion (default 1).

    Returns:
        Tuple of:
          - list[CodeNode]: Top max_nodes reranked CodeNode objects.
          - dict: Stats with seed_count, expanded_count, returned_count, hop_depth,
                  semantic_seeds, fts_seeds.
    """
    # Step 1a: semantic vector search
    seed_results = semantic_search(query, repo_path, top_k=max_nodes, db_path=db_path)
    seed_scores: dict[str, float] = {node_id: score for node_id, score in seed_results}
    semantic_count = len(seed_scores)

    # Step 1b: FTS keyword search — merge, keeping max score per node
    fts_results = fts_search(query, repo_path, top_k=max_nodes, db_path=db_path)
    fts_new = 0
    for node_id, score in fts_results:
        if node_id not in seed_scores:
            fts_new += 1
        if node_id not in seed_scores or score > seed_scores[node_id]:
            seed_scores[node_id] = score
    logger.info(
        "retrieval seeds: semantic=%d fts=%d (fts_new=%d) total=%d",
        semantic_count, len(fts_results), fts_new, len(seed_scores),
    )

    # Step 2: BFS graph expansion from merged seed node IDs
    expanded = expand_via_graph(list(seed_scores.keys()), G, hop_depth)

    # Step 3: score-weighted reranking
    nodes = rerank_and_assemble(expanded, seed_scores, G, max_nodes)

    stats = {
        "seed_count": len(seed_scores),
        "semantic_seeds": semantic_count,
        "fts_seeds": len(fts_results),
        "expanded_count": len(expanded),
        "returned_count": len(nodes),
        "hop_depth": hop_depth,
    }
    return nodes, stats
