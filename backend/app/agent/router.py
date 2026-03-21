"""Router Agent — intent classifier for the V2 multi-agent pipeline.

Exposes:
  - IntentResult     Pydantic model (intent, confidence, reasoning)
  - route(question, intent_hint=None) -> IntentResult
  - CONFIDENCE_THRESHOLD
  - _VALID_HINTS

Three classification paths:
  Path 1: intent_hint in _VALID_HINTS → skip LLM, return immediately (ROUT-03)
  Path 2: LLM returns confidence >= CONFIDENCE_THRESHOLD → return as-is (ROUT-01)
  Path 3: LLM returns confidence < CONFIDENCE_THRESHOLD → override to 'explain' (ROUT-04)

Critical: get_llm() is imported INSIDE route() body — never at module level.
This prevents ValidationError during pytest collection when API keys are absent.
"""
from __future__ import annotations

from typing import Literal

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

class IntentResult(BaseModel):
    """Router output — intent classification with confidence."""

    intent: Literal["explain", "debug", "review", "test"] = Field(
        description="The developer's intent: explain code, debug a bug, review code, or generate tests"
    )
    confidence: float = Field(
        description="Classifier confidence in [0.0, 1.0]",
        ge=0.0,
        le=1.0,
    )
    reasoning: str = Field(
        description="One sentence explaining why this intent was chosen"
    )


# ---------------------------------------------------------------------------
# Module-level constants — safe at import time (no get_llm() call here)
# ---------------------------------------------------------------------------

ROUTER_SYSTEM = """You are an intent classifier for a code intelligence assistant.
Classify the developer query into exactly one of four intents:
- explain: understanding code, architecture, or concepts
- debug: finding bugs, errors, crashes, or unexpected behaviour
- review: code quality, security, style, or best practice feedback
- test: generating test cases or test code

Return only the intent, your confidence (0.0–1.0), and a one-sentence reasoning."""

ROUTER_PROMPT = ChatPromptTemplate.from_messages([
    ("system", ROUTER_SYSTEM),
    ("human", "{question}"),
])

CONFIDENCE_THRESHOLD = 0.6
_VALID_HINTS = frozenset({"explain", "debug", "review", "test"})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def route(question: str, intent_hint: str | None = None) -> IntentResult:
    """Classify question into one of four intents.

    Path 1: intent_hint in _VALID_HINTS → skip LLM, return immediately (ROUT-03)
    Path 2: LLM returns confidence >= CONFIDENCE_THRESHOLD → return as-is (ROUT-01)
    Path 3: LLM returns confidence < CONFIDENCE_THRESHOLD → override to 'explain' (ROUT-04)

    Args:
        question: The developer's query to classify.
        intent_hint: Optional explicit intent. Empty string and "auto" fall through
                     to the LLM path; only the four valid intent strings bypass it.

    Returns:
        IntentResult with the classified intent, confidence score, and reasoning.
    """
    # Path 1: hint bypass — empty string and "auto" fall through to LLM
    if intent_hint and intent_hint in _VALID_HINTS:
        return IntentResult(
            intent=intent_hint,  # type: ignore[arg-type]
            confidence=1.0,
            reasoning=f"User-supplied intent_hint '{intent_hint}' used directly.",
        )

    # Path 2 + 3: LLM classification (lazy import keeps module importable without API key)
    from app.core.model_factory import get_llm  # noqa: PLC0415

    llm = get_llm()
    structured_llm = llm.with_structured_output(IntentResult)
    chain = ROUTER_PROMPT | structured_llm
    result: IntentResult = chain.invoke({"question": question})

    # Path 3: low-confidence fallback — construct new instance (Pydantic v2 is immutable)
    if result.confidence < CONFIDENCE_THRESHOLD:
        return IntentResult(
            intent="explain",
            confidence=result.confidence,
            reasoning=f"Low confidence ({result.confidence:.2f}); defaulted to explain.",
        )

    return result
