---
phase: 05-embedder
plan: "03"
subsystem: embedder-tests
tags: [testing, graph-store, embedder, fts5, pgvector, mocking]

# Dependency graph
requires:
  - phase: 05-embedder
    plan: "01"
    provides: graph_store.py (save_graph, load_graph, delete_nodes_for_files)
  - phase: 05-embedder
    plan: "02"
    provides: embedder.py (init_pgvector_table, embed_and_store, EMBED_BATCH_SIZE)
provides:
  - backend/tests/test_embedder.py — full unit test coverage for graph_store.py and embedder.py
  - backend/app/main.py — init_pgvector_table() wired into FastAPI lifespan
affects: [06-pipeline]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - monkeypatch module-level functions to redirect SQLite path in tests
    - patch app.ingestion.embedder.register_vector (not pgvector.psycopg2.register_vector) — correct target for module-level imports
    - patch app.ingestion.embedder.execute_values — same principle
    - MagicMock psycopg2 connection with context manager __enter__/__exit__ stubs

key-files:
  created:
    - backend/tests/test_embedder.py
  modified:
    - backend/app/main.py
    - backend/app/ingestion/embedder.py

key-decisions:
  - "Patch targets must use embedder module namespace (app.ingestion.embedder.register_vector) not the origin module (pgvector.psycopg2.register_vector) — Python resolves module-level from-imports at load time"
  - "FTS5 content='' removed from _init_fts_table — contentless tables do not store values; UNINDEXED columns return NULL and DELETE by column is a no-op in contentless mode"
  - "init_pgvector_table() placed after init_db() in lifespan — CREATE EXTENSION vector must precede CREATE TABLE with vector(1536) column"

requirements-completed: [EMBED-01, EMBED-02, EMBED-03, EMBED-04, EMBED-05, EMBED-06, STORE-01, STORE-02, STORE-03]

# Metrics
duration: 5min
completed: 2026-03-18
---

# Phase 05 Plan 03: Embedder Tests and Lifespan Wiring Summary

**One-liner:** 10-test suite covering SQLite graph round-trip and mocked OpenAI embed_and_store, plus init_pgvector_table wired into FastAPI lifespan; fixed FTS5 contentless-table bug in embedder.py.

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-18T12:43:18Z
- **Completed:** 2026-03-18T12:48:00Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- `test_embedder.py` created with 10 tests:
  - 6 graph_store tests (STORE-01/02/03): round-trip save/load, empty load, overwrite deduplication, delete by file_path, noop on empty list, repo isolation
  - 4 embedder unit tests (EMBED-01/03/04/05/06): returns count, FTS5 name MATCH, upsert idempotency, batch size constant
- Fixed FTS5 `content=''` bug in `embedder._init_fts_table` — contentless tables do not store column values and do not support DELETE by column value
- Corrected mock patch targets to `app.ingestion.embedder.*` namespace (module-level from-imports bind at load time)
- `main.py` lifespan updated: `init_pgvector_table()` called after `init_db()`
- All 57 tests pass (47 prior + 10 new)

## Task Commits

Each task was committed atomically:

1. **Task 1: Write test_embedder.py covering both graph_store and embedder** — `a102d25` (feat)
2. **Task 2: Wire init_pgvector_table into FastAPI lifespan** — `1185c16` (feat)

## Files Created/Modified

- `backend/tests/test_embedder.py` — 10 unit tests for graph_store.py and embedder.py; uses tmp_db fixture and mock_openai_client fixture
- `backend/app/main.py` — added `from app.ingestion.embedder import init_pgvector_table`; added `init_pgvector_table()` call in lifespan
- `backend/app/ingestion/embedder.py` — removed `content=''` from FTS5 CREATE VIRTUAL TABLE (bug fix)

## Decisions Made

- Patch targets use `app.ingestion.embedder.register_vector` and `app.ingestion.embedder.execute_values` — when a module does `from x import y`, patching `x.y` after import does not affect the already-bound name in the target module; must patch the local binding
- FTS5 without `content=''` stores all column values in the table itself — this is what the code intended, but `content=''` (contentless) mode silently broke both SELECT and DELETE
- `init_pgvector_table()` after `init_db()` in lifespan — ordering ensures the pgvector extension is activated before the DDL that uses `vector(1536)`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Wrong patch targets for register_vector and execute_values**
- **Found during:** Task 1 (test run)
- **Issue:** Plan specified `patch("pgvector.psycopg2.register_vector")` and `patch("psycopg2.extras.execute_values")` — both fail because embedder.py uses `from ... import` which binds the name at module load time
- **Fix:** Changed patch targets to `app.ingestion.embedder.register_vector` and `app.ingestion.embedder.execute_values`
- **Files modified:** `backend/tests/test_embedder.py`
- **Commit:** a102d25

**2. [Rule 1 - Bug] FTS5 `content=''` makes node_id unreadable and DELETE a no-op**
- **Found during:** Task 1 (test failures for FTS5 MATCH and upsert idempotency)
- **Issue:** `_init_fts_table` used `content=''` (contentless FTS5 mode). In this mode the table does not store actual column values — SELECT node_id returns NULL, and DELETE WHERE node_id = ? is a no-op. This meant the upsert DELETE step silently did nothing, producing duplicate rows on second insert.
- **Fix:** Removed `content=''` from the CREATE VIRTUAL TABLE statement in `embedder._init_fts_table`
- **Files modified:** `backend/app/ingestion/embedder.py`
- **Commit:** a102d25

## Issues Encountered

None beyond the auto-fixed bugs above.

## User Setup Required

None — all embedder unit tests run without Docker. Integration tests (requiring a live Postgres+pgvector) are noted in docstrings but not run in this phase.

## Next Phase Readiness

- All Phase 5 requirements (EMBED-01 through EMBED-06, STORE-01 through STORE-03) are verified by tests
- `init_pgvector_table()` runs on every app startup — pgvector table ready before any Phase 6 ingestion call
- Phase 6 (Ingestion Pipeline) can call `save_graph` / `embed_and_store` with confidence that both the SQLite and pgvector stores are initialized

---
*Phase: 05-embedder*
*Completed: 2026-03-18*

## Self-Check: PASSED

- FOUND: backend/tests/test_embedder.py
- FOUND: backend/app/main.py (init_pgvector_table: 2 occurrences — import + call)
- FOUND: backend/app/ingestion/embedder.py (FTS5 content='' removed)
- FOUND: commit a102d25
- FOUND: commit 1185c16
