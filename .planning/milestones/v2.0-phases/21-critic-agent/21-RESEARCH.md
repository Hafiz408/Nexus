# Phase 21: critic-agent - Research

**Researched:** 2026-03-22
**Domain:** Quality-gate agent — deterministic scoring, retry routing, hard loop cap
**Confidence:** HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| CRIT-01 | Critic scores every specialist output on groundedness (citation accuracy), relevance, and actionability; produces overall weighted score (0.4×G + 0.35×R + 0.25×A) | Scoring formula is pure arithmetic — no LLM needed; inputs come from specialist result fields |
| CRIT-02 | When overall score < 0.7 and loops < 2, critic routes back to source agent with specific feedback | Loop count tracked in caller (orchestrator state); critic receives it and returns a routing decision |
| CRIT-03 | After 2 retry loops, critic forces max_loops path regardless of score (hard cap — never infinite) | `loop_count >= max_critic_loops` check gates the pass-through; config provides the constant |
| CRIT-04 | Groundedness is pre-computed from cited node IDs vs. retrieved_nodes set (not LLM-estimated) | `retrieved_nodes` is a `list[str]` on every specialist result; intersection math gives the score |
| TST-05 | test_critic.py — groundedness math; retry routing; loop cap; feedback cleared on pass | All tests are pure unit tests: no LLM, no graph, no DB |
</phase_requirements>

---

## Summary

The Critic agent is a deterministic quality gate that wraps each specialist agent's output (Debugger, Reviewer, Tester) and decides whether to accept it or send it back for another attempt. Unlike the three specialist agents, the Critic makes **no LLM calls at all** — every computation is arithmetic or set-intersection. This makes it the simplest agent to implement and test in the V2 pipeline.

The central design constraint is the hard loop cap: `max_critic_loops = 2` is read from `Settings` (already wired in `config.py`). The Critic compares `loop_count` (passed in at call time) against this constant. If `loop_count >= 2`, the result is accepted unconditionally regardless of score. If `loop_count < 2` and `score < 0.7`, the Critic returns a reject decision with written feedback targeting the weakest sub-score. Otherwise (score >= 0.7), it accepts and the feedback field is `None`.

**Primary recommendation:** Implement `CriticResult` (Pydantic model) + `critique()` (pure function with lazy `get_settings()` import) following the exact same module shape as the three preceding agents. No LLM import is needed — this simplifies the mock surface in tests to `get_settings()` only.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pydantic | (project version) | `CriticResult` output model with typed fields | Every specialist agent uses Pydantic models — consistency required |
| networkx | (project version) | Not used directly by Critic — inherited graph is not needed | Specialist results carry pre-computed `retrieved_nodes` lists |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `app.config.get_settings` | project | Read `max_critic_loops` and `critic_threshold` | Lazy-imported inside `critique()` body — same pattern as all other agents |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Deterministic scoring | LLM-estimated relevance/actionability | LLM adds latency, cost, test complexity, and non-determinism — CRIT-04 explicitly forbids it for groundedness |

**Installation:** No new dependencies required. All imports are already in the project.

---

## Architecture Patterns

### Recommended Project Structure
```
backend/app/agent/
├── router.py        # Phase 17 - complete
├── debugger.py      # Phase 18 - complete
├── reviewer.py      # Phase 19 - complete
├── tester.py        # Phase 20 - complete
└── critic.py        # Phase 21 - NEW

backend/tests/
└── test_critic.py   # Phase 21 - NEW
```

### Pattern 1: Module Shape — Mirror Preceding Agents

**What:** Every agent module in this project has the same layout: constants at top (safe at import time), Pydantic output models, private helpers, then public API function with lazy imports inside the function body.

**When to use:** Always — this is the locked project convention.

