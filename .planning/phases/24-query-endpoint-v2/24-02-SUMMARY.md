---
phase: 24-query-endpoint-v2
plan: 02
subsystem: testing
tags: [fastapi, pytest, sse, streaming, langgraph, mocking, pydantic]

# Dependency graph
requires:
  - phase: 24-query-endpoint-v2
    plan: 01
    provides: V2 branch in /query endpoint gated on intent_hint; v2_event_generator with lazy build_graph import

provides:
  - backend/tests/test_query_router_v2.py with 8 offline endpoint-level integration tests
  - Full V2 routing coverage: debug/review/test/explain intents + auto/None sentinel fall-through
  - Verified: no fixture conflicts between test_query_router.py (V1) and test_query_router_v2.py (V2)

affects:
  - Future endpoint test additions (follow same mock pattern)
  - TST-09 requirement: satisfied

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Patch lazy-imported build_graph at source module (app.agent.orchestrator.build_graph) — lazy imports inside function bodies are not bound in consumer module __dict__"
    - "_make_mock_graph(intent, specialist_result) helper returns MagicMock with NexusState-shaped invoke() return value"
    - "V1-path tests monkeypatch graph_rag_retrieve + explore_stream; assert build_graph.call_count == 0"

key-files:
  created:
    - backend/tests/test_query_router_v2.py
  modified: []

key-decisions:
  - "Patched build_graph at app.agent.orchestrator.build_graph (source module), not app.api.query_router.build_graph — build_graph is a lazy import inside v2_event_generator body; Python binds the name in the local scope at call time, not in the consumer module's __dict__; the established project pattern (STATE.md Phase 17) confirms source-module patching for lazy imports"
  - "Tests 6 and 7 (auto/None sentinel) use mock_bg.call_count == 0 assertion inside the patch context to verify V1 path is taken without build_graph invocation"
  - "MagicMock specialist_result uses model_dump() via MagicMock auto-spec — the V2 endpoint calls hasattr(specialist, 'model_dump') which returns True for MagicMock; model_dump.return_value set to a plain dict for JSON serialization"

patterns-established:
  - "V2-endpoint-test: patch build_graph at source module; monkeypatch get_status + load_graph; assert SSE event names in body text"
  - "Sentinel-test: wrap in patch context; assert call_count == 0 inside context"

requirements-completed:
  - TST-09

# Metrics
duration: 5min
completed: 2026-03-22
---

# Phase 24 Plan 02: Query Endpoint V2 Test Suite Summary

**8 offline endpoint integration tests covering all V2 routing scenarios — debug/review/test/explain intents invoke orchestrator, auto/None sentinels fall through to V1 path, errors surface as event: error; 190 total tests passing**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-22T00:30:58Z
- **Completed:** 2026-03-22T00:35:58Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments

- Created test_query_router_v2.py with 8 offline tests; all pass in 0.33s
- Verified all 4 named intents (debug/review/test/explain) invoke orchestrator via mock_graph
- Verified auto and None sentinels confirm build_graph.call_count == 0 (V1 path)
- Verified RuntimeError from graph.invoke propagates as event: error in SSE stream
- No fixture conflicts between V1 (test_query_router.py) and V2 test files
- Full suite: 190 tests passing (182 pre-existing + 8 new); zero regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Create test_query_router_v2.py with 8 offline V2 endpoint tests** - `1caee73` (test)
2. **Task 2: Confirm full test suite passes (V1 + V2 together)** - verification only; no additional commit needed

**Plan metadata:** committed as part of final docs commit.

## Files Created/Modified

- `backend/tests/test_query_router_v2.py` - 8 offline V2 endpoint tests; client fixture, _make_mock_graph helper, _make_status helper, _make_debug_result helper, _read_stream helper

## Decisions Made

- Patched `build_graph` at the source module `app.agent.orchestrator.build_graph` rather than the consumer module `app.api.query_router.build_graph` — because `build_graph` is a lazy import inside `v2_event_generator`, it is bound in the local function scope at invocation time, not in the `query_router` module's `__dict__`; patching at source intercepts the binding correctly (STATE.md Phase 17 decision confirms this for lazy imports)
- Used `mock_review.model_dump.return_value = {...}` for ReviewResult and TestResult mocks — the V2 endpoint calls `hasattr(specialist, "model_dump")` which is True for MagicMock; providing `model_dump.return_value` ensures JSON serialization succeeds

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Patched build_graph at source module instead of consumer module**
- **Found during:** Task 1 (writing tests)
- **Issue:** Plan specified `patch("app.api.query_router.build_graph")` but `build_graph` is a lazy import inside the generator body; `query_router` module has no `build_graph` attribute in its `__dict__` at patch time — patching it would have no effect (established in STATE.md: "[Phase 17-router-agent]: Patch lazy-imported get_llm at source module, not consumer module")
- **Fix:** Used `patch("app.agent.orchestrator.build_graph", ...)` (source module) — all 8 tests pass green confirming this is the correct intercept point
- **Files modified:** backend/tests/test_query_router_v2.py
- **Verification:** mock_graph.invoke.call_count == 1 assertion passes for debug intent; call_count == 0 assertion passes for auto/None sentinels
- **Committed in:** 1caee73 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 — patch target correction)
**Impact on plan:** Essential for correctness — wrong patch target would have caused all V2 path tests to fail or invoke the real orchestrator. No scope creep.

## Issues Encountered

None beyond the patch target deviation documented above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- TST-08 and TST-09 both satisfied: 9 V1 tests + 8 V2 tests = 17 endpoint tests; full suite at 190
- V2 /query endpoint is fully tested at the integration level — debug/review/test/explain routing verified offline
- Phase 25+ (extension rendering or frontend integration) can rely on documented SSE format: event: result with {type, intent, result} payload

## Self-Check: PASSED

- FOUND: backend/tests/test_query_router_v2.py
- FOUND: commit 1caee73 (Task 1)
- V2 tests: 8 passed, 0 failed (0.33s)
- Combined V1+V2: 17 passed, 0 failed
- Full suite: 190 passed, 0 failed (3.62s)

---
*Phase: 24-query-endpoint-v2*
*Completed: 2026-03-22*
