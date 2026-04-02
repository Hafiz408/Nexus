---
phase: 27-wire-review-test-e2e
plan: "02"
subsystem: api
tags: [pydantic, orchestrator, langgraph, review, test, fallback]

# Dependency graph
requires:
  - phase: 27-wire-review-test-e2e-01
    provides: selected_file/selected_range/target_node_id threaded from extension to backend
  - phase: 19-reviewer-agent
    provides: reviewer.py review() function and ReviewResult model
  - phase: 20-tester-agent
    provides: tester.py test() function and TestResult model
  - phase: 22-orchestrator
    provides: NexusState TypedDict and orchestrator node functions
provides:
  - _derive_target_from_file() graph-scan helper in orchestrator.py
  - _review_node with target_node_id fallback via selected_file+selected_range
  - _test_node with target_node_id fallback via selected_file+selected_range
  - Graceful empty ReviewResult/TestResult when no context available at all
  - QueryRequest.selected_range typed as Optional[list[int]] (Pydantic v2 safe)
  - reviewer.py without unused Field import
  - tester.py without unused Literal import
affects: [28-phase-onwards, test-review-e2e-flows]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "_derive_target_from_file suffix-match: handles absolute vs relative path forms"
    - "Graceful fallback pattern: derive from file context, then return empty result with user message"
    - "TestResult graceful-no-target uses only the three real model fields (test_code, test_file_path, framework)"

key-files:
  created: []
  modified:
    - backend/app/models/schemas.py
    - backend/app/agent/reviewer.py
    - backend/app/agent/tester.py
    - backend/app/agent/orchestrator.py

key-decisions:
  - "selected_range typed as Optional[list[int]] (not Optional[tuple]) — Pydantic v2 does not auto-coerce JSON arrays to tuples"
  - "Graceful TestResult for no-target case uses actual model fields (test_code, test_file_path, framework) — plan's target_function and mocks fields do not exist on TestResult"
  - "_derive_target_from_file uses suffix matching (endswith) for both absolute and relative path form compatibility"
  - "networkx imported lazily inside _derive_target_from_file (already module-wide lazy pattern)"

patterns-established:
  - "No-target fallback: derive from file context first, return empty result with user message second"
  - "Suffix-based file path matching: node_file.endswith(selected_file) or selected_file.endswith(node_file)"

requirements-completed: [REVW-01, REVW-02, REVW-03, TEST-01, TEST-02, TEST-03, TEST-04, TEST-05]

# Metrics
duration: 5min
completed: 2026-03-25
---

# Phase 27 Plan 02: Wire Review/Test E2E — Backend Resilience Summary

**Orchestrator _review_node and _test_node now fall back to graph-scan when target_node_id is None, with graceful empty-result returns and Pydantic v2-safe list[int] type for selected_range**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-03-25T09:11:08Z
- **Completed:** 2026-03-25T09:16:00Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Fixed Pydantic v2 tuple coercion issue: `selected_range` changed from `Optional[tuple]` to `Optional[list[int]]` in schemas.py so JSON arrays `[10, 20]` are accepted correctly
- Added `_derive_target_from_file()` helper to orchestrator.py: scans graph nodes matching file suffix + line midpoint for automatic target resolution
- Updated `_review_node` and `_test_node` to derive `target_node_id` from `selected_file`+`selected_range` when not provided, and return graceful user-facing result when no node is found
- Cleaned unused imports: `Field` from reviewer.py, `Literal` from tester.py
- 191 tests passing (1 more than baseline — no regressions)

## Task Commits

Each task was committed atomically:

1. **Task 1: Fix selected_range type and clean unused imports** - `e8fdd2f` (fix)
2. **Task 2: Add target_node_id fallback in orchestrator** - `2d3cced` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified
- `backend/app/models/schemas.py` - `selected_range` changed to `Optional[list[int]]`
- `backend/app/agent/reviewer.py` - Removed unused `Field` import from pydantic
- `backend/app/agent/tester.py` - Removed unused `Literal` import from typing
- `backend/app/agent/orchestrator.py` - Added `_derive_target_from_file()` helper; updated `_review_node` and `_test_node` with fallback logic

## Decisions Made
- `selected_range` typed as `Optional[list[int]]` not `Optional[tuple]` — Pydantic v2 does not auto-coerce JSON arrays to Python tuples, causing silent validation failures
- Graceful `TestResult` for the no-target case uses only the actual model fields (`test_code`, `test_file_path`, `framework`) — the plan referenced `target_function` and `mocks` fields that do not exist on `TestResult`
- `_derive_target_from_file` uses suffix matching (`endswith`) for both absolute and relative path form compatibility
- `networkx` imported lazily inside `_derive_target_from_file` consistent with the module-wide lazy-import pattern

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Adapted graceful TestResult no-target return to actual model fields**
- **Found during:** Task 2 (Add target_node_id fallback in orchestrator)
- **Issue:** Plan's graceful-error `TestResult` construction used `target_function` and `mocks` fields that do not exist on the `TestResult` Pydantic model (which only has `test_code`, `test_file_path`, `framework`)
- **Fix:** Removed non-existent fields; used `test_code` field with the explanatory comment as message text
- **Files modified:** `backend/app/agent/orchestrator.py`
- **Verification:** `python -m pytest tests/ -x -q` — 191 passed, 0 failed; `python -c "from app.agent.orchestrator import _derive_target_from_file; print('ok')"` — ok
- **Committed in:** `2d3cced` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Fix necessary to prevent Pydantic validation error at runtime. No scope creep.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Backend now resilient to `target_node_id=None` on Review and Test paths
- After Plan 01 wires `selected_file` from extension, graph-scan fallback will automatically find the relevant node
- When no context is available at all, a user-friendly message is returned via the normal result payload
- Ready for Phase 27 Plan 03 (E2E integration tests) or any remaining wiring plans

## Self-Check: PASSED

All created/modified files found. All task commits verified in git log.

- FOUND: backend/app/models/schemas.py
- FOUND: backend/app/agent/orchestrator.py
- FOUND: backend/app/agent/reviewer.py
- FOUND: backend/app/agent/tester.py
- FOUND: .planning/phases/27-wire-review-test-e2e/27-02-SUMMARY.md
- FOUND: e8fdd2f (Task 1 commit)
- FOUND: 2d3cced (Task 2 commit)

---
*Phase: 27-wire-review-test-e2e*
*Completed: 2026-03-25*