```python
# critic.py skeleton
"""Critic Agent — deterministic quality gate for the V2 multi-agent pipeline.

Exposes:
  - CriticResult  Pydantic model (score, groundedness, relevance, actionability,
                  passed, feedback, loop_count)
  - critique(result, loop_count, settings=None) -> CriticResult

Algorithm:
  1. Compute groundedness: len(cited_nodes & retrieved_nodes) / max(len(cited_nodes), 1)
  2. Score relevance and actionability from specialist result content heuristics.
  3. Weighted score = 0.4*G + 0.35*R + 0.25*A
  4. If loop_count >= max_critic_loops: pass unconditionally (hard cap).
  5. If score < critic_threshold and loop_count < max_critic_loops: reject with feedback.
  6. Else: pass, feedback=None.

Critical: get_settings() is imported INSIDE critique() body — never at module level.
"""
from __future__ import annotations
from pydantic import BaseModel, Field

# --- Pydantic output model ---

class CriticResult(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    groundedness: float = Field(ge=0.0, le=1.0)
    relevance: float = Field(ge=0.0, le=1.0)
    actionability: float = Field(ge=0.0, le=1.0)
    passed: bool
    feedback: str | None   # None when passed=True; written critique when passed=False
    loop_count: int

# --- Public API ---

def critique(result, loop_count: int, settings=None) -> CriticResult:
    if settings is None:
        from app.config import get_settings  # noqa: PLC0415
        settings = get_settings()
    ...
```

### Pattern 2: Groundedness Computation — Set Intersection (CRIT-04)

**What:** Groundedness is the fraction of cited node IDs that appear in the specialist's `retrieved_nodes` set. "Cited nodes" are those the specialist explicitly referenced (node IDs embedded in findings, suspects, or test mock targets).

**When to use:** Computing the G sub-score for every specialist type.

```python
# Source: CRIT-04 requirement + reviewer.py / debugger.py retrieved_nodes field
def _compute_groundedness(cited_nodes: set[str], retrieved_nodes: list[str]) -> float:
    """Fraction of cited nodes that are in the retrieved set.

    cited_nodes  — node IDs the specialist actually mentioned in its output.
    retrieved_nodes — node IDs the specialist fetched from the graph.
    Returns 1.0 when cited_nodes is empty (nothing to cite = fully grounded).
    """
    if not cited_nodes:
        return 1.0
    retrieved_set = set(retrieved_nodes)
    matched = len(cited_nodes & retrieved_set)
    return matched / len(cited_nodes)
```

**Extraction of cited_nodes per specialist type:**
- `DebugResult`: `{s.node_id for s in result.suspects}`
- `ReviewResult`: `{f.file_path for f in result.findings}` — note: file_path strings, not node_ids; must match against node file_paths in retrieved set OR use the reviewer's own post-filter guarantee (findings already grounded). Simplest approach: treat cited as `{f.file_path for f in result.findings}`, retrieved as `{G.nodes[n].get("file_path","") for n in result.retrieved_nodes}`. However, since reviewer already post-filters, groundedness will always be 1.0 for ReviewResult — which is correct behaviour.
- `TestResult`: No node citations in output — treat groundedness as 1.0, or derive from mock target names vs callee set.

**Recommended simplification:** The `critique()` function accepts a union type or a typed protocol. The simplest approach matching the codebase style is to accept `Any` and inspect the object for known fields:

```python
from typing import Union
from app.agent.debugger import DebugResult
from app.agent.reviewer import ReviewResult
from app.agent.tester import TestResult

SpecialistResult = Union[DebugResult, ReviewResult, TestResult]
```

This keeps imports inside `critique()` body (lazy) to avoid circular import and test-time ValidationError risks.

### Pattern 3: Scoring Formula — Pure Arithmetic (CRIT-01)

```python
# Weights are locked by CRIT-01 — do not change
WEIGHT_GROUNDEDNESS = 0.40
WEIGHT_RELEVANCE    = 0.35
WEIGHT_ACTIONABILITY = 0.25

def _weighted_score(g: float, r: float, a: float) -> float:
    score = WEIGHT_GROUNDEDNESS * g + WEIGHT_RELEVANCE * r + WEIGHT_ACTIONABILITY * a
    return round(min(max(score, 0.0), 1.0), 4)
```

### Pattern 4: Hard Loop Cap — Compare Before Scoring (CRIT-03)

The cap must be checked BEFORE evaluating the score. This guarantees the third+ call never triggers a retry even if the score would be below threshold.

