"""Tests for the Debugger Agent (Phase 18, TST-02).

Verifies traversal correctness, anomaly scoring range, suspect ranking,
impact radius, diagnosis content, and edge-case handling — all offline
(no live API calls, no database, no network).

Fixtures:
  - debug_graph: 6-node DiGraph with deterministic topology and attributes
  - mock_llm_factory: patches app.core.model_factory.get_llm at source module

Patch target: 'app.core.model_factory.get_llm'
  Reason: debugger.py uses a lazy import inside debug() body — get_llm is NOT
  a module-level attribute of app.agent.debugger. Patching the source module
  intercepts it before the local import resolves.

Chain invocation pattern in debug():
  chain = prompt | llm          (uses __or__ pipe operator)
  response = chain.invoke(...)  (LCEL invoke, not __call__)
  So mock: llm.__or__ returns a mock chain; chain.invoke returns a mock response.
"""

import pytest
import networkx as nx
from unittest.mock import MagicMock, patch

from app.agent.debugger import DebugResult, SuspectNode, debug


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def debug_graph() -> nx.DiGraph:
    """6-node DiGraph with deterministic topology for debugger testing.

    Topology (all CALLS edges):
      src.py::entry -> src.py::hop1a -> lib.py::hop2a
      src.py::entry -> src.py::hop1b -> lib.py::hop2b -> lib.py::hop3

    Node attributes set to produce predictable anomaly scores:
      - hop2a: complexity=8, no error handling ("unsafe_op()") -> highest scorer
      - hop3:  complexity=6, body="raise ValueError" -> has error handling keyword
      - hop1a: complexity=5, no error handling ("risky_call()")
      - hop1b: complexity=1, has error handling ("try: ...")
      - hop2b: complexity=3, body="pass" (neutral)
      - entry: complexity=2, body="hop1a(); hop1b()" (caller)

    Graph contains 6 nodes and 5 CALLS edges.
    """
    G = nx.DiGraph()

    nodes = [
        {
            "node_id": "src.py::entry",
            "name": "entry",
            "type": "function",
            "file_path": "src.py",
            "line_start": 1,
            "line_end": 10,
            "signature": "def entry():",
            "docstring": "Entry point.",
            "body_preview": "hop1a(); hop1b()",
            "complexity": 2,
            "out_degree": 2,
            "pagerank": 0.10,
        },
        {
            "node_id": "src.py::hop1a",
            "name": "hop1a",
            "type": "function",
            "file_path": "src.py",
            "line_start": 12,
            "line_end": 20,
            "signature": "def hop1a():",
            "docstring": "",
            "body_preview": "risky_call()",
            "complexity": 5,
            "out_degree": 1,
            "pagerank": 0.15,
        },
        {
            "node_id": "src.py::hop1b",
            "name": "hop1b",
            "type": "function",
            "file_path": "src.py",
            "line_start": 22,
            "line_end": 30,
            "signature": "def hop1b():",
            "docstring": "",
            "body_preview": "try: safe_call() except Exception: pass",
            "complexity": 1,
            "out_degree": 1,
            "pagerank": 0.20,
        },
        {
            "node_id": "lib.py::hop2a",
            "name": "hop2a",
            "type": "function",
            "file_path": "lib.py",
            "line_start": 5,
            "line_end": 15,
            "signature": "def hop2a():",
            "docstring": "",
            "body_preview": "unsafe_op()",
            "complexity": 8,
            "out_degree": 0,
            "pagerank": 0.08,
        },
        {
            "node_id": "lib.py::hop2b",
            "name": "hop2b",
            "type": "function",
            "file_path": "lib.py",
            "line_start": 17,
            "line_end": 22,
            "signature": "def hop2b():",
            "docstring": "",
            "body_preview": "pass",
            "complexity": 3,
            "out_degree": 1,
            "pagerank": 0.12,
        },
        {
            "node_id": "lib.py::hop3",
            "name": "hop3",
            "type": "function",
            "file_path": "lib.py",
            "line_start": 24,
            "line_end": 30,
            "signature": "def hop3():",
            "docstring": "",
            "body_preview": "raise ValueError('unexpected state')",
            "complexity": 6,
            "out_degree": 0,
            "pagerank": 0.09,
        },
    ]

    for n in nodes:
        node_id = n["node_id"]
        G.add_node(node_id, **n)

    # All edges are CALLS type
    G.add_edge("src.py::entry", "src.py::hop1a", type="CALLS")
    G.add_edge("src.py::entry", "src.py::hop1b", type="CALLS")
    G.add_edge("src.py::hop1a", "lib.py::hop2a", type="CALLS")
    G.add_edge("src.py::hop1b", "lib.py::hop2b", type="CALLS")
    G.add_edge("lib.py::hop2b", "lib.py::hop3", type="CALLS")

    return G


