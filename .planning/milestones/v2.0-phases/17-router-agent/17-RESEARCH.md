# Phase 17: router-agent - Research

**Researched:** 2026-03-22
**Domain:** LangChain structured output / intent classification / pytest mocking
**Confidence:** HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| ROUT-01 | Router classifies developer queries into `explain`, `debug`, `review`, or `test` with confidence score | Pydantic model with `Literal` intent + `float` confidence; `llm.with_structured_output(IntentResult)` pattern |
| ROUT-02 | Router achieves 100% accuracy on all 12 labelled test cases in `test_router_agent.py` | Deterministic prompt + structured output + labelled query corpus; mock LLM returns controlled Pydantic responses |
| ROUT-03 | When `intent_hint` is provided, router uses it directly without an LLM call | Early-return guard in `route()` before any LLM instantiation; maps hint string to intent enum |
| ROUT-04 | When confidence < 0.6, router defaults to `explain` | Post-LLM guard: `if result.confidence < 0.6: result.intent = "explain"` |
| TST-01 | `test_router_agent.py` — 12 labelled queries at 100% accuracy; intent_hint bypass; low-confidence fallback | Monkeypatch `get_llm` at `app.agent.router.get_llm`; `MagicMock().with_structured_output()` returns controlled Pydantic instances |
</phase_requirements>

---

## Summary

Phase 17 builds a standalone router module (`app/agent/router.py`) that classifies any developer query into one of four intents: `explain`, `debug`, `review`, or `test`. It is a pure Python function, not a LangGraph node — the graph wiring happens in Phase 22. This keeps the scope narrow and testable in isolation.

The standard pattern for this domain is: define a Pydantic `BaseModel` with a `Literal` intent field and a `float` confidence field, then call `llm.with_structured_output(IntentResult)` to get a chain that returns a validated Pydantic object. LangChain's structured output uses the provider's tool/function-calling API under the hood to guarantee schema compliance.

Testing with zero live API calls is achieved by monkeypatching `app.agent.router.get_llm` to return a `MagicMock` whose `.with_structured_output()` side returns another mock that `.invoke()` returns a hardcoded `IntentResult` object. This is the same monkeypatch pattern already used in `test_query_router.py` for `explore_stream`.

**Primary recommendation:** Keep the router as a thin `route(question, intent_hint=None) -> IntentResult` function. Three code paths: (1) intent_hint present — return immediately without LLM, (2) LLM returns confidence >= 0.6 — return as-is, (3) confidence < 0.6 — override intent to `explain`. Write each path as a separate pytest parametrize block.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `langchain-core` | transitive via `langchain-mistralai>=0.2.0` | `BaseChatModel`, `with_structured_output` | Already in requirements; provides structured output interface |
| `langchain-mistralai` | `>=0.2.0` (pinned in requirements.txt) | `ChatMistralAI` — active LLM provider | Already installed; `get_llm()` returns this |
| `pydantic` | v2 (via `pydantic-settings>=2.0.0`) | `BaseModel`, `Field`, `Literal` type hints | Already used in `schemas.py`; project standard |
| `pytest` | existing test suite | Test runner for 12 labelled test cases | 93 V1 tests already run under pytest |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `unittest.mock.MagicMock` | stdlib | Mock `get_llm()` return value | Every test that exercises LLM path |
| `typing.Literal` | stdlib | Constrain intent field to 4 values | IntentResult model definition |
| `pydantic.Field` | pydantic v2 | Add `ge=0.0, le=1.0` validation to confidence | IntentResult model definition |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `with_structured_output` | Manual JSON prompt + `json.loads()` | Hand-rolling is fragile (model outputs malformed JSON); `with_structured_output` uses tool-calling which is schema-enforced |
| Monkeypatching `get_llm` | `FakeListChatModel` with JSON responses | `FakeListChatModel` returns strings; it does not support `with_structured_output` returning Pydantic objects. MagicMock is simpler and more direct. |
| Pure string enum `intent` | `Literal["explain", "debug", "review", "test"]` | `Literal` is the idiomatic Pydantic v2 approach; gives field-level validation and IDE completion |

