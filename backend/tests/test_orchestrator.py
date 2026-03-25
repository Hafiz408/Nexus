"""Integration tests for the Phase 22 LangGraph orchestrator.

All 6 tests run offline:
  - MemorySaver (no sqlite thread issues)
  - mock_llm patches app.core.model_factory.get_llm at source
  - specialist agents are mocked directly for routing tests
  - critique() is mocked with side_effect for retry/max_loops tests

Test inventory (TST-07):
  1. test_explain_path       — intent='explain' routes to explain_node
  2. test_debug_path         — intent='debug' routes to debug_node
  3. test_review_path        — intent='review' routes to review_node
  4. test_test_path          — intent='test' routes to test_node
  5. test_critic_retry       — critic fails first call, specialist reruns, critic passes second
  6. test_max_loops_termination — critic always fails but loop caps at 2 retries
"""
import pytest
from unittest.mock import MagicMock, patch
from langgraph.checkpoint.memory import MemorySaver

from app.agent.orchestrator import build_graph, NexusState
from app.agent.debugger import DebugResult, SuspectNode
from app.agent.reviewer import ReviewResult, Finding
from app.agent.tester import TestResult
from app.agent.critic import CriticResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_llm():
    """Mock LLM that handles both plain invoke() and with_structured_output() chains.

    LangChain LCEL pipe (prompt | llm) calls llm via its Runnable protocol.
    Depending on the LangChain version, this may call llm.__call__(messages) rather
    than llm.invoke(messages). Setting both return_value and invoke.return_value
    ensures the mock works regardless of which call path LCEL uses.
    """
    mock = MagicMock()
    llm_response = MagicMock()
    llm_response.content = "mocked LLM answer"
    # Cover both call paths used by LangChain LCEL
    mock.invoke.return_value = llm_response
    mock.return_value = llm_response
    # with_structured_output returns a mock whose __call__ also returns mock
    mock.with_structured_output.return_value = mock
    return mock


@pytest.fixture
def base_state(sample_graph) -> NexusState:
    """Minimal valid NexusState for a query with intent_hint='explain'.

    G is set to None (not sample_graph) because MemorySaver serializes all
    state fields via msgpack and nx.DiGraph is not msgpack-serializable.
    The explain_node wraps graph_rag_retrieve in a try/except so G=None
    causes retrieval to be skipped gracefully (empty context, LLM still runs).
    For debug/review/test routing tests, the agent functions are mocked so
    G is never accessed.
    """
    return {
        "question": "explain func_a",
        "repo_path": "/repo",
        "intent_hint": "explain",
        "G": None,
        "target_node_id": "a.py::func_a",
        "selected_file": None,
        "selected_range": None,
        "repo_root": "/repo",
        "intent": None,
        "specialist_result": None,
        "critic_result": None,
        "loop_count": 0,
    }


def _make_passing_critic(loop_count: int = 0) -> CriticResult:
    return CriticResult(
        score=0.9, groundedness=1.0, relevance=1.0, actionability=1.0,
        passed=True, feedback=None, loop_count=loop_count,
    )


def _make_failing_critic(loop_count: int = 0) -> CriticResult:
    return CriticResult(
        score=0.3, groundedness=0.3, relevance=0.3, actionability=0.3,
        passed=False, feedback="Groundedness is low.", loop_count=loop_count,
    )


def _make_debug_result() -> DebugResult:
    return DebugResult(
        suspects=[
            SuspectNode(
                node_id="a.py::func_a",
                file_path="/repo/a.py",
                line_start=1,
                anomaly_score=0.8,
                reasoning="complexity=3, no error handling, anomaly_score=0.80",
            )
        ],
        traversal_path=["a.py::func_a", "b.py::func_b"],
        impact_radius=[],
        diagnosis="func_a is the likely root cause based on high anomaly score.",
    )


def _make_review_result() -> ReviewResult:
    return ReviewResult(
        findings=[
            Finding(
                severity="warning",
                category="error-handling",
                description="No exception handling around external call",
                file_path="/repo/a.py",
                line_start=2,
                line_end=4,
                suggestion="Wrap in try/except and log the error.",
            )
        ],
        retrieved_nodes=["a.py::func_a"],
        summary="One warning found in func_a.",
    )


def _make_test_result() -> TestResult:
    return TestResult(
        test_code="def test_func_a_happy_path():\n    assert True\ndef test_func_a_error():\n    pass\ndef test_func_a_edge():\n    pass",
        test_file_path="tests/test_func_a.py",
        framework="pytest",
    )


# ---------------------------------------------------------------------------
# Test 1: Explain path
# ---------------------------------------------------------------------------

def test_explain_path(base_state, mock_llm):
    """intent='explain' routes through explain_node; specialist_result has an answer string."""
    with patch("app.core.model_factory.get_llm", return_value=mock_llm), \
         patch("app.agent.critic.critique", return_value=_make_passing_critic()):
        graph = build_graph(checkpointer=MemorySaver())
        result = graph.invoke(
            base_state,
            config={"configurable": {"thread_id": "test-explain-1"}},
        )

    assert result["intent"] == "explain"
    assert result["specialist_result"] is not None
    # _ExplainResult has an .answer attribute
    assert hasattr(result["specialist_result"], "answer")
    assert result["critic_result"].passed is True


# ---------------------------------------------------------------------------
# Test 2: Debug path
# ---------------------------------------------------------------------------

