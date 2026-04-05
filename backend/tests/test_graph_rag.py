"""Tests for the Graph RAG retrieval pipeline (Graph RAG v2).

Tests use in-memory NetworkX fixtures exclusively — zero DB connections or API
keys required. OpenAI is patched via the mock_embedder fixture. sqlite3.connect
is patched inline in tests that exercise semantic_search / fts_search.

Coverage:
  - expand_calls_neighbors: callees, callers, propagated score, decay, multi-seed,
                             IMPORTS edges ignored, missing seed, cap enforcement
  - semantic_search: return type (list of (str, float) tuples)
  - fts_search: score normalisation, OperationalError guard, stopword filtering
  - graph_rag_retrieve: stats dict keys, node cap, FTS-only seed included,
                        dual-search merge behaviour
"""

import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from app.retrieval.graph_rag import (
    expand_calls_neighbors,
    fts_search,
    graph_rag_retrieve,
    semantic_search,
)
from app.models.schemas import CodeNode


# ---------------------------------------------------------------------------
# expand_calls_neighbors tests
# sample_graph topology (all CALLS edges):
#   a.py::func_a -> b.py::func_b
#   b.py::func_b -> c.py::func_c
#   d.py::func_d -> b.py::func_b
#   e.py::func_e  (isolated)
# ---------------------------------------------------------------------------


def test_expand_calls_callees(sample_graph):
    """Callees (successors with CALLS edge) of func_a are returned."""
    scores = {"a.py::func_a": 0.016}
    result = expand_calls_neighbors(["a.py::func_a"], scores, sample_graph)
    assert "b.py::func_b" in result


def test_expand_calls_callers(sample_graph):
    """Callers (predecessors with CALLS edge) of func_b are returned."""
    scores = {"b.py::func_b": 0.016}
    result = expand_calls_neighbors(["b.py::func_b"], scores, sample_graph)
    assert "a.py::func_a" in result
    assert "d.py::func_d" in result


def test_expand_calls_propagated_score(sample_graph):
    """Propagated score = parent_rrf_score × decay (default 0.6)."""
    parent_score = 0.020
    scores = {"a.py::func_a": parent_score}
    result = expand_calls_neighbors(["a.py::func_a"], scores, sample_graph)
    assert "b.py::func_b" in result
    assert abs(result["b.py::func_b"] - parent_score * 0.6) < 1e-9


def test_expand_calls_best_parent_wins(sample_graph):
    """When two seeds both bring in the same neighbor, the higher propagated score wins."""
    # Both a and d call b; a has higher score so b should get a's propagated score
    scores = {"a.py::func_a": 0.020, "d.py::func_d": 0.010}
    result = expand_calls_neighbors(["a.py::func_a", "d.py::func_d"], scores, sample_graph)
    assert "b.py::func_b" in result
    assert abs(result["b.py::func_b"] - 0.020 * 0.6) < 1e-9


def test_expand_calls_custom_decay(sample_graph):
    """Custom decay factor is applied correctly."""
    scores = {"a.py::func_a": 0.020}
    result = expand_calls_neighbors(["a.py::func_a"], scores, sample_graph, decay=0.5)
    assert abs(result["b.py::func_b"] - 0.020 * 0.5) < 1e-9


def test_expand_calls_isolated_node_returns_empty(sample_graph):
    """A seed with no CALLS edges produces no neighbors."""
    scores = {"e.py::func_e": 0.016}
    result = expand_calls_neighbors(["e.py::func_e"], scores, sample_graph)
    assert result == {}


def test_expand_calls_missing_seed_no_error(sample_graph):
    """A nonexistent seed is silently skipped — no KeyError raised."""
    scores = {"nonexistent::node": 0.016}
    result = expand_calls_neighbors(["nonexistent::node"], scores, sample_graph)
    assert isinstance(result, dict)
    assert len(result) == 0


def test_expand_calls_seeds_not_in_result(sample_graph):
    """Seed nodes themselves are never included in the returned neighbors dict."""
    scores = {"b.py::func_b": 0.020}
    result = expand_calls_neighbors(["b.py::func_b"], scores, sample_graph)
    assert "b.py::func_b" not in result


def test_expand_calls_ignores_imports_edges(sample_graph):
    """IMPORTS edges are not followed — only CALLS edges count.

    Add an IMPORTS edge from b to e and verify e does NOT appear in neighbors.
    """
    sample_graph.add_edge("b.py::func_b", "e.py::func_e", type="IMPORTS")
    scores = {"b.py::func_b": 0.020}
    result = expand_calls_neighbors(["b.py::func_b"], scores, sample_graph)
    assert "e.py::func_e" not in result
    # Clean up so other tests are not affected
    sample_graph.remove_edge("b.py::func_b", "e.py::func_e")