**Installation:** No new packages required. All dependencies already in `backend/requirements.txt`.

---

## Architecture Patterns

### Recommended File Layout

```
backend/
├── app/
│   ├── agent/
│   │   ├── explorer.py        # V1 — do not touch
│   │   ├── prompts.py         # V1 — do not touch
│   │   └── router.py          # NEW — Phase 17
│   └── models/
│       └── schemas.py         # V1 — add IntentResult here, or keep in router.py
└── tests/
    └── test_router_agent.py   # NEW — Phase 17
```

**Decision:** Add `IntentResult` to `app/agent/router.py` directly (not `schemas.py`), keeping the router self-contained. `schemas.py` currently holds data transport models; `IntentResult` is an agent-internal type.

### Pattern 1: Pydantic Structured Output Model

**What:** A `BaseModel` subclass that LangChain fills via structured output.
**When to use:** Any time you need the LLM to return a constrained typed value.

```python
# app/agent/router.py
from typing import Literal
from pydantic import BaseModel, Field

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
```

The class docstring and field descriptions are injected into the tool-calling schema that LangChain sends to the provider. More descriptive text improves accuracy (HIGH confidence — verified in LangChain structured output docs).

### Pattern 2: Router Function with Three Paths

**What:** A single synchronous `route()` function with explicit guard clauses.
**When to use:** This is the entire router implementation.

```python
# app/agent/router.py
from langchain_core.prompts import ChatPromptTemplate
from app.config import get_settings
from app.core.model_factory import get_llm

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
_VALID_HINTS = {"explain", "debug", "review", "test"}


def route(question: str, intent_hint: str | None = None) -> IntentResult:
    """Classify question into one of four intents.

    Path 1: intent_hint provided → skip LLM, return immediately (ROUT-03)
    Path 2: LLM returns confidence >= threshold → return as-is (ROUT-01)
    Path 3: LLM returns confidence < threshold → override to 'explain' (ROUT-04)
    """
    # Path 1: hint bypass
    if intent_hint and intent_hint in _VALID_HINTS:
        return IntentResult(
            intent=intent_hint,
            confidence=1.0,
            reasoning=f"User-supplied intent_hint '{intent_hint}' used directly.",
        )

    # Path 2 + 3: LLM classification
    llm = get_llm()
    structured_llm = llm.with_structured_output(IntentResult)
    chain = ROUTER_PROMPT | structured_llm
    result: IntentResult = chain.invoke({"question": question})

    # Path 3: low-confidence fallback
    if result.confidence < CONFIDENCE_THRESHOLD:
        result = IntentResult(
            intent="explain",
            confidence=result.confidence,
            reasoning=f"Low confidence ({result.confidence:.2f}); defaulted to explain.",
        )

    return result
```

### Pattern 3: Lazy Chain Initialisation (Matching explorer.py)

The existing `explorer.py` uses a module-level `_chain = None` sentinel to avoid `ValidationError` during import when API keys are absent. Apply the same pattern if the chain is built at module level. However, since `route()` builds the chain on each call (via `get_llm()` inside the function), no lazy sentinel is needed — the chain is built only when `route()` is called.

### Anti-Patterns to Avoid

