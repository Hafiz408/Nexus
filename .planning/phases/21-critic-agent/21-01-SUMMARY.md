---
phase: 21-critic-agent
plan: 01
subsystem: agent
tags: [pydantic, critic, quality-gate, deterministic, scoring, groundedness]

# Dependency graph
requires:
  - phase: 20-tester-agent
    provides: TestResult model used in groundedness/relevance/actionability dispatch
  - phase: 19-reviewer-agent
    provides: ReviewResult and Finding models used in groundedness/actionability dispatch
  - phase: 18-debugger-agent
    provides: DebugResult and SuspectNode models used in groundedness dispatch
  - phase: 16-config-v2
    provides: max_critic_loops and critic_threshold settings fields
provides:
  - CriticResult Pydantic model with 7 fields (score, groundedness, relevance, actionability, passed, feedback, loop_count)
  - critique() public API — deterministic quality gate with no LLM call
  - Scoring weights WEIGHT_GROUNDEDNESS=0.40, WEIGHT_RELEVANCE=0.35, WEIGHT_ACTIONABILITY=0.25
affects:
  - 22-orchestrator (imports critique() to gate specialist output before routing)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Lazy specialist imports inside private helpers to prevent circular import chains
    - Hard cap checked before quality gate (loop_count >= max_loops forces pass)
    - get_settings() lazy-imported inside critique() body — same pattern as router/debugger/reviewer/tester
    - No LLM call in module — fully deterministic

key-files:
  created:
    - backend/app/agent/critic.py
  modified: []

key-decisions:
  - "Groundedness dispatch per result type: DebugResult uses traversal_path/suspects, ReviewResult uses retrieved_nodes/findings, TestResult always 1.0 (no graph citations)"
  - "Lazy specialist imports inside _extract_groundedness_inputs/_compute_relevance/_compute_actionability helpers — prevents circular imports when orchestrator imports all agents together"
  - "Hard cap checked before quality gate — loop_count >= max_loops forces passed=True unconditionally so loop always terminates (CRIT-03)"
  - "Empty cited_nodes returns groundedness=1.0 to avoid division-by-zero and correctly treat uncited results as fully grounded"
  - "ReviewResult actionability returns 1.0 when findings is empty — no findings means no actionability problem, not a failure"

patterns-established:
  - "Critic pattern: constants → CriticResult model → private helpers → public API (same layout as prior agents)"
  - "No module-level imports of specialist types — all lazy inside helper function bodies"

requirements-completed: [CRIT-01, CRIT-02, CRIT-03, CRIT-04]

# Metrics
duration: 2min
completed: 2026-03-22
---

# Phase 21 Plan 01: Critic Agent Summary

**Deterministic quality gate with composite scoring (0.4*groundedness + 0.35*relevance + 0.25*actionability), hard cap at loop_count >= 2, and per-type groundedness dispatch for DebugResult/ReviewResult/TestResult**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-21T20:16:47Z
- **Completed:** 2026-03-21T20:18:41Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- Implemented `CriticResult` Pydantic model with all 7 required fields and Field constraints (score, groundedness, relevance, actionability all ge=0.0, le=1.0)
- Implemented `critique()` public API with no LLM call — fully deterministic quality gate
- Groundedness dispatch: DebugResult uses traversal_path as retrieved set and suspect node_ids as cited set; ReviewResult uses retrieved_nodes and finding file_paths; TestResult always 1.0
- Hard cap (loop_count >= max_critic_loops) checked before quality gate — guarantees loop termination
- All specialist result types imported lazily inside helper functions to prevent circular import chains

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement critic.py — CriticResult model and scoring helpers** - `44a1e01` (feat)

**Plan metadata:** (docs commit below)

## Files Created/Modified
- `backend/app/agent/critic.py` - Critic agent: CriticResult model, scoring weights, private helpers (_compute_groundedness, _extract_groundedness_inputs, _compute_relevance, _compute_actionability, _weighted_score, _generate_feedback), critique() public API

## Decisions Made
- Groundedness dispatch per result type: DebugResult uses traversal_path/suspects, ReviewResult uses retrieved_nodes/findings, TestResult always 1.0 (no graph citations in output)
- Lazy specialist imports inside private helper functions to prevent circular import chains when orchestrator (Phase 22) imports all agents together — consistent with how all agents avoid module-level LLM imports
- Hard cap checked before quality gate so loop_count >= max_loops always returns passed=True unconditionally (CRIT-03 requirement)
- Empty cited_nodes returns groundedness=1.0 (avoids division-by-zero; nothing cited = fully grounded)
- ReviewResult actionability returns 1.0 when findings list is empty (empty findings is not an actionability failure)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- `CriticResult` and `critique()` are importable without any API keys or postgres env vars
- Scoring weights sum to exactly 1.0 (verified)
- Hard cap and quality gate behaviors verified against all three specialist result types
- Ready for Phase 22 (orchestrator) to integrate critique() into the agent loop

---
*Phase: 21-critic-agent*
*Completed: 2026-03-22*
