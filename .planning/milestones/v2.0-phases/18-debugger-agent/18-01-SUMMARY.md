---
phase: 18-debugger-agent
plan: 01
subsystem: api
tags: [networkx, pydantic, langchain, bfs, call-graph, anomaly-scoring, debugger]

# Dependency graph
requires:
  - phase: 16-config-v2
    provides: Settings with debugger_max_hops field (int, default 4)
  - phase: 17-router-agent
    provides: get_llm() factory pattern (lazy import inside function body)
provides:
  - SuspectNode Pydantic model with anomaly_score Field(ge=0.0, le=1.0) enforcement
  - DebugResult Pydantic model (suspects, traversal_path, impact_radius, diagnosis)
  - debug(question, G, settings=None) -> DebugResult public API
  - _forward_bfs() BFS traversal along CALLS edges up to max_hops
  - _find_entry_nodes() function name matching from bug description
  - _score_node() deterministic 5-factor anomaly scoring formula
  - _impact_radius() direct caller computation for top suspect
affects: [19-reviewer-agent, 20-tester-agent, 25-orchestrator, 26-api-integration]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Lazy import pattern: get_llm() and get_settings() imported inside debug() body, never at module level"
    - "5-factor deterministic scoring: weights 0.30/0.25/0.20/0.15/0.10 summing to 1.0, each factor clamped before weighting"
    - "BFS with CALLS-edge filtering: G.edges[u,v].get('type') == 'CALLS' guards against edges without type attribute"
    - "Entry node fallback: when no function name matches, use highest in_degree node (most-called)"
    - "str() coercion on LLM content: isinstance check before Pydantic model construction"

key-files:
  created:
    - backend/app/agent/debugger.py
  modified: []

key-decisions:
  - "Anomaly score weights: 0.30 complexity / 0.25 error-handling absence / 0.20 keyword match / 0.15 out-degree / 0.10 inverted PageRank — higher-complexity, error-unguarded, query-matching, highly-coupled, low-centrality nodes score highest"
  - "Fallback to highest in_degree node (most-called) rather than highest PageRank node, per plan spec — most-called function is the most likely integration point for a bug"
  - "str() coercion on diagnosis field: isinstance(raw_content, str) guard prevents Pydantic ValidationError when LLM response wraps content in non-string mock types"
  - "Lazy import for both get_settings and get_llm: consistent with router.py pattern established in Phase 17; prevents ValidationError during pytest collection without API keys"

patterns-established:
  - "Debugger agent lazy import: both get_settings() and get_llm() imported inside debug() body — never at module level"
  - "CALLS-edge guard: always use G.edges[u,v].get('type') == 'CALLS' (not G.edges[u,v]['type']) to avoid KeyError on edges without type attribute"
  - "BFS includes entry node at depth 0 so isolated entry nodes still appear as suspects"

requirements-completed: [DBUG-01, DBUG-02, DBUG-03, DBUG-04, DBUG-05]

# Metrics
duration: 4min
completed: 2026-03-22
---

# Phase 18 Plan 01: Debugger Agent Summary

**Graph-traversal Debugger agent using 5-factor anomaly scoring (weights 0.30/0.25/0.20/0.15/0.10) with BFS forward from function-name entry points, top-5 suspect ranking, and LLM-grounded diagnosis narrative**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-21T19:08:33Z
- **Completed:** 2026-03-21T19:12:33Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments

- Implemented complete `backend/app/agent/debugger.py` exporting `SuspectNode`, `DebugResult`, and `debug()`
- Deterministic 5-factor anomaly scoring formula with individually-clamped factors (complexity, error absence, keyword match, out-degree, inverted PageRank)
- BFS forward traversal along CALLS-typed edges with entry-node fallback (highest in_degree) when no function name matches the bug description
- Impact radius computation (direct callers via CALLS edges of top suspect)
- LLM diagnosis narrative grounded in traversal function names only (anti-hallucination constraint via DEBUGGER_SYSTEM prompt)
- All 114 tests pass (93 V1 + 21 router agent), zero regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Pydantic models and helper functions** - `fb1ff1d` (feat)
2. **Task 2: debug() public function** - `69e595f` (feat)

**Plan metadata:** (added in final metadata commit)

## Files Created/Modified

- `backend/app/agent/debugger.py` - Debugger agent module: SuspectNode, DebugResult models, debug() function, _forward_bfs(), _find_entry_nodes(), _score_node(), _build_reasoning(), _impact_radius()

## Decisions Made

- Anomaly score weights chosen: 0.30 complexity, 0.25 error-handling absence, 0.20 keyword match, 0.15 out-degree coupling, 0.10 inverted PageRank — emphasizes complex, unguarded, query-relevant, highly-coupled nodes
- Entry node fallback uses highest `in_degree` (most-called) rather than highest PageRank, per plan specification
- `str()` coercion applied to `diagnosis` field after `isinstance(raw_content, str)` check to prevent Pydantic `ValidationError` when LLM returns non-string types
- Lazy import pattern for both `get_settings` and `get_llm` inside `debug()` body, consistent with Phase 17 router.py pattern

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] str() coercion guard on diagnosis extraction**
- **Found during:** Task 2 (debug() function smoke testing)
- **Issue:** `response.content if hasattr(response, "content") else str(response)` could return a non-string value (e.g., a MagicMock object when `hasattr` returns True but `.content` is not a str), causing Pydantic `ValidationError: Input should be a valid string`
- **Fix:** Added `isinstance(raw_content, str)` check before assigning to `diagnosis`; applied `str()` coercion as fallback: `diagnosis = raw_content if isinstance(raw_content, str) else str(raw_content)`
- **Files modified:** backend/app/agent/debugger.py
- **Verification:** Smoke test passes with `mock_llm.__or__` mock pattern (the plan's prescribed test approach)
- **Committed in:** `69e595f` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 correctness bug)
**Impact on plan:** Auto-fix necessary for correctness — Pydantic's string type enforcement would reject non-string diagnosis values at runtime. No scope creep.

## Issues Encountered

- Plan's Task 2 smoke test does not patch `get_settings()`, which requires postgres env vars not present in this environment. Verified functionally by patching `app.config.get_settings` in addition to `app.core.model_factory.get_llm`. The `debug()` function's `settings` parameter injection also allows bypassing `get_settings()` in tests entirely — the future test suite for Phase 18 should use this pattern (consistent with how router agent tests work).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `backend/app/agent/debugger.py` is complete and importable without API keys
- `SuspectNode`, `DebugResult`, and `debug()` are ready for orchestrator integration (Phase 25)
- The `settings.debugger_max_hops` field (default 4) is live in `app.config.Settings`
- V1 test suite (93 tests) and router agent tests (21 tests) remain green — zero regressions
- Ready to begin Phase 19 (reviewer-agent)

---
*Phase: 18-debugger-agent*
*Completed: 2026-03-22*

## Self-Check: PASSED

- backend/app/agent/debugger.py: FOUND
- .planning/phases/18-debugger-agent/18-01-SUMMARY.md: FOUND
- Commit fb1ff1d: FOUND
- Commit 69e595f: FOUND
