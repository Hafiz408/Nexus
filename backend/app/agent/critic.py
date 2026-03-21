"""Critic Agent — deterministic quality gate for the V2 multi-agent pipeline.

Exposes:
  - CriticResult  Pydantic model (score, groundedness, relevance, actionability,
                  passed, feedback, loop_count)
  - critique(result, loop_count, settings=None) -> CriticResult

No LLM call is made — this is a fully deterministic quality gate.

get_settings() is lazy-imported inside critique() body — never at module level.
loop_count=0 means the first call; the hard cap triggers when
loop_count >= max_critic_loops (default 2), forcing passed=True unconditionally
so the loop always terminates.

Specialist result types (DebugResult, ReviewResult, TestResult) are also
imported lazily — inside the private helper functions that need them — to avoid
circular import chains when the orchestrator (Phase 22) imports all agents together.
"""
from __future__ import annotations

from typing import Union

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Constants — safe at import time (no get_llm() / get_settings() here)
# Locked by CRIT-01 — do not change the weight values.
# ---------------------------------------------------------------------------

WEIGHT_GROUNDEDNESS  = 0.40
WEIGHT_RELEVANCE     = 0.35
WEIGHT_ACTIONABILITY = 0.25


# ---------------------------------------------------------------------------
# Pydantic output model
# ---------------------------------------------------------------------------

class CriticResult(BaseModel):
    """Quality gate result from a single critique() call."""

    score: float = Field(ge=0.0, le=1.0)           # 0.4*G + 0.35*R + 0.25*A
    groundedness: float = Field(ge=0.0, le=1.0)    # fraction of cited nodes in retrieved set
    relevance: float = Field(ge=0.0, le=1.0)       # structural content quality
    actionability: float = Field(ge=0.0, le=1.0)   # specificity (file:line, suggestions)
    passed: bool                                     # True = accept; False = route back
    feedback: str | None                            # None when passed=True; critique text otherwise
    loop_count: int                                  # loop_count value at time of critique


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _compute_groundedness(cited_nodes: set[str], retrieved_nodes: list[str]) -> float:
    """Return fraction of cited nodes that appear in the retrieved set.

    Returns 1.0 when cited_nodes is empty (nothing cited = fully grounded;
    avoids division-by-zero).
    """
    if not cited_nodes:
        return 1.0
    return len(cited_nodes & set(retrieved_nodes)) / len(cited_nodes)


def _extract_groundedness_inputs(result) -> tuple[set[str], list[str]]:
    """Dispatch on result type to extract (cited_nodes, retrieved_nodes).

    Imports are lazy inside this function to prevent circular dependencies
    when the orchestrator imports all agents at once.
    """
    from app.agent.debugger import DebugResult   # noqa: PLC0415
    from app.agent.reviewer import ReviewResult  # noqa: PLC0415
    from app.agent.tester import TestResult      # noqa: PLC0415

    if isinstance(result, DebugResult):
        cited = {s.node_id for s in result.suspects}
        retrieved = result.traversal_path
    elif isinstance(result, ReviewResult):
        cited = {f.file_path for f in result.findings}
        retrieved = result.retrieved_nodes
    elif isinstance(result, TestResult):
        cited = set()
        retrieved = []
    else:
        cited = set()
        retrieved = []

    return cited, retrieved


def _compute_relevance(result) -> float:
    """Dispatch on result type to produce a relevance score in [0.0, 1.0].

    Imports are lazy inside this function to prevent circular dependencies.
    """
    from app.agent.debugger import DebugResult   # noqa: PLC0415
    from app.agent.reviewer import ReviewResult  # noqa: PLC0415
    from app.agent.tester import TestResult      # noqa: PLC0415

    if isinstance(result, DebugResult):
        return 1.0 if (len(result.suspects) > 0 and result.diagnosis) else 0.3
    elif isinstance(result, ReviewResult):
        return 1.0 if (len(result.findings) > 0 and result.summary) else 0.3
    elif isinstance(result, TestResult):
        return 1.0 if (result.test_code and "def test_" in result.test_code) else 0.3
    else:
        return 0.5


