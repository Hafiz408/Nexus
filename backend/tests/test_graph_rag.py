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
    _expand_full_bodies,
    expand_calls_neighbors,
    fts_search,
    graph_rag_retrieve,
    ppr_expand,
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


def test_ce_hybrid_floor_keeps_top3_always(sample_graph, mock_embedder, monkeypatch):
    """Hybrid CE floor always keeps top-3 even when all scores are negative.

    Old hard floor (> 0.0) would drop everything; hybrid floor preserves top-3.
    With 3 candidates all negative and all within 4.0 of the best, none are dropped.
    """
    raw_rows = [("b.py::func_b", 0.1), ("c.py::func_c", 0.2), ("a.py::func_a", 0.3)]
    mock_conn = _make_mock_sqlite_conn(raw_rows)
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite3.connect", MagicMock(return_value=mock_conn))
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite_vec.load", MagicMock())
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite_vec.serialize_float32", MagicMock(return_value=b"\x00"))

    # All three candidates score negative — hybrid floor keeps top-3 unconditionally
    monkeypatch.setattr(
        "app.retrieval.graph_rag.cross_encode_rerank",
        _make_ce_mock({"b.py::func_b": -1.0, "c.py::func_c": -2.0, "a.py::func_a": -3.0}),
    )

    nodes, stats = graph_rag_retrieve(
        "find funcs", "/repo", sample_graph, db_path=":memory:", max_nodes=5,
        use_cross_encoder=True,
    )

    assert stats["ce_floor_dropped"] == 0
    assert len(nodes) > 0  # top-3 preserved — no zero-context response


def test_ce_hybrid_floor_drops_outside_range(sample_graph, mock_embedder, monkeypatch):
    """Hybrid floor drops nodes more than 4.0 logit-units below the best score.

    Best=2.0, floor=-2.0. A node at -3.0 (beyond rank-3) is dropped.
    """
    import networkx as nx

    # Build a graph with enough nodes to go beyond top-3
    G = nx.DiGraph()
    ids = [f"f{i}.py::func" for i in range(6)]
    for nid in ids:
        G.add_node(nid, node_id=nid, name="func", type="function",
                   file_path=f"/{nid}.py", line_start=1, line_end=2,
                   signature="def func():", docstring=None, body_preview="pass",
                   complexity=1, embedding_text="def func():", pagerank=0.1,
                   in_degree=0, out_degree=0, full_body="")
    raw_rows = [(nid, 0.1) for nid in ids]
    mock_conn = _make_mock_sqlite_conn(raw_rows)
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite3.connect", MagicMock(return_value=mock_conn))
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite_vec.load", MagicMock())
    monkeypatch.setattr("app.retrieval.graph_rag.sqlite_vec.serialize_float32", MagicMock(return_value=b"\x00"))

    # 5 nodes score positively, 1 node (f5) is 4.1 below the best → dropped
    scores = {ids[0]: 2.0, ids[1]: 1.5, ids[2]: 1.0, ids[3]: 0.5, ids[4]: 0.1, ids[5]: -2.1}
    monkeypatch.setattr("app.retrieval.graph_rag.cross_encode_rerank", _make_ce_mock(scores))

    nodes, stats = graph_rag_retrieve(
        "find funcs", "/repo", G, db_path=":memory:", max_nodes=10, use_cross_encoder=True,
    )

    assert stats["ce_floor_dropped"] == 1
    assert not any(n.node_id == ids[5] for n in nodes)


def test_ce_floor_zero_score_kept_as_top3(sample_graph, mock_embedder, monkeypatch):
    """A single node scoring 0.0 is kept — it's within top-3 by definition.

    Hybrid floor only drops nodes beyond position 3 that exceed the 4.0 range.
    """
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

    # Single node is top-1, so it's in the always-kept top-3 → not dropped
    assert stats["ce_floor_dropped"] == 0
    assert any(n.node_id == "b.py::func_b" for n in nodes)


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


# ---------------------------------------------------------------------------
# v3 improvement ③: full body expansion
# ---------------------------------------------------------------------------

def test_expand_full_bodies_reads_source(tmp_path):
    """_expand_full_bodies reads line_start→line_end from the source file."""
    src = tmp_path / "funcs.py"
    src.write_text(
        "def foo():\n"          # line 1
        "    x = 1\n"           # line 2
        "    return x\n"        # line 3
        "\n"                    # line 4
        "def bar():\n"          # line 5
        "    pass\n"            # line 6
    )

    node = CodeNode(
        node_id="funcs.py::foo", name="foo", type="function",
        file_path=str(src), line_start=1, line_end=3,
        signature="def foo():", body_preview="x = 1",
    )
    scored = [(0.9, node)]
    count = _expand_full_bodies(scored, top_n=1)

    assert count == 1
    assert "def foo():" in node.full_body
    assert "return x" in node.full_body
    # bar() lines must NOT be present
    assert "def bar():" not in node.full_body


def test_expand_full_bodies_fallback_on_missing_file():
    """_expand_full_bodies falls back silently when file_path is unreadable."""
    node = CodeNode(
        node_id="missing.py::baz", name="baz", type="function",
        file_path="/nonexistent/path/missing.py", line_start=1, line_end=2,
        signature="def baz():", body_preview="pass",
    )
    scored = [(0.5, node)]
    count = _expand_full_bodies(scored, top_n=1)

    assert count == 0        # nothing expanded
    assert node.full_body == ""  # unchanged — still fallback value


