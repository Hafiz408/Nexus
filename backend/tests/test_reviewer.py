"""Tests for the Reviewer Agent (Phase 19, TST-03).

Verifies context assembly (1-hop callers + callees), Finding schema completeness,
groundedness enforcement, optional range targeting, and edge-case handling —
all offline (no live API calls, no database, no network).

Fixtures:
  - reviewer_graph: 5-node DiGraph (target + 2 callers + 2 callees, all CALLS edges)
  - mock_settings: MagicMock with reviewer_context_hops=1
  - mock_llm_factory: patches app.core.model_factory.get_llm at source module

Patch target: 'app.core.model_factory.get_llm'
  Reason: reviewer.py uses a lazy import inside review() body — get_llm is NOT
  a module-level attribute of app.agent.reviewer. Source-level patching intercepts
  the import before the local scope resolves it.

LLM invocation pattern in review():
  structured_llm = llm.with_structured_output(ReviewResult)
  chain = prompt | structured_llm
  result = chain.invoke(...)
  So mock: llm.with_structured_output returns a mock_structured;
           mock_structured.__or__ returns mock_chain;
           mock_chain.invoke returns the fixture ReviewResult.
"""

import pytest
import networkx as nx
from unittest.mock import MagicMock, patch

from app.agent.reviewer import Finding, ReviewResult, review


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def reviewer_graph() -> nx.DiGraph:
    """5-node DiGraph: target + 2 callers + 2 callees, all CALLS edges.

    Topology:
      caller_a (src.py) -> target (src.py) -> callee_a (lib.py)
      caller_b (other.py) -> target (src.py) -> callee_b (lib.py)

    file_path distribution:
      src.py   — target, caller_a
      other.py — caller_b
      lib.py   — callee_a, callee_b
    """
    G = nx.DiGraph()
    nodes = [
        {"node_id": "src.py::target",   "name": "target",   "file_path": "src.py",   "line_start": 10, "line_end": 30},
        {"node_id": "src.py::caller_a", "name": "caller_a", "file_path": "src.py",   "line_start": 1,  "line_end": 9},
        {"node_id": "other.py::caller_b","name": "caller_b","file_path": "other.py", "line_start": 5,  "line_end": 15},
        {"node_id": "lib.py::callee_a", "name": "callee_a", "file_path": "lib.py",   "line_start": 1,  "line_end": 10},
        {"node_id": "lib.py::callee_b", "name": "callee_b", "file_path": "lib.py",   "line_start": 12, "line_end": 20},
    ]
    for n in nodes:
        G.add_node(n["node_id"], **n)
    G.add_edge("src.py::caller_a",  "src.py::target",   type="CALLS")
    G.add_edge("other.py::caller_b","src.py::target",   type="CALLS")
    G.add_edge("src.py::target",    "lib.py::callee_a", type="CALLS")
    G.add_edge("src.py::target",    "lib.py::callee_b", type="CALLS")
    return G


@pytest.fixture
def mock_settings():
    """Minimal settings stub with reviewer_context_hops=1.

    Passed directly to review() to bypass get_settings(), which requires
    postgres env vars not present in the test environment.
    """
    settings = MagicMock()
    settings.reviewer_context_hops = 1
    return settings


@pytest.fixture
def mock_llm_factory():
    """Patch get_llm at source module — lazy import requires source-level patch.

    reviewer.py uses: structured_llm = llm.with_structured_output(ReviewResult)
                       chain = prompt | structured_llm
                       result = chain.invoke(...)
    So: mock_llm.with_structured_output -> mock_structured
        mock_structured.__or__ -> mock_chain (supports pipe operator)
        mock_chain.invoke -> fixture ReviewResult

    Patch target: 'app.core.model_factory.get_llm'
    """
    with patch("app.core.model_factory.get_llm") as mock_factory:
        fixture_result = ReviewResult(
            findings=[
                Finding(
                    severity="warning",
                    category="error-handling",
                    description="Missing error handling in target.",
                    file_path="src.py",
                    line_start=10,
                    line_end=30,
                    suggestion="Wrap in try/except and log exceptions.",
                )
            ],
            retrieved_nodes=[
                "src.py::target",
                "src.py::caller_a",
                "other.py::caller_b",
                "lib.py::callee_a",
                "lib.py::callee_b",
            ],
            summary="One warning found in target function.",
        )

        mock_chain = MagicMock()
        mock_chain.invoke.return_value = fixture_result

        mock_structured = MagicMock()
        mock_structured.__or__ = MagicMock(return_value=mock_chain)

        mock_llm = MagicMock()
        mock_llm.with_structured_output.return_value = mock_structured

        mock_factory.return_value = mock_llm
        yield mock_factory


# ---------------------------------------------------------------------------
# Test 1 — Target node appears in retrieved_nodes (REVW-01)
# ---------------------------------------------------------------------------

def test_retrieved_nodes_contains_target(mock_llm_factory, mock_settings, reviewer_graph):
    """retrieved_nodes must include the target_node_id."""
    result = review("review target for quality", reviewer_graph,
                    target_node_id="src.py::target", settings=mock_settings)
    assert "src.py::target" in result.retrieved_nodes


# ---------------------------------------------------------------------------
# Test 2 — 1-hop callers in retrieved_nodes (REVW-01)
# ---------------------------------------------------------------------------

def test_retrieved_nodes_contains_callers(mock_llm_factory, mock_settings, reviewer_graph):
    """retrieved_nodes must include CALLS-edge predecessors of target."""
    result = review("review target for quality", reviewer_graph,
                    target_node_id="src.py::target", settings=mock_settings)
    assert "src.py::caller_a" in result.retrieved_nodes
    assert "other.py::caller_b" in result.retrieved_nodes


