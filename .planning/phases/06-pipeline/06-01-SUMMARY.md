---
phase: 06-pipeline
plan: "01"
subsystem: api
tags: [asyncio, pydantic, pipeline, ingestion, fastapi]

# Dependency graph
requires:
  - phase: 05-embedder
    provides: embed_and_store, save_graph, delete_nodes_for_files
  - phase: 04-graph-builder
    provides: build_graph
  - phase: 03-ast-parser
    provides: parse_file
  - phase: 02-file-walker
    provides: walk_repo, EXTENSION_TO_LANGUAGE
provides:
  - run_ingestion async orchestrator wiring all ingestion components
  - _parse_concurrent concurrent file parser using asyncio.Semaphore + asyncio.to_thread
  - get_status accessor for module-level _status dict
  - IndexStatus Pydantic model with status, nodes_indexed, edges_indexed, files_processed, error
affects: [07-index-endpoint, 08-query-api]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - asyncio.gather with return_exceptions=True for resilient concurrent processing
    - asyncio.to_thread for offloading blocking I/O in async context
    - asyncio.Semaphore(10) for bounded concurrency
    - Module-level status dict pattern for background task progress tracking

key-files:
  created:
    - backend/app/ingestion/pipeline.py
  modified:
    - backend/app/models/schemas.py

key-decisions:
  - "IndexStatus uses str | None union syntax (not Optional[str]) — consistent with Python 3.11 + pydantic v2 patterns"
  - "asyncio.gather with return_exceptions=True — single parse failure does not cancel all other parses"
  - "embed_and_store and save_graph wrapped in asyncio.to_thread — they are blocking I/O operations"
  - "Incremental path calls delete_nodes_for_files before re-parsing to avoid stale nodes in graph"
  - "Module-level _status dict keyed by repo_path — readable via get_status() at any point during async execution"

patterns-established:
  - "Pipeline orchestrator pattern: wire all ingestion components into single async run_ingestion() entry point"
  - "Status tracking pattern: set status='running' at start, update with files_processed count, set final status at end"
  - "Incremental ingestion pattern: delete old nodes first, then re-parse only changed files"

requirements-completed: [PIPE-01, PIPE-02, PIPE-03, PIPE-04, PIPE-05]

# Metrics
duration: 7min
completed: 2026-03-18
---

# Phase 6 Plan 01: Pipeline Orchestrator Summary

**Async ingestion pipeline wiring walker, ast_parser, graph_builder, embedder, and graph_store into run_ingestion() with concurrent file parsing via asyncio.Semaphore(10) and incremental update support**

## Performance

- **Duration:** 7 min
- **Started:** 2026-03-18T13:07:07Z
- **Completed:** 2026-03-18T13:53:17Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- IndexStatus Pydantic model added to schemas.py with all 5 fields (status, nodes_indexed, edges_indexed, files_processed, error)
- pipeline.py created with run_ingestion orchestrator, _parse_concurrent helper, and get_status accessor
- Concurrent file parsing via asyncio.Semaphore(10) + asyncio.to_thread(parse_file)
- Incremental ingestion path: delete_nodes_for_files before re-parsing changed files only
- All blocking I/O (save_graph, embed_and_store) wrapped in asyncio.to_thread
- 54 of 57 tests pass (3 pre-existing failures in test_embedder.py unrelated to this plan)

## Task Commits

Each task was committed atomically:

1. **Task 1: Add IndexStatus Pydantic model to schemas.py** - `2b1c4d6` (feat)
2. **Task 2: Implement pipeline.py with run_ingestion, _parse_concurrent, get_status** - `380fb62` (feat)

## Files Created/Modified
- `backend/app/models/schemas.py` - Added IndexStatus model with status/nodes_indexed/edges_indexed/files_processed/error fields
- `backend/app/ingestion/pipeline.py` - New pipeline orchestrator with run_ingestion, _parse_concurrent, get_status

## Decisions Made
- IndexStatus uses `str | None` union syntax (not `Optional[str]`) — consistent with Python 3.11 + pydantic v2 patterns used throughout project
- `asyncio.gather` with `return_exceptions=True` — single parse failure does not cancel all other parses
- `embed_and_store` and `save_graph` wrapped in `asyncio.to_thread` — they are blocking I/O operations
- Incremental path calls `delete_nodes_for_files` before re-parsing to avoid stale nodes
- Module-level `_status` dict keyed by `repo_path` — readable via `get_status()` at any point

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- 3 pre-existing test failures in test_embedder.py (postgres_db Field required - pydantic_settings ValidationError) were present before this plan's work and are not caused by any changes here. 54 of 57 tests pass.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- pipeline.py is ready for Phase 7 (Index Endpoint) to call `run_ingestion` as a FastAPI `BackgroundTask`
- `get_status(repo_path)` accessor available for Phase 7 to expose status polling endpoint
- IndexStatus model available for Phase 7 response schemas

---
*Phase: 06-pipeline*
*Completed: 2026-03-18*
