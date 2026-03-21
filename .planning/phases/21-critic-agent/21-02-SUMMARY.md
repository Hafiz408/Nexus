---
phase: 21-critic-agent
plan: 02
subsystem: agent
tags: [pytest, critic, offline-tests, scoring, groundedness, quality-gate, TST-05]

# Dependency graph
requires:
  - phase: 21-01
    provides: CriticResult model and critique() public API being tested

provides:
  - 10 offline unit tests for critique() covering all TST-05 scenarios
  - Coverage of scoring formula, retry routing, hard loop cap, boundary conditions, per-type groundedness, and feedback semantics

affects:
  - CI: total test count raised to 158

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Settings injection directly into critique(settings=mock_settings) — no patching of get_settings required
    - Module-level helper builders (make_debug_result, make_review_result, make_test_result) instead of fixtures for arbitrary argument flexibility
    - mock_settings as MagicMock with max_critic_loops=2 and critic_threshold=0.7 — matches production defaults

key-files:
  created:
    - backend/tests/test_critic.py
  modified: []

key-decisions:
  - "Module-level helper builders chosen over fixtures so tests can construct inputs with arbitrary node_ids and traversal paths without fixture composition overhead"
  - "critic_threshold=0.0 override in test_feedback_none_on_pass to force pass path without needing a high-scoring result — tests the feedback=None invariant independently"
  - "Loop boundary test (loop_count=1) explicitly added to confirm hard cap fires at exactly 2, not 1 — validates CRIT-03 fence-post behavior"

requirements-completed: [TST-05]

# Metrics
duration: 1min
completed: 2026-03-22
---

# Phase 21 Plan 02: Critic Agent Tests Summary

**10 offline unit tests for critique() covering scoring formula arithmetic, retry routing, hard cap (loop_count>=2), loop boundary (count=1 rejects), feedback semantics, and per-type groundedness dispatch for DebugResult/ReviewResult/TestResult**

## Performance

- **Duration:** 1 min
- **Started:** 2026-03-22T08:00:00Z
- **Completed:** 2026-03-22T08:01:00Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- Created `backend/tests/test_critic.py` with exactly 10 test functions
- All 10 tests pass offline (0.14s) with no live API calls
- Full test suite: 158 tests passing, 0 failures (up from 148)
- `mock_settings` fixture injects `max_critic_loops=2` and `critic_threshold=0.7` directly into `critique()` — no `get_settings()` patching needed
- Module-level helpers (`make_debug_result`, `make_review_result`, `make_test_result`) enable flexible per-test construction

## Task Commits

Each task was committed atomically:

1. **Task 1: Write test_critic.py — 10 offline tests for TST-05** - `b385bcb` (test)

**Plan metadata:** (docs commit below)

## Files Created/Modified
- `backend/tests/test_critic.py` - 10 offline unit tests: mock_settings fixture, 3 module-level helper builders, tests covering scoring formula, retry routing, hard cap at 2, loop=1 boundary, feedback=None on pass, DebugResult groundedness (both cited and uncited), ReviewResult groundedness dispatch, TestResult groundedness always 1.0, and full CriticResult field presence across all loop_count values

## Decisions Made
- Module-level helper builders chosen over fixtures so tests can construct inputs with arbitrary node_ids and traversal paths without fixture composition overhead
- `critic_threshold=0.0` override in `test_feedback_none_on_pass` to force pass path without needing a high-scoring result — tests the `feedback=None` invariant independently of score arithmetic
- Loop boundary test (`loop_count=1`) explicitly added to confirm hard cap fires at exactly 2 — validates CRIT-03 fence-post behavior (cap is at max_loops, not max_loops-1)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required

None - no external service configuration required.

## Test Coverage Summary

| Test | CRIT req | Scenario |
|------|----------|----------|
| test_scoring_formula_weights | CRIT-01 | score == round(0.4*G + 0.35*R + 0.25*A, 4) |
| test_retry_routing_on_low_score | CRIT-02 | score < 0.7, loop=0 → passed=False, non-empty feedback |
| test_hard_cap_at_two_loops | CRIT-03 | loop_count=2 forces passed=True, feedback=None |
| test_loop_count_one_still_rejects | CRIT-03 | loop_count=1, low score → passed=False (cap at 2) |
| test_feedback_none_on_pass | TST-05 | passed=True → feedback is None, never empty string |
| test_debug_result_groundedness_cited_in_traversal | CRIT-04 | node in traversal_path → G=1.0 |
| test_debug_result_groundedness_not_in_traversal | CRIT-04 | node absent from traversal_path → G<1.0 |
| test_review_result_groundedness | CRIT-04 | ReviewResult dispatch path, result in [0,1] |
| test_test_result_groundedness_always_one | CRIT-04 | TestResult always G=1.0 (no graph citations) |
| test_critic_result_always_has_score_and_loop_count | TST-05 | All sub-scores + loop_count present at all loop values |

## Next Phase Readiness
- All TST-05 acceptance criteria verified offline
- 158 tests passing (V1 93 tests + V2 65 tests) — V1 test suite unaffected
- Ready for Phase 22 (orchestrator) — critique() import and routing verified

---
*Phase: 21-critic-agent*
*Completed: 2026-03-22*
