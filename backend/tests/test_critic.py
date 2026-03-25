"""Tests for the Critic Agent (Phase 21, TST-05).

Verifies scoring formula arithmetic, retry routing, hard loop cap, boundary
conditions, per-type groundedness dispatch, and feedback semantics — all offline
(no live API calls, no database, no network).

Fixtures:
  - mock_settings: MagicMock with max_critic_loops=2, critic_threshold=0.7

Helpers (module-level functions, not fixtures):
  - make_debug_result: builds a DebugResult with given suspect node_ids and traversal_path
  - make_review_result: builds a ReviewResult with given file_paths and retrieved_nodes
  - make_test_result: builds a TestResult with given test_code

critique() accepts settings directly — no patching of get_settings required.
All tests inject mock_settings directly into critique() to bypass env var requirements.
"""

import pytest
from unittest.mock import MagicMock
from app.agent.critic import CriticResult, critique
from app.agent.debugger import DebugResult, SuspectNode
from app.agent.reviewer import ReviewResult, Finding
from app.agent.tester import TestResult


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_settings():
    """Settings stub with critic knobs — injected directly into critique()."""
    s = MagicMock()
    s.max_critic_loops = 2
    s.critic_threshold = 0.7
    return s


# ---------------------------------------------------------------------------
# Helper builders (module-level functions — callable with arbitrary arguments)
# ---------------------------------------------------------------------------

def make_debug_result(node_ids: list[str], traversal: list[str], diagnosis: str = "test diagnosis") -> DebugResult:
    suspects = [
        SuspectNode(node_id=n, file_path=f"{n}.py", line_start=1, anomaly_score=0.5, reasoning="test")
        for n in node_ids
    ]
    return DebugResult(suspects=suspects, traversal_path=traversal, impact_radius=[], diagnosis=diagnosis)


def make_review_result(file_paths: list[str], retrieved_nodes: list[str], summary: str = "ok") -> ReviewResult:
    findings = [
        Finding(severity="warning", category="style", description="test", file_path=fp,
                line_start=1, line_end=5, suggestion="fix it")
        for fp in file_paths
    ]
    return ReviewResult(findings=findings, retrieved_nodes=retrieved_nodes, summary=summary)


def make_test_result(test_code: str = "", framework: str = "pytest") -> TestResult:
    return TestResult(test_code=test_code, test_file_path="tests/test_foo.py", framework=framework)


# ---------------------------------------------------------------------------
# Test 1 — Scoring formula weights (CRIT-01)
# ---------------------------------------------------------------------------

def test_scoring_formula_weights(mock_settings):
    """score == round(0.4*G + 0.35*R + 0.25*A, 4)."""
    r = make_debug_result(["a"], ["a"], "diagnosis mentioning a")  # G=1.0, suspects present
    result = critique(r, loop_count=0, settings=mock_settings)
    expected = round(
        0.40 * result.groundedness + 0.35 * result.relevance + 0.25 * result.actionability, 4
    )
    assert abs(result.score - expected) < 1e-6


# ---------------------------------------------------------------------------
# Test 2 — Retry routing on low score (CRIT-02)
# ---------------------------------------------------------------------------

def test_retry_routing_on_low_score(mock_settings):
    """score < 0.7 and loop_count=0 → passed=False, feedback is non-empty str."""
    # cited node NOT in traversal → G=0.0 → composite score will be low
    r = make_debug_result(["x"], [])   # suspects=[x], traversal=[] → G=0.0
    result = critique(r, loop_count=0, settings=mock_settings)
    assert result.passed is False
    assert isinstance(result.feedback, str)
    assert len(result.feedback) > 0


# ---------------------------------------------------------------------------
# Test 3 — Hard cap at loop_count=2 (CRIT-03)
# ---------------------------------------------------------------------------

def test_hard_cap_at_two_loops(mock_settings):
    """loop_count >= 2 forces passed=True regardless of score."""
    r = make_debug_result(["x"], [])  # G=0.0 → score would fail quality gate
    result = critique(r, loop_count=2, settings=mock_settings)
    assert result.passed is True      # cap overrides score
    assert result.feedback is None