def _compute_actionability(result) -> float:
    """Dispatch on result type to produce an actionability score in [0.0, 1.0].

    Imports are lazy inside this function to prevent circular dependencies.
    """
    from app.agent.debugger import DebugResult   # noqa: PLC0415
    from app.agent.reviewer import ReviewResult  # noqa: PLC0415
    from app.agent.tester import TestResult      # noqa: PLC0415

    if isinstance(result, DebugResult):
        return min(len(result.suspects) / 5.0, 1.0)
    elif isinstance(result, ReviewResult):
        if not result.findings:
            return 1.0  # nothing to critique = not an actionability problem
        return sum(1 for f in result.findings if f.suggestion) / len(result.findings)
    elif isinstance(result, TestResult):
        if not result.test_code:
            return 0.0
        return min(result.test_code.count("def test_") / 3.0, 1.0)
    else:
        return 0.5


def _weighted_score(g: float, r: float, a: float) -> float:
    """Compute the composite weighted score and clamp to [0.0, 1.0], rounded to 4dp."""
    score = WEIGHT_GROUNDEDNESS * g + WEIGHT_RELEVANCE * r + WEIGHT_ACTIONABILITY * a
    return round(min(max(score, 0.0), 1.0), 4)


def _generate_feedback(g: float, r: float, a: float, score: float) -> str:
    """Build a human-readable feedback string from sub-scores.

    Appends specific guidance for each sub-score below 0.5.
    Falls back to a generic message when all sub-scores are acceptable but
    the composite score still falls below the threshold.
    """
    parts: list[str] = []

    if g < 0.5:
        parts.append(
            f"Groundedness is low ({g:.2f}): cited nodes not found in retrieved context. "
            "Reference only functions/files that were part of the graph traversal."
        )
    if r < 0.5:
        parts.append(
            f"Relevance is low ({r:.2f}): response lacks substantive findings. "
            "Ensure the output directly addresses the query with specific findings."
        )
    if a < 0.5:
        parts.append(
            f"Actionability is low ({a:.2f}): findings lack concrete details. "
            "Include file paths, line numbers, and specific suggestions."
        )

    if not parts:
        parts.append(
            f"Overall score ({score:.2f}) is below threshold. "
            "Improve specificity and coverage of findings."
        )

    return " | ".join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def critique(result, loop_count: int, settings=None) -> CriticResult:
    """Apply deterministic quality gate to a specialist result.

    loop_count=0 on first call; cap fires when loop_count >= max_critic_loops.

    Args:
        result:     A DebugResult, ReviewResult, or TestResult instance.
        loop_count: Number of completed retry cycles so far (0 = first attempt).
        settings:   Optional Settings instance; lazy-loaded from app.config if None.

    Returns:
        CriticResult with passed=True (accept) or passed=False (route back for retry).
    """
    # Step 1: Lazy-load settings if not provided (avoids ValidationError at import time)
    if settings is None:
        from app.config import get_settings  # noqa: PLC0415
        settings = get_settings()

    # Step 2: Read tuning knobs from settings
    max_loops: int = settings.max_critic_loops
    threshold: float = settings.critic_threshold

    # Step 3: Compute the three sub-scores
    cited, retrieved = _extract_groundedness_inputs(result)
    g = _compute_groundedness(cited, retrieved)
    r = _compute_relevance(result)
    a = _compute_actionability(result)

    # Step 4: Composite score
    score = _weighted_score(g, r, a)

    # Step 5: Hard cap — loop has run max_loops times; force accept (CRIT-03)
    if loop_count >= max_loops:
        return CriticResult(
            score=score,
            groundedness=g,
            relevance=r,
            actionability=a,
            passed=True,
            feedback=None,
            loop_count=loop_count,
        )

    # Step 6: Quality gate — score below threshold means route back (CRIT-02)
    if score < threshold:
        feedback = _generate_feedback(g, r, a, score)
        return CriticResult(
            score=score,
            groundedness=g,
            relevance=r,
            actionability=a,
            passed=False,
            feedback=feedback,
            loop_count=loop_count,
        )

    # Step 7: Pass — score meets or exceeds threshold
    return CriticResult(
        score=score,
        groundedness=g,
        relevance=r,
        actionability=a,
        passed=True,
        feedback=None,
        loop_count=loop_count,
    )