def test_expand_calls_callers_cap_enforced(sample_graph):
    """callers_cap limits the number of callers returned per seed."""
    # b has 2 callers (a, d); cap=1 should return exactly 1
    scores = {"b.py::func_b": 0.020}
    result = expand_calls_neighbors(["b.py::func_b"], scores, sample_graph, callers_cap=1)
    callers_in_result = {"a.py::func_a", "d.py::func_d"} & set(result.keys())
    assert len(callers_in_result) == 1


def test_expand_calls_callees_cap_enforced():
    """callees_cap limits the number of callees returned per seed."""
    import networkx as nx
    G = nx.DiGraph()
    for i in range(10):
        nid = f"callee_{i}::f"
        G.add_node(nid, node_id=nid, name=f"f{i}", type="function",
                   file_path=f"/{i}.py", line_start=1, line_end=1,
                   signature="", docstring=None, body_preview="",
                   complexity=0, embedding_text="", pagerank=float(i), in_degree=0)
        G.add_edge("seed::f", nid, type="CALLS")
    G.add_node("seed::f", node_id="seed::f", name="f", type="function",
               file_path="/seed.py", line_start=1, line_end=1,
               signature="", docstring=None, body_preview="",
               complexity=0, embedding_text="", pagerank=0.5, in_degree=0)

    scores = {"seed::f": 0.020}
    result = expand_calls_neighbors(["seed::f"], scores, G, callees_cap=3)
    # Only 3 callees should be returned (top-3 by pagerank)
    assert len(result) == 3


# ---------------------------------------------------------------------------
# semantic_search tests
# ---------------------------------------------------------------------------


def _make_mock_sqlite_conn(rows):
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = rows
    mock_conn.__enter__ = lambda s: mock_conn
    mock_conn.__exit__ = MagicMock(return_value=False)
    return mock_conn


def test_semantic_search_returns_pairs(sample_graph, mock_embedder, monkeypatch):
    """semantic_search returns list of (str, float) tuples."""
    raw_rows = [("b.py::func_b", 0.05), ("a.py::func_a", 0.20)]
    mock_conn = _make_mock_sqlite_conn(raw_rows)
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite3.connect", MagicMock(return_value=mock_conn))
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite_vec.load", MagicMock())
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite_vec.serialize_float32", MagicMock(return_value=b"\x00"))

    result = semantic_search("find func_b", "/repo", top_k=2, db_path=":memory:")

    assert isinstance(result, list)
    assert len(result) == 2
    for item in result:
        assert isinstance(item, tuple) and len(item) == 2
        assert isinstance(item[0], str) and isinstance(item[1], float)


# ---------------------------------------------------------------------------
# fts_search tests
# ---------------------------------------------------------------------------


def _make_fts_conn(rows):
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = rows
    return mock_conn


def test_fts_search_returns_pairs(monkeypatch):
    """fts_search returns list of (str, float) tuples in [0, 0.85]."""
    rows = [("b.py::func_b", -2.5), ("a.py::func_a", -1.0)]
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite3.connect", MagicMock(return_value=_make_fts_conn(rows)))

    result = fts_search("find func_b", "/repo", top_k=5, db_path=":memory:")

    assert isinstance(result, list)
    assert len(result) == 2
    for node_id, score in result:
        assert isinstance(node_id, str) and isinstance(score, float)
        assert 0.0 <= score <= 0.85


def test_fts_search_best_result_scores_highest(monkeypatch):
    """The row with the most-negative BM25 rank must get score 0.85."""
    rows = [("b.py::func_b", -5.0), ("a.py::func_a", -2.5)]
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite3.connect", MagicMock(return_value=_make_fts_conn(rows)))

    result = fts_search("func_b query", "/repo", top_k=5, db_path=":memory:")
    scores_by_id = {node_id: score for node_id, score in result}

    assert scores_by_id["b.py::func_b"] == pytest.approx(0.85)
    assert scores_by_id["a.py::func_a"] < scores_by_id["b.py::func_b"]