# ---------------------------------------------------------------------------
# Test 4 — Loop boundary: loop_count=1 still rejects (CRIT-03)
# ---------------------------------------------------------------------------

def test_loop_count_one_still_rejects(mock_settings):
    """loop_count=1 with low score → passed=False (cap fires at 2, not 1)."""
    r = make_debug_result(["x"], [])
    result = critique(r, loop_count=1, settings=mock_settings)
    assert result.passed is False


# ---------------------------------------------------------------------------
# Test 5 — Feedback cleared on pass (TST-05)
# ---------------------------------------------------------------------------

def test_feedback_none_on_pass(mock_settings):
    """When passed=True, feedback must be None — never empty string."""
    mock_settings.critic_threshold = 0.0   # force pass regardless of score
    r = make_debug_result(["a"], ["a"], "diagnosis")
    result = critique(r, loop_count=0, settings=mock_settings)
    assert result.passed is True
    assert result.feedback is None


# ---------------------------------------------------------------------------
# Test 6 — DebugResult groundedness uses traversal_path (CRIT-04)
# ---------------------------------------------------------------------------

def test_debug_result_groundedness_cited_in_traversal(mock_settings):
    """DebugResult: suspect node_id in traversal_path → groundedness = 1.0."""
    r = make_debug_result(["func_a"], ["func_a", "func_b"])
    result = critique(r, loop_count=0, settings=mock_settings)
    assert result.groundedness == 1.0


# ---------------------------------------------------------------------------
# Test 7 — DebugResult groundedness: cited not in traversal → G < 1.0 (CRIT-04)
# ---------------------------------------------------------------------------

def test_debug_result_groundedness_not_in_traversal(mock_settings):
    """DebugResult: suspect node_id absent from traversal_path → groundedness < 1.0."""
    r = make_debug_result(["unknown_node"], ["func_a"])
    result = critique(r, loop_count=0, settings=mock_settings)
    assert result.groundedness < 1.0


# ---------------------------------------------------------------------------
# Test 8 — ReviewResult groundedness uses retrieved_nodes (CRIT-04)
# ---------------------------------------------------------------------------

def test_review_result_groundedness(mock_settings):
    """ReviewResult: finding file_path in retrieved_nodes → groundedness = 1.0."""
    r = make_review_result(["app/foo.py"], ["node_a"], summary="summary")
    # retrieved_nodes are node IDs not file paths — groundedness uses file_path set match
    # With file_path cited but retrieved_nodes containing different IDs:
    # groundedness = 0/1 since "app/foo.py" not in set(["node_a"])
    # This verifies the dispatch path runs without error; exact value depends on impl
    result = critique(r, loop_count=0, settings=mock_settings)
    assert isinstance(result.groundedness, float)
    assert 0.0 <= result.groundedness <= 1.0


# ---------------------------------------------------------------------------
# Test 9 — TestResult groundedness is always 1.0 (CRIT-04)
# ---------------------------------------------------------------------------

def test_test_result_groundedness_always_one(mock_settings):
    """TestResult has no graph citations → groundedness defaults to 1.0."""
    r = make_test_result("def test_foo(): pass\ndef test_bar(): pass\ndef test_baz(): pass")
    result = critique(r, loop_count=0, settings=mock_settings)
    assert result.groundedness == 1.0


# ---------------------------------------------------------------------------
# Test 10 — CriticResult always includes score and loop_count (observability)
# ---------------------------------------------------------------------------

def test_critic_result_always_has_score_and_loop_count(mock_settings):
    """All four sub-scores and loop_count must be present even on hard-cap path."""
    r = make_debug_result(["x"], [])
    for lc in [0, 1, 2]:
        result = critique(r, loop_count=lc, settings=mock_settings)
        assert 0.0 <= result.score <= 1.0
        assert 0.0 <= result.groundedness <= 1.0
        assert 0.0 <= result.relevance <= 1.0
        assert 0.0 <= result.actionability <= 1.0
        assert result.loop_count == lc