```python
def critique(result, loop_count: int, settings=None) -> CriticResult:
    if settings is None:
        from app.config import get_settings  # noqa: PLC0415
        settings = get_settings()

    max_loops: int = settings.max_critic_loops      # default 2
    threshold: float = settings.critic_threshold    # default 0.7

    g = _compute_groundedness(...)
    r = _compute_relevance(result)
    a = _compute_actionability(result)
    score = _weighted_score(g, r, a)

    # Hard cap — accept unconditionally on loop 2+ (CRIT-03)
    if loop_count >= max_loops:
        return CriticResult(score=score, groundedness=g, relevance=r,
                            actionability=a, passed=True, feedback=None,
                            loop_count=loop_count)

    # Quality gate — reject if below threshold (CRIT-02)
    if score < threshold:
        feedback = _generate_feedback(g, r, a, score)
        return CriticResult(score=score, groundedness=g, relevance=r,
                            actionability=a, passed=False, feedback=feedback,
                            loop_count=loop_count)

    # Pass
    return CriticResult(score=score, groundedness=g, relevance=r,
                        actionability=a, passed=True, feedback=None,
                        loop_count=loop_count)
```

### Pattern 5: Relevance and Actionability Heuristics

Since no extra LLM call is allowed (CRIT-04 forbids it), R and A must be computed from structural properties of the specialist output:

**Relevance (R) heuristics (confidence: MEDIUM — design choices, verify with team):**
- `DebugResult`: `len(suspects) > 0` → base relevance; non-empty `diagnosis` string adds to score
- `ReviewResult`: `len(findings) > 0` → base relevance; non-empty `summary` adds
- `TestResult`: non-empty `test_code` containing `def test_` → base relevance

Suggested formula: `R = min(content_present_score, 1.0)` where content_present_score rewards having substantive output (at least one finding/suspect/test function).

**Actionability (A) heuristics:**
- `DebugResult`: each `SuspectNode` has `file_path` and `line_start` — presence of these = actionable; `len(suspects) / 5` as ratio
- `ReviewResult`: each `Finding` has `suggestion` field (non-empty string) — `sum(1 for f in findings if f.suggestion) / max(len(findings), 1)`
- `TestResult`: `test_code` has runnable test functions — count of `def test_` / expected min (3)

**Important:** The exact heuristics for R and A are not locked by requirements. The REQUIREMENTS only lock the formula weights (0.4/0.35/0.25) and the threshold (0.7). Implement reasonable structural heuristics that produce sensible scores and are fully deterministic.

### Pattern 6: Feedback Generation — Written, Targeted (CRIT-02)

When the Critic rejects, it must provide written feedback to the specialist. The feedback should identify the weakest sub-score:

```python
def _generate_feedback(g: float, r: float, a: float, score: float) -> str:
    parts = []
    if g < 0.5:
        parts.append(f"Groundedness is low ({g:.2f}): cited nodes not found in retrieved context. "
                     "Reference only functions/files that were part of the graph traversal.")
    if r < 0.5:
        parts.append(f"Relevance is low ({r:.2f}): response lacks substantive findings. "
                     "Ensure the output directly addresses the query with specific findings.")
    if a < 0.5:
        parts.append(f"Actionability is low ({a:.2f}): findings lack concrete details. "
                     "Include file paths, line numbers, and specific suggestions.")
    if not parts:
        parts.append(f"Overall score ({score:.2f}) is below threshold. "
                     "Improve specificity and coverage of findings.")
    return " | ".join(parts)
```

### Anti-Patterns to Avoid

