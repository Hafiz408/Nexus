---
phase: 19-reviewer-agent
plan: 02
subsystem: testing
tags: [pytest, networkx, pydantic, langchain, mock, offline-tests, structured-output, lcel]

# Dependency graph
requires:
  - phase: 19-reviewer-agent
    plan: 01
    provides: reviewer.py with Finding+ReviewResult models, _assemble_context(), review() with LCEL chain and groundedness post-filter
  - phase: 18-debugger-agent
    plan: 02
    provides: test_debugger.py fixture patterns (debug_graph, mock_settings, mock_llm_factory) to mirror
provides:
  - 10 offline tests for TST-03 covering REVW-01, REVW-02, REVW-03, groundedness, and edge cases
  - reviewer_graph fixture (5-node DiGraph with target, 2 callers, 2 callees, all CALLS edges)
  - mock_llm_factory fixture using correct LCEL __call__ pattern for with_structured_output chains
  - Documented LCEL mock pattern: RunnableSequence calls structured_llm via __call__, not .invoke()
affects: [20-reviewer-tests, 24-orchestrator, 25-api-v2-endpoints]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Reviewer LCEL mock: mock_structured.return_value = fixture_result (RunnableSequence uses __call__, not .invoke())"
    - "Source-level patching: patch('app.core.model_factory.get_llm') intercepts lazy import before local scope resolves"
    - "reviewer_graph node attributes include file_path for groundedness test validation"

key-files:
  created:
    - backend/tests/test_reviewer.py
  modified: []

key-decisions:
  - "LCEL mock pattern for with_structured_output: mock_structured.return_value = fixture_result — ChatPromptTemplate.__or__ creates RunnableSequence that invokes structured_llm via __call__, not .invoke(). Plan spec used __or__ + mock_chain.invoke which was incorrect for this chain type."
  - "reviewer_graph fixture uses explicit file_path attributes on all 5 nodes so test_no_hallucinated_nodes can compute valid_file_paths from retrieved_nodes correctly"

patterns-established:
  - "Reviewer test pattern: 5-node reviewer_graph (target + 2 callers + 2 callees) + mock_settings (reviewer_context_hops=1) + mock_llm_factory (source-level patch with __call__ return_value)"
  - "All three V2 agent test modules (router, debugger, reviewer) use identical source-level patch target: app.core.model_factory.get_llm"

requirements-completed: [TST-03]

# Metrics
duration: 3min
completed: 2026-03-22
---

# Phase 19 Plan 02: Reviewer Agent Tests Summary

**10 offline tests for the reviewer agent covering 1-hop CALLS-edge context assembly, Finding schema completeness, groundedness (no hallucinated file_path), range targeting, empty-findings edge case, and missing-target ValueError**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-03-21T19:38:05Z
- **Completed:** 2026-03-21T19:41:05Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments

- reviewer_graph fixture: 5-node DiGraph with target (src.py), 2 callers (src.py, other.py), 2 callees (lib.py), all CALLS edges and file_path attributes
- mock_llm_factory fixture using correct LCEL invocation pattern (RunnableSequence calls structured_llm via `__call__`, not `.invoke()`)
- All 10 tests pass offline with no live API calls, no database, no network
- Total test suite advances from 124 to 134 passing (no regressions)

## Task Commits

1. **Task 1: Create test fixtures and 10 tests (initial version)** - `9b71cdf` (test)
2. **Task 2: Fix LCEL mock pattern (Rule 1 auto-fix)** - `9daf848` (fix)

**Plan metadata:** _(docs commit follows)_

## Files Created/Modified

- `backend/tests/test_reviewer.py` - 10 offline tests: reviewer_graph + mock_settings + mock_llm_factory fixtures; tests covering REVW-01 (x3), REVW-02 (x1), REVW-03 (x1), groundedness (x1), summary (x1), empty-findings (x1), missing-target (x1), schema (x1)

## Decisions Made

- LCEL mock pattern corrected from plan spec: `ChatPromptTemplate.__or__(structured_llm)` creates a `RunnableSequence` that calls `structured_llm` as a callable (via `__call__`), not via `.invoke()`. Therefore `mock_structured.return_value = fixture_result` is the correct mock — not `mock_structured.__or__ = MagicMock(return_value=mock_chain); mock_chain.invoke.return_value = fixture_result`. This matches the Phase 17 router STATE.md note about with_structured_output mocking.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Incorrect LCEL mock chain pattern in mock_llm_factory fixture**
- **Found during:** Task 2 (running tests)
- **Issue:** Plan spec called for `mock_structured.__or__ = MagicMock(return_value=mock_chain); mock_chain.invoke.return_value = fixture_result`. This is incorrect: `ChatPromptTemplate.__or__(mock_structured)` owns the pipe, creating a `RunnableSequence` that calls `mock_structured(messages)` via `__call__`, not `mock_chain.invoke(...)`. 9/10 tests failed with Pydantic ValidationError because `result.summary` was a MagicMock attribute instead of a string.
- **Fix:** Changed to `mock_structured.return_value = fixture_result` in both `mock_llm_factory` fixture and inline patch in `test_empty_findings_valid`. Removed `mock_chain` and `__or__` setup.
- **Files modified:** backend/tests/test_reviewer.py
- **Verification:** All 10 tests pass; total suite 134/134 passing
- **Committed in:** `9daf848` (fix commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - bug in plan-specified mock pattern)
**Impact on plan:** Auto-fix was essential for correctness. No scope creep. All 10 tests verify intended behavior.

## Issues Encountered

The plan spec's mock chain pattern (`__or__` + `mock_chain.invoke`) was appropriate for chains where the LLM itself owns the pipe operator — but in reviewer.py, `REVIEWER_PROMPT | structured_llm` uses `ChatPromptTemplate.__or__`, so the mock pattern from Phase 17's router tests applies here too (use `return_value` for `__call__` path). The STATE.md decision log for Phase 17 documents this but the plan spec was written with the wrong pattern.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `test_reviewer.py` is complete with all 10 TST-03 tests passing offline
- The correct LCEL mock pattern for `with_structured_output` chains (`mock_structured.return_value = fixture_result`) is now documented and should be used in any future phases testing LCEL structured-output chains
- All three V2 agent modules (router, debugger, reviewer) are now fully test-covered offline; ready for Phase 20+

---
*Phase: 19-reviewer-agent*
*Completed: 2026-03-22*