- **Calling `get_llm()` at module level:** Causes `ValidationError` on test import when `MISTRAL_API_KEY` is empty. Call `get_llm()` inside `route()` so monkeypatching in tests works.
- **Using `model_validate` / `json.loads` manually:** `with_structured_output` handles all parsing; don't duplicate it.
- **Importing from `langchain_openai`:** Not in requirements.txt. Do not add it. Router uses `get_llm()` which is provider-agnostic.
- **Mutating the returned `IntentResult` object:** Pydantic v2 models are immutable by default. Construct a new `IntentResult` for the fallback case (as shown in Pattern 2).

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON extraction from LLM response | `json.loads(response.content)` + regex | `llm.with_structured_output(IntentResult)` | LLMs produce malformed JSON; tool-calling API is schema-enforced |
| Confidence normalisation | Manual min/max clamp | `Field(ge=0.0, le=1.0)` in Pydantic | Validation is automatic and raises `ValidationError` on bad data |
| Intent enum validation | `if intent not in ["explain", ...]` guards | `Literal["explain", "debug", "review", "test"]` in Pydantic | Pydantic rejects unknown values at parse time |

**Key insight:** The LLM tool-calling layer (via `with_structured_output`) is far more reliable than text parsing. Mistral and OpenAI both support JSON schema tool calling natively; LangChain's abstraction selects the right strategy per provider.

---

## Common Pitfalls

### Pitfall 1: Module-level `get_llm()` call breaks test collection

**What goes wrong:** If `route()` module builds an LCEL chain at import time, `get_settings()` tries to read `MISTRAL_API_KEY` from env. Tests don't set this, so import fails with `ValidationError`.
**Why it happens:** `get_llm()` reads from `Settings` which tries to validate required fields.
**How to avoid:** Call `get_llm()` inside `route()`, not at module level. The `explorer.py` sentinel pattern exists for this exact reason.
**Warning signs:** `ImportError` or `ValidationError` when running `pytest` before any test runs.

### Pitfall 2: `FakeListChatModel` does not return Pydantic objects via `with_structured_output`

**What goes wrong:** Using `FakeListChatModel(responses=['{"intent": "debug", ...}'])` and expecting `with_structured_output` to return an `IntentResult` instance.
**Why it happens:** `FakeListChatModel._call()` returns a plain string; `with_structured_output` on it does NOT parse the string as structured data in the same way.
**How to avoid:** Monkeypatch `get_llm` to return a `MagicMock`. Set `.with_structured_output.return_value.invoke.return_value` to a real `IntentResult(...)` object. No string parsing required.
**Warning signs:** Test crashes with `AttributeError` or `ValidationError` on the returned value.

### Pitfall 3: Pydantic v2 model immutability

**What goes wrong:** Trying to do `result.intent = "explain"` in the fallback path.
**Why it happens:** Pydantic v2 `BaseModel` fields are immutable by default (`model_config = ConfigDict(frozen=True)` or default validation).
**How to avoid:** Construct a new `IntentResult(intent="explain", confidence=result.confidence, ...)` for the fallback. Do not mutate.
**Warning signs:** `ValidationError: X instances of Y are frozen` at runtime.

### Pitfall 4: `intent_hint` arriving as arbitrary string