def test_fts_search_empty_on_operational_error(monkeypatch):
    """FTS5 OperationalError must return [] not raise."""
    mock_conn = MagicMock()
    mock_conn.execute.side_effect = sqlite3.OperationalError("fts syntax error")
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite3.connect", MagicMock(return_value=mock_conn))

    result = fts_search("!@# bad tokens", "/repo", top_k=5, db_path=":memory:")
    assert result == []


def test_fts_search_empty_on_short_words(monkeypatch):
    """Queries with only ≤2-char tokens return [] without a DB call."""
    result = fts_search("is an or", "/repo", top_k=5, db_path=":memory:")
    assert result == []


def test_fts_search_empty_when_no_rows(monkeypatch):
    """fts_search on a no-match query returns []."""
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite3.connect",
                        MagicMock(return_value=_make_fts_conn([])))
    result = fts_search("xyzzy_nonexistent_token", "/repo", top_k=5, db_path=":memory:")
    assert result == []


# ---------------------------------------------------------------------------
# graph_rag_retrieve integration tests
# ---------------------------------------------------------------------------


def test_graph_rag_retrieve_stats(sample_graph, mock_embedder, monkeypatch):
    """graph_rag_retrieve returns (nodes, stats) with all v2 stats keys."""
    raw_rows = [("b.py::func_b", 0.1)]
    mock_conn = _make_mock_sqlite_conn(raw_rows)
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite3.connect", MagicMock(return_value=mock_conn))
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite_vec.load", MagicMock())
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite_vec.serialize_float32", MagicMock(return_value=b"\x00"))

    nodes, stats = graph_rag_retrieve(
        "find func_b", "/repo", sample_graph, db_path=":memory:", max_nodes=3, hop_depth=1,
        use_cross_encoder=False,
    )

    for key in ("seed_count", "semantic_seeds", "fts_seeds", "fts_new",
                "neighbor_count", "candidate_pool", "returned_count",
                "cross_encoder_used"):
        assert key in stats, f"missing stats key: {key}"
    assert len(nodes) <= 3


def test_graph_rag_retrieve_includes_calls_neighbors(sample_graph, mock_embedder, monkeypatch):
    """Nodes reachable via CALLS edges from a seed appear in the candidate pool.

    seed = a.py::func_a — its CALLS callee is b.py::func_b.
    b should appear in returned nodes even when max_nodes is large enough.
    """
    raw_rows = [("a.py::func_a", 0.05)]
    mock_conn = _make_mock_sqlite_conn(raw_rows)
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite3.connect", MagicMock(return_value=mock_conn))
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite_vec.load", MagicMock())
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite_vec.serialize_float32", MagicMock(return_value=b"\x00"))

    nodes, stats = graph_rag_retrieve(
        "func_a", "/repo", sample_graph, db_path=":memory:", max_nodes=10, use_cross_encoder=False,
    )

    node_ids = {n.node_id for n in nodes}
    assert "a.py::func_a" in node_ids   # seed must be present
    assert stats["neighbor_count"] > 0  # expansion added neighbors


def test_graph_rag_retrieve_fts_node_included(sample_graph, mock_embedder, monkeypatch):
    """A node found by FTS but NOT by semantic search is included via RRF merge."""
    sem_conn = _make_mock_sqlite_conn([("b.py::func_b", 0.1)])
    fts_conn = _make_fts_conn([("c.py::func_c", -3.0)])

    call_count = {"n": 0}

    def connect_side_effect(db_path):
        call_count["n"] += 1
        return sem_conn if call_count["n"] == 1 else fts_conn

    monkeypatch.setattr("app.retrieval.graph_rag.sqlite3.connect", connect_side_effect)
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite_vec.load", MagicMock())
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite_vec.serialize_float32", MagicMock(return_value=b"\x00"))

    _nodes, stats = graph_rag_retrieve(
        "find func_b or func_c", "/repo", sample_graph, db_path=":memory:", max_nodes=5,
        use_cross_encoder=False,
    )

    assert stats["fts_seeds"] >= 1
    assert stats["seed_count"] >= stats["semantic_seeds"]
    assert stats["fts_new"] >= 1


# -- cross-encoder integration tests -----------------------------------------


