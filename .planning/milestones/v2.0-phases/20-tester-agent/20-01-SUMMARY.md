---
phase: 20-tester-agent
plan: 01
subsystem: testing
tags: [langchain, pydantic, networkx, pytest, test-generation, structured-output]

# Dependency graph
requires:
  - phase: 19-reviewer-agent
    provides: reviewer.py structural pattern (docstring, constants, models, helpers, public API sections)
  - phase: 18-debugger-agent
    provides: lazy-import pattern for get_llm/get_settings inside agent function body
provides:
  - backend/app/agent/tester.py with _detect_framework(), _get_callees(), _derive_test_path(), test() public API
  - TestResult Pydantic model (test_code, test_file_path, framework)
  - _LLMTestOutput Pydantic model for LLM structured output
affects: [20-02-tests, 21-graph-agent, 25-orchestrator]

# Tech tracking
tech-stack:
  added: []
  patterns: [lazy-import-agent-pattern, two-model-llm-approach, deterministic-path-derivation, framework-marker-detection]

key-files:
  created: [backend/app/agent/tester.py]
  modified: []

key-decisions:
  - "Tester uses two-model pattern: _LLMTestOutput for LLM call (test_code only), TestResult assembled deterministically post-call"
  - "Framework detection is pure file-system scan (_FRAMEWORK_MARKERS dict) — no LLM call; first marker match wins (pytest priority)"
  - "_derive_test_path() called after LLM returns to build test_file_path — LLM never generates paths"
  - "get_llm() and get_settings() imported inside test() body (lazy) consistent with router.py, debugger.py, reviewer.py pattern"
  - "TESTER_SYSTEM prompt uses UPPERCASE REQUIREMENTS block and mandates EXACTLY three or more test functions"

patterns-established:
  - "Lazy-import pattern: get_llm/get_settings imported inside public API function body with # noqa: PLC0415"
  - "Two-model LLM approach: _LLMTestOutput captures raw LLM output; result model (TestResult) assembled deterministically"
  - "Deterministic path derivation: file paths always computed from (func_name, framework), never trusted from LLM"
  - "Framework-marker detection: dict-driven scan of repo root files, priority-ordered, with rglob fallback"

requirements-completed: [TEST-01, TEST-02, TEST-03, TEST-04, TEST-05]

# Metrics
duration: 2min
completed: 2026-03-22
---

# Phase 20 Plan 01: Tester Agent Summary

**Graph-aware test generator with deterministic framework detection (_detect_framework), mock target enumeration (_get_callees), and LLM-constrained test synthesis returning test_file_path via _derive_test_path — not from LLM output**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-03-21T19:55:33Z
- **Completed:** 2026-03-21T19:56:55Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- Created `backend/app/agent/tester.py` (219 lines) following reviewer.py section structure exactly
- `_detect_framework()` scans repo root for marker files (pytest/jest/vitest/junit) without any LLM call
- `_get_callees()` returns all CALLS-edge successors of target_node_id as mock target dicts
- `_derive_test_path()` maps (func_name, framework) to conventional test file path for each supported framework
- `test()` public API with lazy get_llm/get_settings imports inside function body — safe for pytest collection without API keys
- TESTER_SYSTEM prompt mandates EXACTLY three or more test functions (happy path, error, edge cases)
- _MOCK_SYNTAX dict injects correct framework mock syntax per framework into system prompt

## Task Commits

Each task was committed atomically:

1. **Task 1: Create backend/app/agent/tester.py** - `7eb4025` (feat)

**Plan metadata:** (docs commit — see below)

## Files Created/Modified
- `backend/app/agent/tester.py` - Tester agent module: _detect_framework, _get_callees, _derive_test_path helpers + test() public API with lazy imports

## Decisions Made
- Two-model pattern chosen to keep LLM scope minimal: _LLMTestOutput contains only test_code; test_file_path and framework are always derived deterministically
- Framework priority order: pytest first (most common in this Python-heavy project), then jest, vitest, junit
- get_llm() and get_settings() imported inside test() body (lazy), consistent with all prior V2 agent modules

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `backend/app/agent/tester.py` ready for Phase 20 Plan 02 (test suite: offline tests using mock LLM + mock graph)
- All three deterministic helpers (_detect_framework, _get_callees, _derive_test_path) are standalone callables — easily testable without any mock setup

---
*Phase: 20-tester-agent*
*Completed: 2026-03-22*