- **Importing get_llm at module level:** No LLM is needed at all for Critic, but get_settings() must still be lazy-imported inside critique() body — same reason as all other agents (test-time ValidationError on postgres env vars).
- **Importing specialist result types at module level in critic.py:** This could create circular import chains if orchestrator later imports both. Use `from __future__ import annotations` and type as strings, or keep specialist imports lazy inside the function body.
- **Checking loop cap AFTER scoring decision:** The cap must be unconditional — score is still computed and returned for observability, but the routing decision ignores it when `loop_count >= max_loops`.
- **feedback=None vs feedback="" on reject:** Use `None` for pass (TST-05 verifies "feedback cleared on pass"), use a non-empty string on reject. Never return `feedback=""` on reject.
- **loop_count starting at 0 vs 1:** Confirm with orchestrator phase (Phase 22) what value is passed on the first critique call. Research assumption: `loop_count=0` on first call, `loop_count=1` on first retry, `loop_count=2` triggers the hard cap (>= max_critic_loops=2).

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Weighted score clamping | Custom clamp logic | `min(max(score, 0.0), 1.0)` | One-liner; over-engineering risks float precision bugs |
| Pydantic validation | Manual field validation | `Field(ge=0.0, le=1.0)` | Pydantic enforces bounds at construction time |
| Settings loading | Env var parsing | `get_settings()` lazy import | Already wired in config.py with lru_cache |

**Key insight:** The Critic's entire value is in being the simplest component — it is intentionally a pure function. Any complexity added (LLM calls, graph traversal) defeats the purpose and violates CRIT-04.

---

## Common Pitfalls

### Pitfall 1: Circular Import from Specialist Result Types

**What goes wrong:** `critic.py` imports `DebugResult`, `ReviewResult`, `TestResult` at module level; later phases import all of these together and hit a circular dependency.

**Why it happens:** Python resolves module-level imports at collection time. If the orchestrator imports `critic` which imports `debugger`, and `debugger` imports something from the orchestrator package, the cycle breaks.

**How to avoid:** Keep specialist result type imports inside `critique()` body (lazy), or use `TYPE_CHECKING` guard with string annotations (`from __future__ import annotations`).

**Warning signs:** `ImportError: cannot import name X` or `partially initialized module` errors during pytest collection.

### Pitfall 2: Groundedness Denominator = 0

**What goes wrong:** `_compute_groundedness` divides by `len(cited_nodes)`. If the specialist returns no cited nodes (e.g., empty suspects list or zero findings), division by zero occurs.

**How to avoid:** Return `1.0` when `cited_nodes` is empty — nothing was cited, nothing was wrong.

### Pitfall 3: Mock Pattern Mismatch in Tests

**What goes wrong:** `critique()` does NOT call LLM, so the `mock_llm_factory` fixture from other test files is irrelevant. Tests that accidentally include it will pass spuriously. Tests that try to patch `get_llm` for the Critic will find nothing to patch.

**How to avoid:** The `test_critic.py` mock surface is only `get_settings()` (if settings is not injected directly). Prefer injecting `mock_settings` directly into `critique(settings=mock_settings)` to eliminate even that patch.

**Warning signs:** Tests pass with incorrect mock setup — the function never calls LLM so a broken LLM mock does not cause failures.

### Pitfall 4: Loop Count Semantics Mismatch with Orchestrator

**What goes wrong:** Orchestrator (Phase 22) tracks loop_count with different start value (e.g., 1-indexed instead of 0-indexed), causing the hard cap to trigger one iteration early or late.

**How to avoid:** Document the expected semantics explicitly in the module docstring. Recommended: `loop_count=0` on first critique call (no retries yet), cap triggers when `loop_count >= 2`.

**Warning signs:** Integration tests in Phase 22 show the specialist is called 3 times instead of 2, or accepted on first failure.

### Pitfall 5: score and loop_count Always Present in CriticResult

**What goes wrong:** Callers (orchestrator) read `result.score` for logging/observability even when `passed=True`. If score is omitted from the result model or not computed when capping, downstream breaks.

**How to avoid:** Always compute and return all four fields (`score`, `groundedness`, `relevance`, `actionability`) regardless of routing decision. The cap path still computes the score — it just ignores it for routing.

---

## Code Examples

### CriticResult Model