def test_debug_path(base_state, mock_llm, sample_graph):
    """intent='debug' routes through debug_node; specialist_result is a DebugResult."""
    debug_state = {**base_state, "intent_hint": "debug"}
    expected = _make_debug_result()

    with patch("app.core.model_factory.get_llm", return_value=mock_llm), \
         patch("app.agent.debugger.debug", return_value=expected), \
         patch("app.agent.critic.critique", return_value=_make_passing_critic()):
        graph = build_graph(checkpointer=MemorySaver())
        result = graph.invoke(
            debug_state,
            config={"configurable": {"thread_id": "test-debug-1"}},
        )

    assert result["intent"] == "debug"
    assert isinstance(result["specialist_result"], DebugResult)
    assert len(result["specialist_result"].suspects) == 1
    assert result["critic_result"].passed is True


# ---------------------------------------------------------------------------
# Test 3: Review path
# ---------------------------------------------------------------------------

def test_review_path(base_state, mock_llm, sample_graph):
    """intent='review' routes through review_node; specialist_result is a ReviewResult."""
    review_state = {**base_state, "intent_hint": "review"}
    expected = _make_review_result()

    with patch("app.core.model_factory.get_llm", return_value=mock_llm), \
         patch("app.agent.reviewer.review", return_value=expected), \
         patch("app.agent.critic.critique", return_value=_make_passing_critic()):
        graph = build_graph(checkpointer=MemorySaver())
        result = graph.invoke(
            review_state,
            config={"configurable": {"thread_id": "test-review-1"}},
        )

    assert result["intent"] == "review"
    assert isinstance(result["specialist_result"], ReviewResult)
    assert len(result["specialist_result"].findings) == 1
    assert result["critic_result"].passed is True


# ---------------------------------------------------------------------------
# Test 4: Test path
# ---------------------------------------------------------------------------

def test_test_path(base_state, mock_llm, sample_graph):
    """intent='test' routes through test_node; specialist_result is a TestResult."""
    test_state = {**base_state, "intent_hint": "test"}
    expected = _make_test_result()

    with patch("app.core.model_factory.get_llm", return_value=mock_llm), \
         patch("app.agent.tester.test", return_value=expected), \
         patch("app.agent.critic.critique", return_value=_make_passing_critic()):
        graph = build_graph(checkpointer=MemorySaver())
        result = graph.invoke(
            test_state,
            config={"configurable": {"thread_id": "test-test-1"}},
        )

    assert result["intent"] == "test"
    assert isinstance(result["specialist_result"], TestResult)
    assert "def test_" in result["specialist_result"].test_code
    assert result["critic_result"].passed is True


# ---------------------------------------------------------------------------
# Test 5: Critic retry loop
# ---------------------------------------------------------------------------

def test_critic_retry(base_state, mock_llm):
    """Critic fails on first specialist call; graph reruns explain_node; critic passes second time.

    side_effect list: [failing_CriticResult, passing_CriticResult]
    The specialist runs twice; the loop terminates after second critic pass.
    """
    side_effects = [
        _make_failing_critic(loop_count=0),  # first call: fail -> increment loop_count -> retry
        _make_passing_critic(loop_count=1),  # second call: pass -> done
    ]

    with patch("app.core.model_factory.get_llm", return_value=mock_llm), \
         patch("app.agent.critic.critique", side_effect=side_effects):
        graph = build_graph(checkpointer=MemorySaver())
        result = graph.invoke(
            base_state,
            config={"configurable": {"thread_id": "test-retry-1"}},
        )

    assert result["critic_result"].passed is True
    # loop_count was incremented once (from 0 to 1) on the retry path
    assert result["loop_count"] == 1


# ---------------------------------------------------------------------------
# Test 6: Max loops termination
# ---------------------------------------------------------------------------

def test_max_loops_termination(base_state, mock_llm):
    """Critic always fails; graph terminates after 2 retries (loop_count reaches 2 = hard cap).

    The critic.critique() hard-cap logic fires at loop_count >= max_critic_loops (default 2).
    But here we mock critique() directly, so we simulate what the real critique() would do:
    - call 1 (loop_count=0): fail -> loop_count becomes 1 -> retry
    - call 2 (loop_count=1): fail -> loop_count becomes 2 -> retry
    - call 3 (loop_count=2): hard cap fires in real critic; we mock as passed=True
      (simulating what critic.py CRIT-03 does: force passed=True when loop_count >= max_loops)

    This confirms the graph terminates -- it never runs a 4th specialist iteration.
    """
    side_effects = [
        _make_failing_critic(loop_count=0),  # fail -> loop_count -> 1
        _make_failing_critic(loop_count=1),  # fail -> loop_count -> 2
        # At loop_count=2, real critique() would hard-cap to passed=True (CRIT-03)
        CriticResult(
            score=0.3, groundedness=0.3, relevance=0.3, actionability=0.3,
            passed=True,   # hard cap forces passed=True
            feedback=None, loop_count=2,
        ),
    ]

    with patch("app.core.model_factory.get_llm", return_value=mock_llm), \
         patch("app.agent.critic.critique", side_effect=side_effects):
        graph = build_graph(checkpointer=MemorySaver())
        result = graph.invoke(
            base_state,
            config={"configurable": {"thread_id": "test-maxloops-1"}},
        )

    # Graph terminated -- final state is present
    assert result["critic_result"].passed is True
    assert result["loop_count"] == 2
    # score is low (0.3) confirming this was a hard-cap termination, not a quality pass
    assert result["critic_result"].score < 0.7