def test_expand_full_bodies_only_expands_top_n(tmp_path):
    """_expand_full_bodies only expands the first top_n nodes in scored."""
    src = tmp_path / "f.py"
    src.write_text("def a():\n    pass\n\ndef b():\n    pass\n")

    node_a = CodeNode(
        node_id="f.py::a", name="a", type="function",
        file_path=str(src), line_start=1, line_end=2,
        signature="def a():", body_preview="pass",
    )
    node_b = CodeNode(
        node_id="f.py::b", name="b", type="function",
        file_path=str(src), line_start=4, line_end=5,
        signature="def b():", body_preview="pass",
    )
    scored = [(0.9, node_a), (0.5, node_b)]
    count = _expand_full_bodies(scored, top_n=1)

    assert count == 1
    assert node_a.full_body != ""   # first node expanded
    assert node_b.full_body == ""   # second node NOT expanded (beyond top_n=1)


def test_expand_full_bodies_returns_zero_when_empty():
    """_expand_full_bodies with empty scored list returns 0."""
    count = _expand_full_bodies([], top_n=5)
    assert count == 0


# ---------------------------------------------------------------------------
# v3.1: ppr_expand tests
# Graph topology for PPR tests:
#   cls.py::MyClass -> cls.py::method_a  (CLASS_CONTAINS)
#   cls.py::MyClass -> cls.py::method_b  (CLASS_CONTAINS)
#   cls.py::method_a -> util.py::helper  (CALLS)
#   other.py::other -> util.py::helper   (IMPORTS — must NOT be traversed)
# ---------------------------------------------------------------------------

@pytest.fixture
def ppr_graph():
    """Graph with CALLS, CLASS_CONTAINS, and IMPORTS edges for PPR traversal tests."""
    import networkx as nx

    def _node(nid, name):
        return dict(node_id=nid, name=name, type="function", file_path=f"/{nid}.py",
                    line_start=1, line_end=5, signature=f"def {name}():", docstring=None,
                    body_preview="pass", complexity=1, embedding_text=name,
                    pagerank=0.1, in_degree=0, out_degree=0, full_body="")

    G = nx.DiGraph()
    for nid, nm in [
        ("cls.py::MyClass", "MyClass"),
        ("cls.py::method_a", "method_a"),
        ("cls.py::method_b", "method_b"),
        ("util.py::helper", "helper"),
        ("other.py::other", "other"),
    ]:
        G.add_node(nid, **_node(nid, nm))

    G.add_edge("cls.py::MyClass", "cls.py::method_a", type="CLASS_CONTAINS")
    G.add_edge("cls.py::MyClass", "cls.py::method_b", type="CLASS_CONTAINS")
    G.add_edge("cls.py::method_a", "util.py::helper", type="CALLS")
    G.add_edge("other.py::other", "util.py::helper", type="IMPORTS")
    return G


def test_ppr_expand_returns_neighbors(ppr_graph):
    """PPR seeded from MyClass discovers its CLASS_CONTAINS children."""
    result = ppr_expand({"cls.py::MyClass": 0.5}, ppr_graph)
    assert "cls.py::method_a" in result
    assert "cls.py::method_b" in result


def test_ppr_expand_seeds_not_in_result(ppr_graph):
    """Seed nodes are never included in the returned neighbor dict."""
    seeds = {"cls.py::MyClass": 0.5}
    result = ppr_expand(seeds, ppr_graph)
    for seed in seeds:
        assert seed not in result


def test_ppr_expand_traverses_calls_edges(ppr_graph):
    """CALLS edges are followed — multi-hop neighbor surfaced."""
    # Seed = method_a; via CALLS it reaches helper
    result = ppr_expand({"cls.py::method_a": 0.5}, ppr_graph)
    assert "util.py::helper" in result


def test_ppr_expand_ignores_imports_edges(ppr_graph):
    """IMPORTS edges are not traversed by PPR."""
    # Seed = other.py::other; its IMPORTS edge to helper must not be followed
    result = ppr_expand({"other.py::other": 0.5}, ppr_graph)
    assert "util.py::helper" not in result


def test_ppr_expand_empty_seeds_returns_empty(ppr_graph):
    """Empty seed dict returns empty dict without error."""
    assert ppr_expand({}, ppr_graph) == {}


def test_ppr_expand_isolated_seed_returns_empty(ppr_graph):
    """Seed with no traversable edges returns empty (no neighbors reachable)."""
    result = ppr_expand({"other.py::other": 0.5}, ppr_graph)
    # other only has an IMPORTS edge which is excluded — no reachable neighbors
    assert result == {}


def test_ppr_expand_respects_top_n(ppr_graph):
    """top_n cap limits the number of returned neighbors."""
    result = ppr_expand({"cls.py::MyClass": 1.0}, ppr_graph, top_n=1)
    assert len(result) <= 1


def test_ppr_expand_scores_are_positive(ppr_graph):
    """All returned PPR scores are > 0."""
    result = ppr_expand({"cls.py::MyClass": 1.0}, ppr_graph)
    assert all(v > 0 for v in result.values())