```python
# Based on established Pydantic patterns in this codebase (reviewer.py, debugger.py)
class CriticResult(BaseModel):
    """Quality gate result from a single critique() call."""

    score: float = Field(ge=0.0, le=1.0)          # weighted composite: 0.4G + 0.35R + 0.25A
    groundedness: float = Field(ge=0.0, le=1.0)   # fraction of cited nodes in retrieved set
    relevance: float = Field(ge=0.0, le=1.0)      # structural content quality
    actionability: float = Field(ge=0.0, le=1.0)  # specificity of output (file:line, suggestions)
    passed: bool                                    # True = accept; False = route back
    feedback: str | None                           # None when passed=True; critique text otherwise
    loop_count: int                                # loop_count value at time of this critique
```

### Test Fixture Pattern — Settings Only (no LLM mock needed)

```python
# test_critic.py — follows the mock_settings pattern from test_tester.py
@pytest.fixture
def mock_settings():
    """Settings stub with critic knobs injected directly."""
    settings = MagicMock()
    settings.max_critic_loops = 2
    settings.critic_threshold = 0.7
    return settings
```

### Test: Scoring Formula Arithmetic (CRIT-01)

```python
def test_scoring_formula_weights(mock_settings):
    """0.4*G + 0.35*R + 0.25*A produces correct composite score."""
    # Inject a trivial specialist result with known sub-scores
    result = make_debug_result(node_ids=["a"], retrieved=["a"])  # G=1.0
    critic_result = critique(result, loop_count=0, settings=mock_settings)
    expected = round(0.4 * critic_result.groundedness
                     + 0.35 * critic_result.relevance
                     + 0.25 * critic_result.actionability, 4)
    assert abs(critic_result.score - expected) < 1e-6
```

### Test: Retry Routing (CRIT-02)

```python
def test_retry_routing_on_low_score(mock_settings):
    """score < 0.7 and loop_count=0 → passed=False and feedback is non-empty string."""
    mock_settings.critic_threshold = 0.7
    result = make_debug_result(node_ids=["x"], retrieved=[])  # G=0.0 → low score
    critic_result = critique(result, loop_count=0, settings=mock_settings)
    assert critic_result.passed is False
    assert isinstance(critic_result.feedback, str)
    assert len(critic_result.feedback) > 0
```

### Test: Hard Cap (CRIT-03)

```python
def test_hard_cap_at_two_loops(mock_settings):
    """loop_count >= 2 forces passed=True regardless of score."""
    mock_settings.max_critic_loops = 2
    result = make_debug_result(node_ids=["x"], retrieved=[])  # G=0.0 → would fail
    critic_result = critique(result, loop_count=2, settings=mock_settings)
    assert critic_result.passed is True  # cap overrides score

def test_no_third_loop(mock_settings):
    """loop_count=1 with low score → still rejected (cap is at 2, not 1)."""
    result = make_debug_result(node_ids=["x"], retrieved=[])
    critic_result = critique(result, loop_count=1, settings=mock_settings)
    assert critic_result.passed is False
```

### Test: Feedback Cleared on Pass (TST-05)

```python
def test_feedback_none_on_pass(mock_settings):
    """When passed=True, feedback must be None (not empty string)."""
    result = make_debug_result(node_ids=["a"], retrieved=["a"])  # guaranteed high score
    mock_settings.critic_threshold = 0.0   # force pass for isolation
    critic_result = critique(result, loop_count=0, settings=mock_settings)
    assert critic_result.passed is True
    assert critic_result.feedback is None
```

---

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| LLM self-evaluation for quality scoring | Deterministic formula from structural properties | No extra API cost, fully testable, reproducible |
| Infinite retry loops in LLM pipelines | Hard loop cap (max_critic_loops=2) | Production safety, bounded latency |
| Per-call re-evaluation of previous scores | Fresh score per critique() call, loop_count tracked externally | Stateless critic; orchestrator owns loop state |

---

## Open Questions