def test_graph_rag_retrieve_cross_encoder_called_when_enabled(
    sample_graph, mock_embedder, monkeypatch
):
    """cross_encode_rerank is called when use_cross_encoder=True."""
    raw_rows = [("b.py::func_b", 0.1)]
    mock_conn = _make_mock_sqlite_conn(raw_rows)
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite3.connect", MagicMock(return_value=mock_conn))
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite_vec.load", MagicMock())
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite_vec.serialize_float32", MagicMock(return_value=b"\x00"))

    ce_mock = MagicMock(return_value=[])
    monkeypatch.setattr("app.retrieval.graph_rag.cross_encode_rerank", ce_mock)

    _nodes, stats = graph_rag_retrieve(
        "find func_b", "/repo", sample_graph, ":memory:", max_nodes=3, use_cross_encoder=True,
    )

    ce_mock.assert_called_once()
    assert ce_mock.call_args[0][0] == "find func_b"
    assert stats["cross_encoder_used"] is True


def test_graph_rag_retrieve_cross_encoder_skipped_when_disabled(
    sample_graph, mock_embedder, monkeypatch
):
    """cross_encode_rerank is NOT called when use_cross_encoder=False."""
    raw_rows = [("b.py::func_b", 0.1)]
    mock_conn = _make_mock_sqlite_conn(raw_rows)
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite3.connect", MagicMock(return_value=mock_conn))
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite_vec.load", MagicMock())
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite_vec.serialize_float32", MagicMock(return_value=b"\x00"))

    ce_mock = MagicMock()
    monkeypatch.setattr("app.retrieval.graph_rag.cross_encode_rerank", ce_mock)

    _nodes, stats = graph_rag_retrieve(
        "find func_b", "/repo", sample_graph, ":memory:", max_nodes=3, use_cross_encoder=False,
    )

    ce_mock.assert_not_called()
    assert stats["cross_encoder_used"] is False


def test_graph_rag_retrieve_cross_encoder_failure_falls_back(
    sample_graph, mock_embedder, monkeypatch
):
    """If cross_encode_rerank raises, pipeline completes via score-sorted fallback."""
    raw_rows = [("b.py::func_b", 0.1)]
    mock_conn = _make_mock_sqlite_conn(raw_rows)
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite3.connect", MagicMock(return_value=mock_conn))
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite_vec.load", MagicMock())
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite_vec.serialize_float32", MagicMock(return_value=b"\x00"))
    monkeypatch.setattr(
        "app.retrieval.graph_rag.cross_encode_rerank",
        MagicMock(side_effect=RuntimeError("model unavailable")),
    )

    nodes, stats = graph_rag_retrieve(
        "find func_b", "/repo", sample_graph, ":memory:", max_nodes=3, use_cross_encoder=True,
    )

    assert stats["cross_encoder_used"] is False
    assert isinstance(nodes, list)


def test_graph_rag_retrieve_cross_encoder_used_key_always_present(
    sample_graph, mock_embedder, monkeypatch
):
    """stats always contains 'cross_encoder_used' for both True and False flag values."""
    raw_rows = [("b.py::func_b", 0.1)]
    mock_conn = _make_mock_sqlite_conn(raw_rows)
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite3.connect", MagicMock(return_value=mock_conn))
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite_vec.load", MagicMock())
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite_vec.serialize_float32", MagicMock(return_value=b"\x00"))
    monkeypatch.setattr("app.retrieval.graph_rag.cross_encode_rerank", MagicMock(return_value=[]))

    for flag in (True, False):
        _, stats = graph_rag_retrieve(
            "q", "/repo", sample_graph, ":memory:", max_nodes=3, use_cross_encoder=flag,
        )
        assert "cross_encoder_used" in stats, f"missing key with use_cross_encoder={flag}"


# ---------------------------------------------------------------------------
# v3 improvement ①: cosine floor
# ---------------------------------------------------------------------------

def test_semantic_search_cosine_floor(mock_embedder, monkeypatch):
    """semantic_search drops nodes whose similarity score < min_similarity.

    distance=0.80 → similarity=0.20  (above default 0.15, kept)
    distance=0.90 → similarity=0.10  (below threshold, dropped)
    """
    raw_rows = [("a.py::func_a", 0.80), ("b.py::func_b", 0.90)]
    mock_conn = _make_mock_sqlite_conn(raw_rows)
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite3.connect", MagicMock(return_value=mock_conn))
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite_vec.load", MagicMock())
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite_vec.serialize_float32", MagicMock(return_value=b"\x00"))

    result = semantic_search("find func", "/repo", top_k=2, db_path=":memory:")

    node_ids = [node_id for node_id, _ in result]
    assert "a.py::func_a" in node_ids      # similarity=0.20, above threshold
    assert "b.py::func_b" not in node_ids  # similarity=0.10, below threshold


