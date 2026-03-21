---
phase: 20-tester-agent
plan: 02
subsystem: testing
tags: [pytest, networkx, unittest-mock, pydantic, langchain, offline-tests]

# Dependency graph
requires:
  - phase: 20-01
    provides: backend/app/agent/tester.py with _detect_framework, _get_callees, _derive_test_path, test() public API
  - phase: 19-02
    provides: test_reviewer.py structural pattern (fixtures, source-level mock, LCEL __call__ pattern)
provides:
  - backend/tests/test_tester.py with 10 offline tests covering TST-04 acceptance criteria
  - tester_graph fixture (4-node DiGraph: target + 2 CALLS callees + 1 isolated node)
  - framework detection tests via tmp_path seeding (no real repo dependency)
  - mock_llm_factory fixture with source-level patch + LCEL mock_structured.return_value pattern
affects: [21-graph-agent, 25-orchestrator]

# Tech tracking
tech-stack:
  added: []
  patterns: [source-level-lazy-import-mock, LCEL-call-mock-pattern, tester-graph-topology, tmp-path-framework-seeding]

key-files:
  created: [backend/tests/test_tester.py, backend/pytest.ini]
  modified: []

key-decisions:
  - "Import alias: 'from app.agent.tester import test as run_test' avoids pytest collecting the public test() API as a test function — named 'test' without prefix triggers pytest collection of the production function"
  - "pytest.ini added with testpaths=tests and norecursedirs=app to prevent pytest scanning app/ source modules for test functions"
  - "tester_graph fixture uses 4-node topology (2 CALLS callees + 1 isolated) to verify _get_callees count is exactly 2"
  - "mock_structured.return_value = _LLMTestOutput(test_code=...) — LCEL RunnableSequence calls structured_llm via __call__, not .invoke()"

patterns-established:
  - "tester_graph fixture topology: 4-node DiGraph (target + 2 CALLS-edge callees + 1 isolated node) — verifies callee count isolation"
  - "LCEL mock pattern: mock_structured.return_value = _LLMTestOutput(test_code=...) — __call__ path used by RunnableSequence"
  - "Framework detection tests via tmp_path seeding: (tmp_path / 'pytest.ini').write_text('[pytest]\\n') — no real repo needed"
  - "Import aliasing: import test as run_test to prevent pytest collecting production function named 'test'"

requirements-completed: [TST-04]

# Metrics
duration: 5min
completed: 2026-03-22
---

# Phase 20 Plan 02: Tester Agent Tests Summary

**10-function offline test suite for the tester agent covering framework detection (5 heuristics), callee enumeration (2-target count + isolated-node exclusion), parametrized path derivation (5 frameworks), and full integration asserting >=3 generated test functions and mock syntax presence**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-03-21T19:58:55Z
- **Completed:** 2026-03-21T20:04:00Z
- **Tasks:** 1
- **Files modified:** 2

## Accomplishments
- Created `backend/tests/test_tester.py` (259 lines) with 10 test function definitions covering all TST-04 acceptance criteria
- Framework detection tests use `tmp_path` seeding — pytest, jest, vitest, rglob fallback, and unknown all verified without a real repo
- `_get_callees` tests confirm count=2 from tester_graph and confirm "helper_fn" (isolated node) is excluded
- `_derive_test_path` parametrized across 5 frameworks (pytest, jest, vitest, junit, unknown) with exact expected path strings
- Integration tests (test 9 + 10) verify TestResult fields and >=3 "def test_" definitions in generated code
- `backend/pytest.ini` added to restrict pytest collection to `tests/` only, preventing the production `test()` function being mistaken for a test

## Task Commits

Each task was committed atomically:

1. **Task 1: Create backend/tests/test_tester.py — fixtures and 10 offline tests** - `403cb65` (feat)

**Plan metadata:** (docs commit — see below)

## Files Created/Modified
- `backend/tests/test_tester.py` - 10 offline tester agent tests: 3 fixtures + 10 test functions (14 collected items due to parametrize expansion)
- `backend/pytest.ini` - Restricts pytest to `testpaths = tests` + `norecursedirs = app data .venv __pycache__`

## Decisions Made
- Aliased import `from app.agent.tester import test as run_test` to prevent pytest treating the production `test()` function as a test — discovered when pytest collected `tests/test_tester.py::test` and failed with "fixture 'question' not found"
- Added `backend/pytest.ini` with `testpaths = tests` and `norecursedirs` — the function name collision persisted even with testpaths alone because pytest scans imported module namespaces; the import alias was the definitive fix
- `mock_llm_factory` fixture yields (not returns) `mock_factory` — consistent with reviewer pattern; allows teardown of the patch context manager

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Import alias to prevent pytest collecting production test() function**
- **Found during:** Task 1 (running test suite verification)
- **Issue:** `from app.agent.tester import test` brought the production `test(question, G, ...)` function into the test module namespace with the name `test`; pytest collected it as a fixture-based test and failed with "fixture 'question' not found"
- **Fix:** Changed import to `test as run_test`; updated 2 call sites in test functions 9 and 10
- **Files modified:** backend/tests/test_tester.py
- **Verification:** `pytest tests/test_tester.py -v` shows 14 PASSED, 0 errors
- **Committed in:** 403cb65 (Task 1 commit)

**2. [Rule 3 - Blocking] Added backend/pytest.ini to scope collection to tests/ directory**
- **Found during:** Task 1 (investigating pytest collection error for tester.py::test)
- **Issue:** Without testpaths restriction, pytest could scan app/ source modules and attempt to collect any function starting with "test"
- **Fix:** Created `backend/pytest.ini` with `testpaths = tests` and `norecursedirs = app data .venv __pycache__`
- **Files modified:** backend/pytest.ini (new file)
- **Verification:** Full suite runs cleanly with 148 passing
- **Committed in:** 403cb65 (Task 1 commit)

---

**Total deviations:** 2 auto-fixed (2 blocking)
**Impact on plan:** Both fixes necessary to make the test suite runnable. Import alias is the definitive fix; pytest.ini is belt-and-suspenders protection for future agent modules that may also have functions starting with "test".

## Issues Encountered
- pytest's `norecursedirs` did not prevent the collection error on its own because the issue was in the test module's imported namespace, not direct directory scanning. The import alias (`test as run_test`) was required as the primary fix.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `backend/tests/test_tester.py` complete — TST-04 fully satisfied
- 148 tests passing (V1 suite fully green, all V2 agents tested offline)
- Phase 20 fully complete; ready for Phase 21 (graph agent)

---
*Phase: 20-tester-agent*
*Completed: 2026-03-22*