@pytest.fixture
def mock_settings():
    """Minimal settings stub with debugger_max_hops=4.

    Passed directly to debug() to bypass get_settings(), which requires
    postgres env vars not present in the test environment.
    debug() accepts an optional settings parameter for exactly this purpose.
    """
    settings = MagicMock()
    settings.debugger_max_hops = 4
    return settings


@pytest.fixture
def mock_llm_factory():
    """Patch get_llm at source module — lazy import requires source-level patch.

    The debug() function does: chain = prompt | llm; response = chain.invoke(...)
    So we mock: llm.__or__ returns a mock chain; chain.invoke returns a mock response.

    Patch target: 'app.core.model_factory.get_llm'
    Why not 'app.agent.debugger.get_llm'?
    debugger.py imports get_llm inside debug() body (lazy import), so it is NOT
    a module-level attribute of app.agent.debugger. Source-level patching intercepts
    the import before the local scope resolves it.
    """
    with patch("app.core.model_factory.get_llm") as mock_factory:
        mock_response = MagicMock()
        mock_response.content = (
            "The bug likely originates in hop2a due to missing error handling "
            "and high complexity."
        )

        mock_chain = MagicMock()
        mock_chain.invoke.return_value = mock_response

        mock_llm = MagicMock()
        mock_llm.__or__ = MagicMock(return_value=mock_chain)

        mock_factory.return_value = mock_llm
        yield mock_factory


# ---------------------------------------------------------------------------
# Test 1 — Traversal visits correct hop nodes (DBUG-01)
# ---------------------------------------------------------------------------

def test_traversal_visits_hop_nodes(mock_llm_factory, mock_settings, debug_graph):
    """BFS from entry must include hop1a and hop1b in traversal_path."""
    result = debug("bug in entry function", debug_graph, settings=mock_settings)
    assert "src.py::hop1a" in result.traversal_path
    assert "src.py::hop1b" in result.traversal_path


# ---------------------------------------------------------------------------
# Test 2 — Entry node appears in traversal path (DBUG-01)
# ---------------------------------------------------------------------------

def test_traversal_includes_entry_node(mock_llm_factory, mock_settings, debug_graph):
    """Entry node is the BFS start and must appear in traversal_path."""
    result = debug("bug in entry function", debug_graph, settings=mock_settings)
    assert "src.py::entry" in result.traversal_path


# ---------------------------------------------------------------------------
# Test 3 — Traversal depth reaches hop3 within max_hops=4 (DBUG-01)
# ---------------------------------------------------------------------------

def test_traversal_depth_respects_max_hops(mock_llm_factory, mock_settings, debug_graph):
    """hop3 is at depth 3 from entry; with default max_hops=4 it must be reached.

    debug_graph has 6 reachable nodes from entry: entry, hop1a, hop1b, hop2a,
    hop2b, hop3 — all within 3 hops of entry. The traversal path may include
    all 6 nodes (no phantom nodes beyond the graph).
    """
    result = debug("bug in entry", debug_graph, settings=mock_settings)
    # hop3 reachable: entry(0) -> hop1b(1) -> hop2b(2) -> hop3(3) — within max_hops=4
    assert "lib.py::hop3" in result.traversal_path
    # All 6 nodes are reachable within max_hops=4; no phantom nodes beyond that
    assert len(result.traversal_path) <= 6


# ---------------------------------------------------------------------------
# Test 4 — Anomaly scores in [0.0, 1.0] range (DBUG-02)
# ---------------------------------------------------------------------------

