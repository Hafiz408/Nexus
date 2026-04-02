---
phase: 24-query-endpoint-v2
plan: 01
subsystem: api
tags: [fastapi, langgraph, sse, streaming, pydantic, sqlite, asyncio]

# Dependency graph
requires:
  - phase: 22-orchestrator
    provides: build_graph, NexusState — wired into V2 branch via lazy import
  - phase: 23-mcp-tools
    provides: MCP layer complete; all agents available for orchestrator invocation

provides:
  - QueryRequest with 5 additive optional V2 fields (intent_hint, target_node_id, selected_file, selected_range, repo_root)
  - V2 branch in /query endpoint gated on intent_hint; routes through LangGraph orchestrator
  - V1 SSE path (token, citations, done events) completely unmodified

affects:
  - 24-query-endpoint-v2 (plan 02 if any)
  - Frontend integration (intent_hint field now accepted)
  - Any test suite exercising POST /query

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "V2 branch inserted above V1 generator block with zero modifications to V1 lines"
    - "Lazy import pattern applied to build_graph, SqliteSaver, sqlite3, uuid4 inside v2_event_generator body"
    - "asyncio.to_thread(graph.invoke, ...) to offload synchronous LangGraph execution off the event loop"
    - "Intent gate: intent_hint not None and not 'auto' triggers V2; None and 'auto' both fall through to V1"

key-files:
  created: []
  modified:
    - backend/app/models/schemas.py
    - backend/app/api/query_router.py

key-decisions:
  - "Gate condition: `if request_body.intent_hint and request_body.intent_hint != 'auto'` — both None AND 'auto' fall through to V1 (Pitfall 6 in RESEARCH.md)"
  - "All orchestrator/SqliteSaver/sqlite3 imports are lazy (inside v2_event_generator body) — prevents import-time ValidationError when API keys absent"
  - "asyncio.to_thread(graph.invoke, ...) — graph.invoke() is synchronous; calling directly would block the FastAPI event loop"
  - "SqliteSaver connects to data/checkpoints.db — never data/nexus.db (locked decision, STATE.md)"
  - "Thread ID uses uuid4 suffix scoped per request — prevents cross-request state bleed in SqliteSaver"
  - "model_dump(mode='json') used for specialist result serialization — handles nested Pydantic models (e.g. CodeNode objects in _ExplainResult.nodes)"

patterns-established:
  - "V2-branch-above-V1: insert new async generators before existing V1 generator, never modify V1 lines"
  - "Per-request uuid4 thread_id for LangGraph checkpoint isolation"

requirements-completed:
  - TST-08

# Metrics
duration: 2min
completed: 2026-03-22
---

# Phase 24 Plan 01: Query Endpoint V2 Branch Summary

**V2 intent-routing branch wired into /query endpoint — named-intent requests route through LangGraph orchestrator while all V1 SSE behaviour (token/citations/done) stays completely unchanged**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-21T21:26:33Z
- **Completed:** 2026-03-21T21:27:59Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- QueryRequest extended with 5 additive optional fields (all None by default); V1 callers sending only {question, repo_path} never receive 422
- V2 event generator inserted between HTTPException guard and V1 event_generator with zero modifications to any V1 line
- All 9 V1 tests in test_query_router.py pass green; import of query_router succeeds cleanly

## Task Commits

Each task was committed atomically:

1. **Task 1: Extend QueryRequest with additive V2 optional fields** - `de011d2` (feat)
2. **Task 2: Wire V2 branch into query_router.py** - `d75d004` (feat)

**Plan metadata:** committed as part of final docs commit.

## Files Created/Modified

- `backend/app/models/schemas.py` - Added `from typing import Optional` and five optional V2 fields after hop_depth
- `backend/app/api/query_router.py` - Inserted v2_event_generator block (58 lines) gated on intent_hint; V1 block untouched

## Decisions Made

- Gate condition uses both checks (`intent_hint and intent_hint != "auto"`) so that `None` (omitted) and `"auto"` (explicit legacy value) both fall through to V1 path
- All lazy imports inside generator body follow the established project-wide pattern (Phases 17-23) to prevent import-time ValidationError
- `asyncio.to_thread(graph.invoke, ...)` is mandatory — LangGraph's `invoke()` is synchronous and would block the FastAPI event loop if called directly
- Checkpoints DB is `data/checkpoints.db` (locked decision from Phase 22 STATE.md) — separate from `data/nexus.db`
- Per-request `uuid4` thread_id prevents SqliteSaver state from bleeding across concurrent requests
- `model_dump(mode="json")` chosen over `.dict()` — Pydantic v2 method that recursively serializes nested models correctly

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- V2 branch is live; named-intent POST /query requests (intent_hint=debug/review/test/explain) now route through the full LangGraph orchestrator pipeline
- `data/checkpoints.db` directory must exist at server start (or be created by the app before first V2 request)
- TST-08 satisfied: all V1 tests green, V1 callers never receive 422 from new fields

## Self-Check: PASSED

- FOUND: backend/app/models/schemas.py
- FOUND: backend/app/api/query_router.py
- FOUND: .planning/phases/24-query-endpoint-v2/24-01-SUMMARY.md
- FOUND: commit de011d2 (Task 1)
- FOUND: commit d75d004 (Task 2)
- V1 tests: 9 passed, 0 failed

---
*Phase: 24-query-endpoint-v2*
*Completed: 2026-03-22*
