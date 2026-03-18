---
phase: 07-index-endpoint
plan: 01
subsystem: api
tags: [fastapi, router, index, embeddings, graph, cleanup]
dependency_graph:
  requires: [06-pipeline]
  provides: [index-api-router]
  affects: [backend/app/api/index_router.py, backend/app/models/schemas.py]
tech_stack:
  added: [fastapi.BackgroundTasks, fastapi.APIRouter]
  patterns: [background-task-fire-and-forget, three-store-atomic-delete]
key_files:
  created:
    - backend/app/api/__init__.py
    - backend/app/api/index_router.py
  modified:
    - backend/app/models/schemas.py
    - backend/app/ingestion/embedder.py
    - backend/app/ingestion/graph_store.py
    - backend/app/ingestion/pipeline.py
decisions:
  - BackgroundTasks.add_task passes run_ingestion directly — no asyncio.run() wrapper; Starlette awaits async functions correctly
  - DELETE and GET routes use plain str repo_path query parameter — not IndexRequest model body
  - delete_embeddings_for_repo collects pgvector ids before DELETE to build FTS5 target set
metrics:
  duration: 2 min
  completed: 2026-03-18
  tasks_completed: 2
  files_modified: 6
---

# Phase 07 Plan 01: Index API Router Summary

**One-liner:** FastAPI index router with POST/GET/DELETE endpoints wiring BackgroundTasks to run_ingestion and three-store delete helpers for atomic repo cleanup.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add IndexRequest schema + delete helpers + clear_status | 5ca0b85 | schemas.py, embedder.py, graph_store.py, pipeline.py |
| 2 | Create app/api package + index_router.py | 13ce274 | api/__init__.py, api/index_router.py |

## What Was Built

- **IndexRequest** Pydantic model in `schemas.py` with `repo_path`, `languages` (default `["python", "typescript"]`), and optional `changed_files`
- **delete_embeddings_for_repo()** in `embedder.py`: collects node IDs from pgvector `code_embeddings`, deletes them, then deletes matching `code_fts` rows in SQLite
- **delete_graph_for_repo()** in `graph_store.py`: deletes all `graph_nodes` and `graph_edges` rows for a repo in a single connection
- **clear_status()** in `pipeline.py`: pops the repo entry from the in-memory `_status` dict
- **index_router.py**: three-endpoint FastAPI router — POST /index (non-blocking), GET /index/status (404 on miss), DELETE /index (three-store purge)
- **app/api/__init__.py**: empty package marker

## Verification Results

All three verification checks passed:
- Routes registered: `['/index', '/index/status', '/index']`
- Default languages: `['python', 'typescript']`
- `clear_status('/tmp/nonexistent')` runs without error
- Existing 59 passing tests still pass (3 pre-existing embedder failures unrelated to this plan)

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check

- [x] `backend/app/api/__init__.py` created
- [x] `backend/app/api/index_router.py` created
- [x] Commit 5ca0b85 exists
- [x] Commit 13ce274 exists