def test_semantic_search_cosine_floor_custom_threshold(mock_embedder, monkeypatch):
    """Custom min_similarity threshold is respected."""
    # distance=0.70 → similarity=0.30
    raw_rows = [("a.py::func_a", 0.70)]
    mock_conn = _make_mock_sqlite_conn(raw_rows)
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite3.connect", MagicMock(return_value=mock_conn))
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite_vec.load", MagicMock())
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite_vec.serialize_float32", MagicMock(return_value=b"\x00"))

    # With threshold=0.40, similarity=0.30 is below it and should be dropped
    result = semantic_search("find func", "/repo", top_k=1, db_path=":memory:", min_similarity=0.40)
    assert result == []

    # With threshold=0.20, similarity=0.30 is above it and should be kept
    result2 = semantic_search("find func", "/repo", top_k=1, db_path=":memory:", min_similarity=0.20)
    assert len(result2) == 1
    assert result2[0][0] == "a.py::func_a"


# ---------------------------------------------------------------------------
# v3 improvement ②: CE score floor before MMR
# ---------------------------------------------------------------------------

def _make_ce_mock(scores_by_id: dict):
    """Returns a cross_encode_rerank mock that assigns fixed CE scores."""
    def _ce(query, scored, top_n):
        result = []
        for score, node in scored:
            ce_score = scores_by_id.get(node.node_id, score)
            result.append((ce_score, node))
        result.sort(key=lambda x: x[0], reverse=True)
        return result
    return _ce


def test_ce_floor_drops_negative_scores(sample_graph, mock_embedder, monkeypatch):
    """CE ≤ 0.0 nodes are removed before MMR; stats['ce_floor_dropped'] counts them."""
    raw_rows = [("b.py::func_b", 0.1), ("c.py::func_c", 0.2), ("a.py::func_a", 0.3)]
    mock_conn = _make_mock_sqlite_conn(raw_rows)
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite3.connect", MagicMock(return_value=mock_conn))
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite_vec.load", MagicMock())
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite_vec.serialize_float32", MagicMock(return_value=b"\x00"))

    # b=0.8 (kept), c=-0.5 (dropped), a=0.3 (kept)
    monkeypatch.setattr(
        "app.retrieval.graph_rag.cross_encode_rerank",
        _make_ce_mock({"b.py::func_b": 0.8, "c.py::func_c": -0.5, "a.py::func_a": 0.3}),
    )

    nodes, stats = graph_rag_retrieve(
        "find funcs", "/repo", sample_graph, db_path=":memory:", max_nodes=5,
        use_cross_encoder=True,
    )

    assert stats["ce_floor_dropped"] == 1
    node_ids = {n.node_id for n in nodes}
    assert "c.py::func_c" not in node_ids


def test_ce_floor_zero_score_dropped(sample_graph, mock_embedder, monkeypatch):
    """Nodes with CE score exactly 0.0 are also dropped (boundary: strictly > 0 required)."""
    raw_rows = [("b.py::func_b", 0.1)]
    mock_conn = _make_mock_sqlite_conn(raw_rows)
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite3.connect", MagicMock(return_value=mock_conn))
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite_vec.load", MagicMock())
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite_vec.serialize_float32", MagicMock(return_value=b"\x00"))

    monkeypatch.setattr(
        "app.retrieval.graph_rag.cross_encode_rerank",
        _make_ce_mock({"b.py::func_b": 0.0}),
    )

    nodes, stats = graph_rag_retrieve(
        "find func_b", "/repo", sample_graph, db_path=":memory:", max_nodes=5,
        use_cross_encoder=True,
    )

    assert stats["ce_floor_dropped"] == 1
    assert not any(n.node_id == "b.py::func_b" for n in nodes)


def test_ce_floor_key_present_when_ce_disabled(sample_graph, mock_embedder, monkeypatch):
    """stats['ce_floor_dropped'] is always present, equals 0 when CE is off."""
    raw_rows = [("b.py::func_b", 0.1)]
    mock_conn = _make_mock_sqlite_conn(raw_rows)
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite3.connect", MagicMock(return_value=mock_conn))
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite_vec.load", MagicMock())
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite_vec.serialize_float32", MagicMock(return_value=b"\x00"))

    _, stats = graph_rag_retrieve(
        "find func_b", "/repo", sample_graph, db_path=":memory:", max_nodes=5,
        use_cross_encoder=False,
    )

    assert "ce_floor_dropped" in stats
    assert stats["ce_floor_dropped"] == 0