**What goes wrong:** A caller passes `intent_hint="auto"` (from the extension's "Auto" option) or `intent_hint=""`, and the router incorrectly bypasses the LLM with an unknown intent value.
**Why it happens:** The bypass guard checks truthiness before validating against known intents.
**How to avoid:** Guard as `if intent_hint and intent_hint in _VALID_HINTS:` — the empty string and "auto" both fall through to the LLM path.
**Warning signs:** Tests for the LLM path fail because `intent_hint="auto"` accidentally triggered the bypass.

### Pitfall 5: Tests modify shared `lru_cache` state in `get_settings()`

**What goes wrong:** `get_settings()` is decorated with `@lru_cache`. If one test modifies env vars, later tests see the cached stale value.
**Why it happens:** `lru_cache` caches the first call result indefinitely within a process.
**How to avoid:** Clear the cache in teardown: `get_settings.cache_clear()`. Or monkeypatch at the usage site (`app.agent.router.get_llm`) rather than setting env vars.
**Warning signs:** Tests pass in isolation but fail when run together.

---

## Code Examples

Verified patterns derived from project codebase and LangChain structured output documentation:

### Mock LLM Pattern for Tests

```python
# backend/tests/test_router_agent.py
import pytest
from unittest.mock import MagicMock, patch
from app.agent.router import IntentResult, route

def _make_mock_llm(intent: str, confidence: float) -> MagicMock:
    """Return a mock get_llm() result that produces a controlled IntentResult."""
    mock_structured = MagicMock()
    mock_structured.invoke.return_value = IntentResult(
        intent=intent,
        confidence=confidence,
        reasoning="mock reasoning",
    )
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = mock_structured
    return mock_llm


@pytest.fixture
def mock_llm_factory():
    """Fixture: patch get_llm at the router module's import site."""
    with patch("app.agent.router.get_llm") as mock_factory:
        yield mock_factory
```

### 12 Labelled Test Queries (Representative Corpus)

The 12 test cases must cover all four intents (at least 2-3 per intent) plus edge cases. Representative distribution:

| # | Query | Expected Intent |
|---|-------|----------------|
| 1 | "What does the `auth_middleware` function do?" | explain |
| 2 | "Walk me through the ingestion pipeline architecture." | explain |
| 3 | "Why is the graph_rag_retrieve function slow on large repos?" | explain |
| 4 | "My service crashes with KeyError in graph_store. What's wrong?" | debug |
| 5 | "The embedder returns None for some documents. How do I debug this?" | debug |
| 6 | "Users report a NullPointerException in the walker. Trace the cause." | debug |
| 7 | "Review the query_router.py for security issues." | review |
| 8 | "Is the error handling in pipeline.py production-quality?" | review |
| 9 | "Check the explorer agent for code smells." | review |
| 10 | "Generate pytest tests for the `format_context_block` function." | test |
| 11 | "Write unit tests for the embedder with mock pgvector." | test |
| 12 | "Create test cases covering edge cases in the AST parser." | test |

These labels should be embedded directly in `test_router_agent.py` as `@pytest.mark.parametrize` data. The mock LLM must return controlled `IntentResult` objects matching these labels.

### Test Structure: Three Behaviours, One File

```python
# Pattern: each requirement maps to a distinct test class or section

# Section 1: 12 labelled queries — ROUT-01, ROUT-02
@pytest.mark.parametrize("question,expected_intent", [
    ("What does auth_middleware do?", "explain"),
    # ... 11 more entries
])
def test_labelled_queries(mock_llm_factory, question, expected_intent):
    mock_llm_factory.return_value = _make_mock_llm(expected_intent, confidence=0.9)
    result = route(question)
    assert result.intent == expected_intent
    assert 0.0 <= result.confidence <= 1.0

# Section 2: intent_hint bypass — ROUT-03
@pytest.mark.parametrize("hint", ["explain", "debug", "review", "test"])
def test_intent_hint_bypasses_llm(mock_llm_factory, hint):
    result = route("any question", intent_hint=hint)
    mock_llm_factory.assert_not_called()  # LLM never instantiated
    assert result.intent == hint
    assert result.confidence == 1.0

# Section 3: low-confidence fallback — ROUT-04
def test_low_confidence_falls_back_to_explain(mock_llm_factory):
    mock_llm_factory.return_value = _make_mock_llm("debug", confidence=0.4)
    result = route("ambiguous question")
    assert result.intent == "explain"
    assert result.confidence == 0.4  # original confidence preserved
```

### IntentResult Construction in Fallback

```python
# Correct (Pydantic v2 — construct new instance, do not mutate)
if result.confidence < CONFIDENCE_THRESHOLD:
    result = IntentResult(
        intent="explain",
        confidence=result.confidence,
        reasoning=f"Low confidence ({result.confidence:.2f}); defaulted to explain.",
    )
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual JSON parsing of LLM output | `llm.with_structured_output(PydanticModel)` | LangChain 0.1+ | Eliminates JSON parsing errors; schema is enforced by provider tool-calling |
| `FakeLLM` with string responses | `MagicMock` with Pydantic return values | Stable pattern | Simpler to construct correct typed test data; avoids parsing layer entirely |
| Global LCEL chain at module level | Lazy chain init inside function | V1 explorer pattern | Prevents import-time failures when API keys absent |

**Deprecated / outdated:**
- `PydanticOutputParser` + `OutputFixingParser`: older approach that tries to parse free-text LLM output; replaced by `with_structured_output` which uses tool-calling API.
- `LLMChain`: deprecated LangChain class, replaced by LCEL (`prompt | llm`). Project already uses LCEL.

---

## Open Questions

1. **What are the exact 12 labelled query strings?**
   - What we know: requirements say 12 labelled test cases must be in `test_router_agent.py`; intents are explain/debug/review/test
   - What's unclear: the exact query text is not specified in requirements or roadmap
   - Recommendation: Planner should define 12 queries in the plan (3 per intent suggested above); they are embedded directly in the test file as constants

2. **Should the router produce a reasoning field?**
   - What we know: ROUT-01 specifies intent + confidence score; no explicit mention of reasoning
   - What's unclear: whether downstream phases (Phase 22 orchestrator) need reasoning for audit trails
   - Recommendation: Include `reasoning: str` in `IntentResult` — it costs nothing, aids debugging, and the test spec only asserts on `intent` and `confidence`

3. **Does `intent_hint` validation live in the router or the API layer?**
   - What we know: `QueryRequest` in `schemas.py` currently has no `intent_hint` field; that extension is Phase 25
   - What's unclear: Phase 17 only builds `router.py`; the API plumbing is Phase 22-24
   - Recommendation: Router accepts `intent_hint: str | None` directly; API binding is out of scope for this phase

---

## Sources

### Primary (HIGH confidence)

- Project source: `backend/app/agent/explorer.py` — lazy chain init pattern, LCEL `prompt | llm`, `get_llm()` factory usage
- Project source: `backend/app/core/model_factory.py` — `get_llm()` implementation; how to monkeypatch it
- Project source: `backend/tests/conftest.py` — `mock_embedder` monkeypatch pattern; `sample_graph` fixture
- Project source: `backend/tests/test_query_router.py` — monkeypatch pattern for internal functions; how `_make_async_gen` mocks an async generator
- Project source: `backend/app/config.py` — `get_settings()` with `@lru_cache`; V2 fields
- [LangChain docs — structured output](https://docs.langchain.com/oss/python/langchain/structured-output) — `with_structured_output` API
- [LangChain test docs](https://docs.langchain.com/oss/python/langchain/test/unit-testing) — `GenericFakeChatModel` for mocking

### Secondary (MEDIUM confidence)

- [LangChain fake_chat_models.py on GitHub](https://github.com/langchain-ai/langchain/blob/master/libs/core/langchain_core/language_models/fake_chat_models.py) — `FakeListChatModel` returns strings, not structured objects; `GenericFakeChatModel` takes `AIMessage` iterators
- Multiple WebSearch results (2024-2025) confirming `with_structured_output` + Pydantic `Literal` as standard pattern for intent classification

### Tertiary (LOW confidence)

- WebSearch results on 12 labelled query corpus — no authoritative source; recommended queries above are suggested by researcher, not specified in project requirements

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already in requirements.txt; no new dependencies
- Architecture patterns: HIGH — matches explorer.py conventions already in codebase; structured output is well-documented LangChain API
- Test mock strategy: HIGH — MagicMock pattern confirmed by `test_query_router.py` precedent; `FakeListChatModel` limitation confirmed from source code review
- Pitfalls: HIGH — `lru_cache` / module-level import / Pydantic immutability pitfalls verified against project code
- 12 labelled queries: LOW — exact text not specified in requirements; researcher-suggested corpus

**Research date:** 2026-03-22
**Valid until:** 2026-06-22 (LangChain structured output API is stable; Pydantic v2 model pattern is stable)