# ---------------------------------------------------------------------------
# Test 3 — 1-hop callees in retrieved_nodes (REVW-01)
# ---------------------------------------------------------------------------

def test_retrieved_nodes_contains_callees(mock_llm_factory, mock_settings, reviewer_graph):
    """retrieved_nodes must include CALLS-edge successors of target."""
    result = review("review target for quality", reviewer_graph,
                    target_node_id="src.py::target", settings=mock_settings)
    assert "lib.py::callee_a" in result.retrieved_nodes
    assert "lib.py::callee_b" in result.retrieved_nodes


# ---------------------------------------------------------------------------
# Test 4 — Finding schema completeness (REVW-02)
# ---------------------------------------------------------------------------

def test_finding_schema_fields(mock_llm_factory, mock_settings, reviewer_graph):
    """Every Finding must have all 7 required fields with correct types."""
    result = review("check error handling in target", reviewer_graph,
                    target_node_id="src.py::target", settings=mock_settings)
    for finding in result.findings:
        assert isinstance(finding.severity, str) and finding.severity in {"critical", "warning", "info"}
        assert isinstance(finding.category, str) and finding.category
        assert isinstance(finding.description, str) and finding.description
        assert isinstance(finding.file_path, str) and finding.file_path
        assert isinstance(finding.line_start, int)
        assert isinstance(finding.line_end, int)
        assert isinstance(finding.suggestion, str) and finding.suggestion


# ---------------------------------------------------------------------------
# Test 5 — Groundedness: no hallucinated file_path (TST-03 / success criterion 4)
# ---------------------------------------------------------------------------

def test_no_hallucinated_nodes(mock_llm_factory, mock_settings, reviewer_graph):
    """No Finding.file_path may reference a file not present in retrieved context."""
    result = review("review target for quality", reviewer_graph,
                    target_node_id="src.py::target", settings=mock_settings)
    valid_file_paths = {
        reviewer_graph.nodes[n].get("file_path", "")
        for n in result.retrieved_nodes
        if n in reviewer_graph
    }
    for finding in result.findings:
        assert finding.file_path in valid_file_paths, (
            f"Hallucinated file_path: {finding.file_path!r} not in retrieved context"
        )


# ---------------------------------------------------------------------------
# Test 6 — Summary is a non-empty string
# ---------------------------------------------------------------------------

def test_summary_is_non_empty_string(mock_llm_factory, mock_settings, reviewer_graph):
    """ReviewResult.summary must be a non-empty string."""
    result = review("review target", reviewer_graph,
                    target_node_id="src.py::target", settings=mock_settings)
    assert isinstance(result.summary, str)
    assert len(result.summary) > 0


# ---------------------------------------------------------------------------
# Test 7 — Range targeting accepted without error (REVW-03)
# ---------------------------------------------------------------------------

def test_range_targeting_accepted(mock_llm_factory, mock_settings, reviewer_graph):
    """review() must accept selected_file and selected_range without raising."""
    result = review(
        "review lines 10-20 of src.py",
        reviewer_graph,
        target_node_id="src.py::target",
        selected_file="src.py",
        selected_range=(10, 20),
        settings=mock_settings,
    )
    assert isinstance(result, ReviewResult)


# ---------------------------------------------------------------------------
# Test 8 — Empty findings list is valid (edge case)
# ---------------------------------------------------------------------------

def test_empty_findings_valid(mock_settings, reviewer_graph):
    """review() must return a valid ReviewResult when LLM returns zero findings."""
    empty_result = ReviewResult(
        findings=[],
        retrieved_nodes=[
            "src.py::target",
            "src.py::caller_a",
            "other.py::caller_b",
            "lib.py::callee_a",
            "lib.py::callee_b",
        ],
        summary="No issues found.",
    )

    with patch("app.core.model_factory.get_llm") as mock_factory:
        mock_chain = MagicMock()
        mock_chain.invoke.return_value = empty_result
        mock_structured = MagicMock()
        mock_structured.__or__ = MagicMock(return_value=mock_chain)
        mock_llm = MagicMock()
        mock_llm.with_structured_output.return_value = mock_structured
        mock_factory.return_value = mock_llm

        result = review("review target", reviewer_graph,
                        target_node_id="src.py::target", settings=mock_settings)

    assert isinstance(result, ReviewResult)
    assert len(result.findings) == 0
    assert result.summary == "No issues found."


# ---------------------------------------------------------------------------
# Test 9 — Missing target node raises ValueError (edge case, REVW-01)
# ---------------------------------------------------------------------------

def test_missing_target_raises(mock_llm_factory, mock_settings, reviewer_graph):
    """review() must raise ValueError when target_node_id is absent from the graph."""
    with pytest.raises(ValueError, match="not found in graph"):
        review("review nonexistent", reviewer_graph,
               target_node_id="nonexistent::func", settings=mock_settings)


# ---------------------------------------------------------------------------
# Test 10 — retrieved_nodes is a list of strings (schema check)
# ---------------------------------------------------------------------------

def test_retrieved_nodes_is_list_of_strings(mock_llm_factory, mock_settings, reviewer_graph):
    """ReviewResult.retrieved_nodes must be a list of non-empty strings."""
    result = review("review target", reviewer_graph,
                    target_node_id="src.py::target", settings=mock_settings)
    assert isinstance(result.retrieved_nodes, list)
    assert len(result.retrieved_nodes) > 0
    for node_id in result.retrieved_nodes:
        assert isinstance(node_id, str) and node_id
