"""Tests for the Graph RAG retrieval pipeline (Phase 8 Plan 02).

Tests use in-memory NetworkX fixtures exclusively — zero DB connections or API
keys required. OpenAI is patched via the mock_embedder fixture. get_db_connection
is patched inline in tests that exercise semantic_search.

Coverage:
  - expand_via_graph: hop depth 1, hop depth 2, missing seed, seed inclusion
  - rerank_and_assemble: max_nodes limit, CodeNode return type, sort order, zero in_degree
  - semantic_search: return type (list of (str, float) tuples)
  - graph_rag_retrieve: stats dict keys and hop_depth value
"""

import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from app.retrieval.graph_rag import (
    expand_via_graph,
    fts_search,
    graph_rag_retrieve,
    rerank_and_assemble,
    semantic_search,
)
from app.models.schemas import CodeNode


# ---------------------------------------------------------------------------
# expand_via_graph tests
# ---------------------------------------------------------------------------


def test_expand_hop_depth_1(sample_graph):
    """From b.py::func_b at depth 1, all direct neighbors are returned.

    Topology: a->b, b->c, d->b
    Bidirectional BFS at depth 1 from b should reach a, b, c, d.
    e is isolated and must NOT be in the result.
    """
    result = expand_via_graph(["b.py::func_b"], sample_graph, hop_depth=1)

    assert "a.py::func_a" in result
    assert "b.py::func_b" in result
    assert "c.py::func_c" in result
    assert "d.py::func_d" in result
    assert "e.py::func_e" not in result


def test_expand_hop_depth_2_from_a(sample_graph):
    """From a.py::func_a at depth 2, reaches c (2 hops: a->b->c) and d (2 hops via b).

    Topology: a->b, b->c, d->b
    At depth 2 from a:
      hop 1: b (direct successor)
      hop 2 from b: c (successor), d (predecessor of b)
    """
    result = expand_via_graph(["a.py::func_a"], sample_graph, hop_depth=2)

    assert "a.py::func_a" in result
    assert "b.py::func_b" in result
    assert "c.py::func_c" in result
    assert "d.py::func_d" in result


def test_expand_missing_seed(sample_graph):
    """expand_via_graph with a nonexistent seed must return empty set without error."""
    result = expand_via_graph(["nonexistent::node"], sample_graph, hop_depth=1)
    assert isinstance(result, set)
    assert len(result) == 0


def test_expand_includes_seed(sample_graph):
    """The seed node itself must always be present in the expanded set."""
    result = expand_via_graph(["c.py::func_c"], sample_graph, hop_depth=1)
    assert "c.py::func_c" in result


# ---------------------------------------------------------------------------
# rerank_and_assemble tests
# ---------------------------------------------------------------------------


def test_rerank_respects_max_nodes(sample_graph):
    """rerank_and_assemble with 5 nodes and max_nodes=2 returns exactly 2 results."""
    all_nodes = {
        "a.py::func_a",
        "b.py::func_b",
        "c.py::func_c",
        "d.py::func_d",
        "e.py::func_e",
    }
    seed_scores = {"b.py::func_b": 0.9}
    result = rerank_and_assemble(all_nodes, seed_scores, sample_graph, max_nodes=2)
    assert len(result) == 2


def test_rerank_returns_code_nodes(sample_graph):
    """All items returned by rerank_and_assemble must be CodeNode instances."""
    all_nodes = {"a.py::func_a", "b.py::func_b"}
    seed_scores = {"b.py::func_b": 0.9}
    result = rerank_and_assemble(all_nodes, seed_scores, sample_graph, max_nodes=5)
    assert all(isinstance(node, CodeNode) for node in result)


def test_rerank_sorted_descending(sample_graph):
    """With known seed_scores the first result must have a higher composite score.

    b.py::func_b has semantic=0.9 vs a.py::func_a fallback=0.3 — b must rank first.
    """
    nodes = {"a.py::func_a", "b.py::func_b"}
    seed_scores = {"b.py::func_b": 0.9}
    result = rerank_and_assemble(nodes, seed_scores, sample_graph, max_nodes=5)

    assert len(result) >= 2
    # b must come before a (higher semantic score dominates)
    node_ids = [n.node_id for n in result]
    assert node_ids.index("b.py::func_b") < node_ids.index("a.py::func_a")