def test_anomaly_score_range(mock_llm_factory, mock_settings, debug_graph):
    """Every suspect's anomaly_score must be within [0.0, 1.0]."""
    result = debug("risky_call failing", debug_graph, settings=mock_settings)
    assert len(result.suspects) > 0
    for suspect in result.suspects:
        assert 0.0 <= suspect.anomaly_score <= 1.0, (
            f"{suspect.node_id} score {suspect.anomaly_score} out of range"
        )


# ---------------------------------------------------------------------------
# Test 5 — Suspects sorted by score descending (DBUG-02 / DBUG-04)
# ---------------------------------------------------------------------------

def test_suspects_sorted_descending(mock_llm_factory, mock_settings, debug_graph):
    """Suspects list must be sorted by anomaly_score in descending order."""
    result = debug("unsafe operation in hop2a", debug_graph, settings=mock_settings)
    scores = [s.anomaly_score for s in result.suspects]
    assert scores == sorted(scores, reverse=True), (
        "Suspects must be sorted by score descending"
    )


# ---------------------------------------------------------------------------
# Test 6 — At most 5 suspects returned (DBUG-04)
# ---------------------------------------------------------------------------

def test_max_five_suspects(mock_llm_factory, mock_settings, debug_graph):
    """debug() must return at most 5 suspects regardless of traversal size."""
    result = debug("some bug", debug_graph, settings=mock_settings)
    assert len(result.suspects) <= 5


# ---------------------------------------------------------------------------
# Test 7 — SuspectNode has required schema fields (DBUG-04)
# ---------------------------------------------------------------------------

def test_suspect_node_schema(mock_llm_factory, mock_settings, debug_graph):
    """Each SuspectNode must have non-empty node_id, str file_path, int line_start,
    float anomaly_score, and non-empty reasoning."""
    result = debug("error in hop2a", debug_graph, settings=mock_settings)
    for suspect in result.suspects:
        assert isinstance(suspect.node_id, str) and suspect.node_id
        assert isinstance(suspect.file_path, str)
        assert isinstance(suspect.line_start, int)
        assert isinstance(suspect.anomaly_score, float)
        assert isinstance(suspect.reasoning, str) and suspect.reasoning


# ---------------------------------------------------------------------------
# Test 8 — Impact radius is set of CALLS-edge predecessors of top suspect (DBUG-03)
# ---------------------------------------------------------------------------

def test_impact_radius_correct(mock_llm_factory, mock_settings, debug_graph):
    """impact_radius must equal the direct CALLS-edge callers of the top suspect."""
    result = debug("error in hop2a", debug_graph, settings=mock_settings)
    if not result.suspects:
        pytest.skip("no suspects — graph topology may not score any node")
    top_suspect_id = result.suspects[0].node_id
    # Compute expected callers from the fixture graph directly
    expected_callers = {
        pred
        for pred in debug_graph.predecessors(top_suspect_id)
        if debug_graph.edges[pred, top_suspect_id].get("type") == "CALLS"
    }
    assert set(result.impact_radius) == expected_callers


# ---------------------------------------------------------------------------
# Test 9 — Diagnosis is a non-empty string (DBUG-05)
# ---------------------------------------------------------------------------

def test_diagnosis_is_non_empty_string(mock_llm_factory, mock_settings, debug_graph):
    """diagnosis must be a non-empty string sourced from the LLM response."""
    result = debug("bug in entry", debug_graph, settings=mock_settings)
    assert isinstance(result.diagnosis, str)
    assert len(result.diagnosis) > 0


# ---------------------------------------------------------------------------
# Test 10 — Fallback when no entry node matched (DBUG-01 edge case)
# ---------------------------------------------------------------------------

def test_fallback_when_no_entry_matched(mock_llm_factory, mock_settings, debug_graph):
    """When bug description matches no node name, debug() must not raise and
    must return a DebugResult with a non-empty traversal_path (fallback to
    highest in_degree node)."""
    # "xyz_nonexistent" matches no node name in debug_graph
    result = debug("error in xyz_nonexistent function", debug_graph, settings=mock_settings)
    assert isinstance(result, DebugResult)
    # traversal_path is non-empty — fallback entry node selected
    assert len(result.traversal_path) >= 1
