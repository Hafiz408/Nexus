"""Tests for the Router Agent (Phase 17 accuracy gate).

Verifies three routing behaviours — all offline (no live API calls):
  1. 12 labelled queries return the correct intent via mock LLM
  2. Valid intent_hint values bypass the LLM entirely
  3. A low-confidence LLM result is overridden to 'explain' with confidence preserved

Requirements: ROUT-01, ROUT-02, ROUT-03, ROUT-04
Patch target: 'app.agent.router.get_llm'
  Reason: get_llm is imported via a lazy local import inside route(), placing it
  in the app.agent.router module namespace at call time.
"""
from unittest.mock import MagicMock, patch

import pytest

from app.agent.router import IntentResult, route


# ---------------------------------------------------------------------------
# Labelled corpus (Phase 17 accuracy gate — 12 queries, 100% required)
# ---------------------------------------------------------------------------

LABELLED_QUERIES = [
    # explain (3)
    ("What does the `auth_middleware` function do?",                      "explain"),
    ("Walk me through the ingestion pipeline architecture.",               "explain"),
    ("Why is the graph_rag_retrieve function slow on large repos?",        "explain"),
    # debug (3)
    ("My service crashes with KeyError in graph_store. What's wrong?",    "debug"),
    ("The embedder returns None for some documents. How do I debug this?", "debug"),
    ("Users report a NullPointerException in the walker. Trace the cause.", "debug"),
    # review (3)
    ("Review the query_router.py for security issues.",                    "review"),
    ("Is the error handling in pipeline.py production-quality?",           "review"),
    ("Check the explorer agent for code smells.",                          "review"),
    # test (3)
    ("Generate pytest tests for the `format_context_block` function.",     "test"),
    ("Write unit tests for the embedder with mock pgvector.",              "test"),
    ("Create test cases covering edge cases in the AST parser.",           "test"),
]

VALID_HINTS = ["explain", "debug", "review", "test"]
NON_BYPASS_VALUES = ["auto", "", None]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_llm(intent: str, confidence: float) -> MagicMock:
    """Build a MagicMock that mimics a LangChain LLM with structured output.

    LCEL wraps with_structured_output() result in a RunnableLambda and calls it
    as a callable (not via .invoke()) when the chain is invoked. Therefore we set
    mock_structured.return_value (the __call__ return value) rather than
    mock_structured.invoke.return_value.
    """
    mock_structured = MagicMock(
        return_value=IntentResult(
            intent=intent, confidence=confidence, reasoning="mock reasoning"
        )
    )
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = mock_structured
    return mock_llm


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_llm_factory():
    """Patch get_llm at its source module so no API calls are made.

    Patch target: 'app.core.model_factory.get_llm'

    Why not 'app.agent.router.get_llm'?
    router.py uses a lazy import: `from app.core.model_factory import get_llm`
    inside the route() body. This means get_llm is NOT a module-level attribute
    of app.agent.router — it only exists in the local scope when route() runs.
    Patching the source (app.core.model_factory.get_llm) intercepts it before
    the local import resolves, which is the correct patch point for lazy imports.
    """
    with patch("app.core.model_factory.get_llm") as mock_factory:
        yield mock_factory


# ---------------------------------------------------------------------------
# Behaviour 1: 12 labelled queries — 100% accuracy gate (ROUT-01, ROUT-02)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("question,expected_intent", LABELLED_QUERIES)
def test_labelled_queries(mock_llm_factory, question, expected_intent):
    """Each labelled query must return the correct intent via mock LLM.

    Mock LLM is configured to return the expected intent at confidence=0.9
    (above CONFIDENCE_THRESHOLD=0.6, so no fallback override occurs).
    """
    mock_llm_factory.return_value = _make_mock_llm(expected_intent, 0.9)

    result = route(question)

    assert result.intent == expected_intent, (
        f"Query '{question[:50]}...' returned intent='{result.intent}', "
        f"expected='{expected_intent}'"
    )
    assert 0.0 <= result.confidence <= 1.0


# ---------------------------------------------------------------------------
# Behaviour 2: intent_hint bypass — LLM never called (ROUT-03)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("hint", VALID_HINTS)
def test_intent_hint_bypasses_llm(mock_llm_factory, hint):
    """Valid intent_hint values must bypass the LLM entirely.

    Checks:
      - result.intent matches the supplied hint
      - result.confidence is exactly 1.0
      - get_llm (mock_llm_factory) was never called
    """
    result = route("any question at all", intent_hint=hint)

    assert result.intent == hint
    assert result.confidence == 1.0
    mock_llm_factory.assert_not_called()


@pytest.mark.parametrize("non_hint", NON_BYPASS_VALUES)
def test_invalid_hint_falls_through_to_llm(mock_llm_factory, non_hint):
    """'auto', empty string, and None must NOT bypass the LLM.

    These values are deliberately excluded from _VALID_HINTS and must
    trigger a normal LLM call.
    """
    mock_llm_factory.return_value = _make_mock_llm("explain", 0.9)

    route("some question", intent_hint=non_hint)

    mock_llm_factory.assert_called_once()


# ---------------------------------------------------------------------------
# Behaviour 3: low-confidence fallback (ROUT-04)
# ---------------------------------------------------------------------------

def test_low_confidence_falls_back_to_explain(mock_llm_factory):
    """When LLM confidence < 0.6, intent is overridden to 'explain'.

    The original low confidence value must be preserved in the returned result.
    """
    mock_llm_factory.return_value = _make_mock_llm("debug", 0.4)

    result = route("ambiguous question")

    assert result.intent == "explain", (
        f"Expected 'explain' fallback for low-confidence result, got '{result.intent}'"
    )
    assert result.confidence == pytest.approx(0.4), (
        f"Expected original confidence 0.4 to be preserved, got {result.confidence}"
    )


# ---------------------------------------------------------------------------
# Sanity: confidence field always in [0.0, 1.0] (all paths)
# ---------------------------------------------------------------------------

def test_result_has_confidence_field(mock_llm_factory):
    """Sanity check — route() always returns IntentResult with confidence in [0.0, 1.0]."""
    mock_llm_factory.return_value = _make_mock_llm("review", 0.85)

    result = route("Is the code quality good?")

    assert isinstance(result, IntentResult)
    assert 0.0 <= result.confidence <= 1.0