1. **Cited node extraction for TestResult**
   - What we know: `TestResult` has `test_code` (string) and `framework` (string) — no `retrieved_nodes` field, no structured node references.
   - What's unclear: Should the Critic compute groundedness differently for TestResult vs DebugResult/ReviewResult?
   - Recommendation: For TestResult, default groundedness to `1.0` (the tester agent's mock target enumeration is already deterministic from graph CALLS edges — the output cannot hallucinate node references). Document this per-type behaviour in the module docstring.

2. **Relevance/Actionability formula precision**
   - What we know: CRIT-01 locks weights but not the heuristics for R and A.
   - What's unclear: Test suite (TST-05) must verify "scoring formula" — does this mean only the weights, or also the sub-score heuristics?
   - Recommendation: Design sub-score heuristics first, document them as constants in the module, then write tests that verify the complete path (known input → expected sub-score → expected composite). This makes TST-05 deterministic and specification-complete.

3. **Type annotation for the `result` parameter**
   - What we know: `critique()` will receive `DebugResult | ReviewResult | TestResult`.
   - Recommendation: Use `Union` type alias (`SpecialistResult`) defined at module level using string annotations to avoid import-time cost. Alternatively, accept `Any` and use `isinstance` checks inside helper functions.

---

## Sources

### Primary (HIGH confidence)
- `backend/app/config.py` — `max_critic_loops=2`, `critic_threshold=0.7` confirmed present and typed correctly
- `backend/app/agent/reviewer.py` — `ReviewResult.retrieved_nodes: list[str]` shape confirmed
- `backend/app/agent/debugger.py` — `DebugResult.suspects: list[SuspectNode]` with `node_id` confirmed; `retrieved_nodes` is NOT on `DebugResult` directly — traversal_path is the closest analogue
- `backend/app/agent/tester.py` — `TestResult` has no `retrieved_nodes` field confirmed
- `.planning/REQUIREMENTS.md` — CRIT-01 through CRIT-04, TST-05 requirements text confirmed
- `.planning/STATE.md` — lazy import convention, mock patterns, loop cap decisions confirmed
- `backend/tests/test_reviewer.py` — mock_settings / mock_llm_factory fixture patterns confirmed
- `backend/tests/test_tester.py` — source-level patch pattern, alias import convention confirmed
- `backend/tests/conftest.py` — shared fixtures, graph topology conventions confirmed

### Secondary (MEDIUM confidence)
- Design of relevance/actionability heuristics — inferred from specialist output model shapes; no external source needed since this is internal to the project

---

## Critical Implementation Note: DebugResult Has No retrieved_nodes

**This is the most important finding from reading the actual code.**

`DebugResult` (debugger.py) does NOT have a `retrieved_nodes` field. It has:
- `suspects: list[SuspectNode]` — each with `node_id`
- `traversal_path: list[str]` — node_ids visited in BFS order
- `impact_radius: list[str]` — direct callers of top suspect
- `diagnosis: str`

The `retrieved_nodes` field exists only on `ReviewResult`. For Critic groundedness computation:

| Specialist | "retrieved_nodes" analogue | "cited_nodes" analogue |
|-----------|---------------------------|------------------------|
| `ReviewResult` | `result.retrieved_nodes` (explicit field) | `{f.file_path for f in result.findings}` |
| `DebugResult` | `result.traversal_path` (BFS-visited node_ids) | `{s.node_id for s in result.suspects}` |
| `TestResult` | none (no graph traversal recorded) | none → groundedness = 1.0 |

The `critique()` function must dispatch on result type using `isinstance` checks or duck-typing to extract the correct fields. This is a design decision that does not require external research — the model shapes are fully known from the codebase.

---

## Metadata

**Confidence breakdown:**
- CriticResult model design: HIGH — derived directly from CRIT-01 requirements and Pydantic patterns throughout codebase
- Scoring formula implementation: HIGH — formula is mathematically specified (0.4G + 0.35R + 0.25A)
- Groundedness computation: HIGH — CRIT-04 explicitly specifies set-intersection approach; specialist model fields verified
- R/A heuristics: MEDIUM — requirements do not specify exact heuristics; structural approach is well-motivated but implementation detail
- Test patterns: HIGH — test_reviewer.py and test_tester.py provide exact templates to follow
- Loop cap logic: HIGH — config.py, STATE.md, and REQUIREMENTS.md all confirm the semantics

**Research date:** 2026-03-22
**Valid until:** 2026-04-22 (stable domain — pure internal code, no external library dependency)
