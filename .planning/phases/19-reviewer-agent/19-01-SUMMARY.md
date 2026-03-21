---
phase: 19-reviewer-agent
plan: 01
subsystem: api
tags: [pydantic, langchain, networkx, structured-output, code-review, graph-traversal]

# Dependency graph
requires:
  - phase: 18-debugger-agent
    provides: debugger.py module and lazy-import pattern for agent modules
  - phase: 17-router-agent
    provides: router.py with_structured_output pattern via LCEL pipe
  - phase: 16-config-v2
    provides: reviewer_context_hops setting in Settings
provides:
  - Finding Pydantic model with 7 fields (severity, category, description, file_path, line_start, line_end, suggestion)
  - ReviewResult Pydantic model with 3 fields (findings, retrieved_nodes, summary)
  - _assemble_context() helper with CALLS-edge filter for 1-hop neighborhood
  - review() public API with lazy get_llm/get_settings imports and groundedness post-filter
affects: [20-reviewer-tests, 24-orchestrator, 25-api-v2-endpoints]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Groundedness post-filter: drop LLM findings whose file_path not in retrieved node set"
    - "range_clause injection: ChatPromptTemplate.partial() used to conditionally append selection focus"
    - "LCEL structured output: REVIEWER_PROMPT | llm.with_structured_output(ReviewResult)"
    - "Lazy import inside function body: get_llm() and get_settings() imported inside review() only"

key-files:
  created:
    - backend/app/agent/reviewer.py
  modified: []

key-decisions:
  - "Groundedness post-filter applied after LLM call, not before — allows LLM to see full context but enforces file_path validity on output"
  - "range_clause injected via REVIEWER_PROMPT.partial() per-call, not baked into system prompt constant — keeps REVIEWER_SYSTEM reusable"
  - "reviewer_context_hops setting read inside review() but currently unused beyond asserting its presence — reserved for future N-hop expansion"
  - "Both tasks implemented in a single file write since _assemble_context() and review() were specified together; committed as one feat commit"

patterns-established:
  - "Reviewer pattern: 1-hop CALLS-edge neighborhood -> structured LLM output -> groundedness filter -> ReviewResult"
  - "All three V2 agent modules (router, debugger, reviewer) follow identical lazy-import pattern for get_llm/get_settings"

requirements-completed: [REVW-01, REVW-02, REVW-03]

# Metrics
duration: 8min
completed: 2026-03-22
---

# Phase 19 Plan 01: Reviewer Agent Summary

**reviewer.py with Finding+ReviewResult Pydantic models, 1-hop CALLS-edge graph context assembly, LCEL structured-output chain, and groundedness post-filter that drops hallucinated file_path references**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-03-22T19:27:00Z
- **Completed:** 2026-03-22T19:35:00Z
- **Tasks:** 2 (implemented together in one file write)
- **Files modified:** 1

## Accomplishments

- Finding model with all 7 required fields including `severity: Literal["critical", "warning", "info"]`
- ReviewResult model with findings, retrieved_nodes, and summary fields
- `_assemble_context()` builds 1-hop context via CALLS-edge filter on both `G.predecessors()` and `G.successors()`
- `review()` function with lazy imports, LCEL `REVIEWER_PROMPT | llm.with_structured_output(ReviewResult)` chain, and groundedness post-filter
- Module imports cleanly without API keys set (no module-level LLM or settings calls)
- All 124 prior tests remain passing with no regressions

## Task Commits

1. **Task 1 + Task 2: reviewer.py complete implementation** - `c4fc495` (feat) — Both tasks combined since file was written atomically

## Files Created/Modified

- `backend/app/agent/reviewer.py` - Reviewer agent: Finding, ReviewResult models, _assemble_context() helper, review() public API

## Decisions Made

- Groundedness post-filter applied AFTER LLM call: LLM gets full context but any finding with a `file_path` not present in `retrieved_nodes` is dropped before returning. This prevents hallucinated paths from leaking to the caller.
- `range_clause` is injected per-call via `REVIEWER_PROMPT.partial(range_clause=range_clause)` rather than being baked into the system prompt constant, keeping `REVIEWER_SYSTEM` reusable across calls with and without selection focus.
- `reviewer_context_hops` is read from settings (via `_ = settings.reviewer_context_hops`) to ensure the field exists and is accessible, even though current implementation is fixed at 1 hop. This is a forward-compatibility hook for future N-hop expansion.
- Both tasks (Task 1: models + skeleton; Task 2: helpers + review()) were implemented in a single file write since they produce the same file. Committed as a single feat commit rather than two partial-file commits.

## Deviations from Plan

### Implementation Approach

**Combined Task 1 and Task 2 into single file write and single commit**
- **Found during:** Task 1
- **Reason:** Both tasks write to the same file (`reviewer.py`). Writing the skeleton (Task 1) and then adding the helpers+review() (Task 2) would require reading and editing the same file twice. Writing the complete file once is cleaner and avoids intermediate states where the file imports cleanly but lacks the public API.
- **Impact:** Single commit `c4fc495` covers both tasks. No functionality is missing.

---

**Total deviations:** 1 (process deviation — combined commits for same-file tasks)
**Impact on plan:** All plan requirements met. No functionality omitted or changed.

## Issues Encountered

None - plan executed cleanly. The AST-based module-level import check confirmed that `get_llm` and `get_settings` appear only inside the `review()` function body (col_offset > 0), not at module level.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `reviewer.py` is complete and ready for Phase 20 (reviewer agent test suite)
- All three agent modules (router.py, debugger.py, reviewer.py) follow identical lazy-import pattern — Phase 20 tests should mirror Phase 18's `mock_llm_factory` and `mock_settings` fixture pattern
- Groundedness post-filter requires test graphs with explicit `file_path` attributes on nodes to validate correctly

---
*Phase: 19-reviewer-agent*
*Completed: 2026-03-22*