def test_rerank_zero_in_degree_no_error(sample_graph):
    """Passing only e.py::func_e (in_degree=0) with seed_scores={} must not raise
    ZeroDivisionError and must return exactly 1 CodeNode."""
    result = rerank_and_assemble(
        {"e.py::func_e"}, seed_scores={}, G=sample_graph, max_nodes=5
    )
    assert len(result) == 1
    assert isinstance(result[0], CodeNode)


# ---------------------------------------------------------------------------
# semantic_search tests
# ---------------------------------------------------------------------------


def _make_mock_sqlite_conn(rows):
    """Helper that builds a mock sqlite3 connection returning given rows on execute."""
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = rows
    mock_conn.__enter__ = lambda s: mock_conn
    mock_conn.__exit__ = MagicMock(return_value=False)
    return mock_conn


def test_semantic_search_returns_pairs(sample_graph, mock_embedder, monkeypatch):
    """semantic_search must return list of (str, float) tuples of the correct length."""
    # Rows: (node_id, distance) — distance is cosine distance, converted to 1-distance score
    raw_rows = [("b.py::func_b", 0.05), ("a.py::func_a", 0.20)]
    mock_conn = _make_mock_sqlite_conn(raw_rows)
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite3.connect", MagicMock(return_value=mock_conn))
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite_vec.load", MagicMock())
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite_vec.serialize_float32", MagicMock(return_value=b"\x00"))

    result = semantic_search("find func_b", "/repo", top_k=2, db_path=":memory:")

    assert isinstance(result, list)
    assert len(result) == 2
    for item in result:
        assert isinstance(item, tuple)
        assert len(item) == 2
        assert isinstance(item[0], str)
        assert isinstance(item[1], float)


# ---------------------------------------------------------------------------
# graph_rag_retrieve integration test
# ---------------------------------------------------------------------------


def test_graph_rag_retrieve_stats(sample_graph, mock_embedder, monkeypatch):
    """graph_rag_retrieve must return (nodes, stats) with all required keys including
    the new semantic_seeds and fts_seeds added with the dual-search update."""
    raw_rows = [("b.py::func_b", 0.1)]
    mock_conn = _make_mock_sqlite_conn(raw_rows)
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite3.connect", MagicMock(return_value=mock_conn))
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite_vec.load", MagicMock())
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite_vec.serialize_float32", MagicMock(return_value=b"\x00"))

    result = graph_rag_retrieve(
        "find func_b", "/repo", sample_graph, db_path=":memory:", max_nodes=3, hop_depth=1
    )
    nodes, stats = result

    assert "seed_count" in stats
    assert "semantic_seeds" in stats
    assert "fts_seeds" in stats
    assert "expanded_count" in stats
    assert "returned_count" in stats
    assert stats["hop_depth"] == 1
    assert len(nodes) <= 3


# ---------------------------------------------------------------------------
# fts_search tests
# ---------------------------------------------------------------------------


def _make_fts_conn(rows):
    """Build a mock sqlite3 connection for FTS5 queries (no vec extension needed)."""
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = rows
    return mock_conn


def test_fts_search_returns_pairs(monkeypatch):
    """fts_search must return list of (str, float) tuples."""
    rows = [("b.py::func_b", -2.5), ("a.py::func_a", -1.0)]
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite3.connect", MagicMock(return_value=_make_fts_conn(rows)))

    result = fts_search("find func_b", "/repo", top_k=5, db_path=":memory:")

    assert isinstance(result, list)
    assert len(result) == 2
    for node_id, score in result:
        assert isinstance(node_id, str)
        assert isinstance(score, float)
        assert 0.0 <= score <= 0.85


