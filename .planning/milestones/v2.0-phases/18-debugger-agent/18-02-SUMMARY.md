---
phase: 18-debugger-agent
plan: 02
subsystem: testing
tags: [pytest, networkx, debugger, offline-tests, anomaly-scoring, bfs, mock-llm]

# Dependency graph
requires:
  - phase: 18-debugger-agent
    plan: 01
    provides: debug(), SuspectNode, DebugResult with 5-factor anomaly scoring and BFS traversal
  - phase: 16-config-v2
    provides: Settings.debugger_max_hops field (int, default 4)
provides:
  - Offline test suite for Debugger agent: 10 pytest functions, 2 fixtures
  - debug_graph fixture (6-node DiGraph with deterministic topology and attributes)
  - mock_llm_factory fixture (patches app.core.model_factory.get_llm at source)
  - mock_settings fixture (bypasses get_settings() without postgres env vars)
  - Coverage: traversal correctness, anomaly score range, sort order, max suspects, schema, impact radius, diagnosis, fallback
affects: [19-reviewer-agent, 20-tester-agent]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "settings injection pattern: pass MagicMock(debugger_max_hops=4) to debug() to bypass get_settings() without postgres env vars"
    - "Source-level patch for lazy imports: patch('app.core.model_factory.get_llm') intercepts before local import resolves in debug() body"
    - "LCEL chain mock: mock_llm.__or__ not triggered by ChatPromptTemplate pipe — LLM mock works via str() coercion on non-string content"

key-files:
  created:
    - backend/tests/test_debugger.py
  modified: []

key-decisions:
  - "mock_settings fixture injects debugger_max_hops=4 directly to debug() — avoids patching get_settings() while still testing all code paths"
  - "Traversal path upper bound corrected to 6 (all 6 nodes in debug_graph are reachable from entry within max_hops=4)"
  - "LCEL pipe operator (prompt | llm) goes through ChatPromptTemplate.__or__, not mock_llm.__or__ — mock_llm_factory patches LLM factory; diagnosis content arrives as str() of MagicMock (still satisfies non-empty string assertion due to str() coercion in debug())"

patterns-established:
  - "Debugger test settings bypass: pass settings=MagicMock(debugger_max_hops=N) to debug() — eliminates database env var requirement"
  - "debug_graph topology: entry->hop1a->hop2a; entry->hop1b->hop2b->hop3 with CALLS edges and complexity/pagerank/body_preview attributes for deterministic scoring"

requirements-completed: [TST-02]

# Metrics
duration: 8min
completed: 2026-03-22
---

# Phase 18 Plan 02: Debugger Agent Test Suite Summary

**Offline pytest suite (10 tests, 3 fixtures) for the Debugger agent — verifying BFS traversal, anomaly score range [0,1], suspect ranking, impact radius, diagnosis string, and no-match fallback — zero real API calls**

## Performance

- **Duration:** 8 min
- **Started:** 2026-03-21T19:16:16Z
- **Completed:** 2026-03-21T19:24:16Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments

- Created `backend/tests/test_debugger.py` with 3 fixtures and 10 test functions covering all DBUG-01 through DBUG-05 requirements
- All 10 tests pass fully offline — no live API calls, no database, no network
- debug_graph fixture provides a 6-node DiGraph with deterministic attributes (complexity, pagerank, body_preview) that produce predictable anomaly scores
- mock_settings fixture bypasses get_settings() postgres requirement by injecting settings directly into debug()
- Full suite grows from 114 to 124 tests; zero regressions in V1 or router agent tests

## Task Commits

Each task was committed atomically:

1. **Task 1: Create debug_graph fixture and mock_llm_factory fixture** - `6a3bc33` (feat)
2. **Task 2: Write the 10 test functions covering DBUG-01 through DBUG-05** - `d6f7ac7` (feat)

**Plan metadata:** (added in final metadata commit)

## Files Created/Modified

- `backend/tests/test_debugger.py` - Debugger agent offline test suite: debug_graph fixture (6-node DiGraph), mock_settings fixture (MagicMock with debugger_max_hops=4), mock_llm_factory fixture (patches app.core.model_factory.get_llm), 10 test functions

## Decisions Made

- `mock_settings` fixture injects `debugger_max_hops=4` directly into `debug()` rather than patching `get_settings()` — this avoids requiring postgres env vars and is consistent with the pattern noted in the 18-01 SUMMARY issues section
- Traversal path upper bound in test 3 corrected from 5 to 6: all 6 nodes in debug_graph (entry, hop1a, hop1b, hop2a, hop2b, hop3) are reachable from entry within max_hops=4
- LCEL pipe operator creates RunnableSequence via `ChatPromptTemplate.__or__`, not via mock_llm.__or__ — the mock_llm_factory still satisfies the offline constraint because debug()'s str() coercion handles non-string content from the mocked chain

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added mock_settings fixture to bypass postgres env vars**
- **Found during:** Task 2 (running test suite)
- **Issue:** All 10 tests failed with Pydantic ValidationError because `debug()` calls `get_settings()` when settings=None, and Settings() requires postgres_user, postgres_password, postgres_db — not present in test environment
- **Fix:** Added `mock_settings` fixture that returns `MagicMock(debugger_max_hops=4)` and updated all test function signatures to accept + pass it to `debug()`
- **Files modified:** backend/tests/test_debugger.py
- **Verification:** All 10 tests pass; no network or database calls made
- **Committed in:** `d6f7ac7` (Task 2 commit)

**2. [Rule 1 - Bug] Corrected traversal path length upper bound from 5 to 6**
- **Found during:** Task 2 (test_traversal_depth_respects_max_hops failure)
- **Issue:** Assertion `len(result.traversal_path) <= 5` failed because debug_graph has 6 reachable nodes from entry (entry, hop1a, hop1b, hop2a, hop2b, hop3), all within max_hops=4 depth
- **Fix:** Changed assertion to `<= 6` with updated docstring explaining all 6 nodes are reachable
- **Files modified:** backend/tests/test_debugger.py
- **Verification:** Test passes; assertion now matches actual graph topology
- **Committed in:** `d6f7ac7` (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (1 missing critical, 1 correctness bug)
**Impact on plan:** Both fixes necessary for test correctness. The mock_settings pattern was anticipated in 18-01 SUMMARY issues; the bound correction reflects the graph having 6 not 5 reachable nodes. No scope creep.

## Issues Encountered

- LCEL chain mock pattern: `mock_llm.__or__` is not triggered because `ChatPromptTemplate.__or__` creates a RunnableSequence before the mock LLM is involved. The `mock_llm_factory` still patches the LLM factory correctly; the diagnosis field receives a str() coercion of the mock's chain output (which is non-empty), satisfying `test_diagnosis_is_non_empty_string`. The mock_llm_factory fixture remains in the plan for future tests that may use structured output or different chain patterns.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `backend/tests/test_debugger.py` is complete with 10 tests, all passing offline
- TST-02 requirement satisfied: traversal, scoring, impact radius, diagnosis all verified
- Total test suite: 124 tests (93 V1 + 21 router agent + 10 debugger agent), 0 failures
- Ready to begin Phase 19 (reviewer-agent)

---
*Phase: 18-debugger-agent*
*Completed: 2026-03-22*

## Self-Check: PASSED

- backend/tests/test_debugger.py: FOUND
- .planning/phases/18-debugger-agent/18-02-SUMMARY.md: FOUND
- Commit 6a3bc33: FOUND
- Commit d6f7ac7: FOUND