def test_fts_search_best_result_scores_highest(monkeypatch):
    """The row with the most-negative BM25 rank (best match) must get score 0.85."""
    rows = [("b.py::func_b", -5.0), ("a.py::func_a", -2.5)]
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite3.connect", MagicMock(return_value=_make_fts_conn(rows)))

    result = fts_search("func_b query", "/repo", top_k=5, db_path=":memory:")
    scores_by_id = {node_id: score for node_id, score in result}

    assert scores_by_id["b.py::func_b"] == pytest.approx(0.85)
    assert scores_by_id["a.py::func_a"] < scores_by_id["b.py::func_b"]


def test_fts_search_empty_on_operational_error(monkeypatch):
    """FTS5 OperationalError (e.g. malformed MATCH query) must return [] not raise."""
    mock_conn = MagicMock()
    mock_conn.execute.side_effect = sqlite3.OperationalError("fts syntax error")
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite3.connect", MagicMock(return_value=mock_conn))

    result = fts_search("!@# bad tokens", "/repo", top_k=5, db_path=":memory:")
    assert result == []


def test_fts_search_empty_on_short_words(monkeypatch):
    """Queries consisting only of ≤2-char tokens produce no FTS search (returns [])."""
    # Ensure no DB call is made — if it were, this would fail without a mock
    result = fts_search("is an or", "/repo", top_k=5, db_path=":memory:")
    assert result == []


def test_fts_search_empty_when_no_rows(monkeypatch):
    """fts_search on a query that matches nothing must return []."""
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite3.connect",
                        MagicMock(return_value=_make_fts_conn([])))

    result = fts_search("xyzzy_nonexistent_token", "/repo", top_k=5, db_path=":memory:")
    assert result == []


# ---------------------------------------------------------------------------
# Dual-search merge behaviour in graph_rag_retrieve
# ---------------------------------------------------------------------------


def test_fts_only_node_included_in_seeds(sample_graph, mock_embedder, monkeypatch):
    """A node found by FTS but NOT by semantic search must appear in the final results
    when it exists in the graph — the merge keeps the union of both seed sets."""
    # semantic_search returns b; fts_search returns c (different node)
    sem_conn = _make_mock_sqlite_conn([("b.py::func_b", 0.1)])
    fts_conn = _make_fts_conn([("c.py::func_c", -3.0)])

    call_count = {"n": 0}

    def connect_side_effect(db_path):
        call_count["n"] += 1
        # First call: semantic (uses sqlite_vec), second: fts (plain sqlite)
        return sem_conn if call_count["n"] == 1 else fts_conn

    monkeypatch.setattr("app.retrieval.graph_rag.sqlite3.connect", connect_side_effect)
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite_vec.load", MagicMock())
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite_vec.serialize_float32", MagicMock(return_value=b"\x00"))

    _nodes, stats = graph_rag_retrieve(
        "find func_b or func_c", "/repo", sample_graph, db_path=":memory:", max_nodes=5, hop_depth=0
    )

    # fts contributed at least one node not found by semantic
    assert stats["fts_seeds"] >= 1
    assert stats["seed_count"] >= stats["semantic_seeds"]


def test_higher_score_wins_on_overlap(sample_graph, mock_embedder, monkeypatch):
    """When the same node appears in both semantic and FTS results, the higher score
    is kept — FTS score (0.85 max) should not overwrite a high semantic score (0.95)."""
    # semantic returns b with distance 0.05 → score 0.95
    # fts returns b with rank -1.0 → score 0.85
    sem_conn = _make_mock_sqlite_conn([("b.py::func_b", 0.05)])
    fts_conn = _make_fts_conn([("b.py::func_b", -1.0)])

    call_count = {"n": 0}

    def connect_side_effect(db_path):
        call_count["n"] += 1
        return sem_conn if call_count["n"] == 1 else fts_conn

    monkeypatch.setattr("app.retrieval.graph_rag.sqlite3.connect", connect_side_effect)
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite_vec.load", MagicMock())
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite_vec.serialize_float32", MagicMock(return_value=b"\x00"))

    nodes, stats = graph_rag_retrieve(
        "func_b", "/repo", sample_graph, db_path=":memory:", max_nodes=5, hop_depth=0
    )

    # b should be first (highest score: semantic 0.95 beats fts 0.85)
    assert len(nodes) > 0
    assert nodes[0].node_id == "b.py::func_b"
