---
phase: 10-query-endpoint
plan: "02"
subsystem: api
tags: [sse, streaming, query-endpoint, testing, fastapi, monkeypatch]
dependency_graph:
  requires:
    - Phase 10 Plan 01 — query_router.py (POST /query SSE endpoint)
    - Phase 8 — graph_rag_retrieve (mocked in tests)
    - Phase 9 — explore_stream (mocked in tests)
  provides:
    - Unit tests for POST /query SSE endpoint
    - Proof of API-03 (400 guard) and API-04 (SSE sequence) correctness
  affects: []
tech_stack:
  added: []
  patterns:
    - FastAPI TestClient with stream=True + r.read() for SSE body consumption
    - unittest.mock.patch for lifespan init_db/init_pgvector_table as no-ops
    - monkeypatch at query_router namespace (from-import binding pattern)
    - _make_async_gen helper for async generator mocking
key_files:
  created:
    - backend/tests/test_query_router.py
  modified: []
decisions:
  - patch init_db/init_pgvector_table at app.main namespace to decouple TestClient from postgres
  - r.read() called inside client.stream() context to materialize body before context closes
  - _read_stream() helper centralizes the read pattern for streaming tests
metrics:
  duration: "3 min"
  completed: "2026-03-19"
  tasks: 2
  files_modified: 1
requirements:
  - API-03
  - API-04
---

# Phase 10 Plan 02: Query Router Tests Summary

**One-liner:** 9 unit tests for POST /query SSE endpoint using TestClient + monkeypatch, covering 400 guards, full SSE event sequence, citations fields, error events, and Content-Type header.

## What Was Built

Created `backend/tests/test_query_router.py` with 9 pytest tests that verify the complete behavior of the POST /query SSE streaming endpoint without any real API calls, database connections, or postgres env vars. All external I/O is mocked at the `app.api.query_router` namespace; lifespan database initialization is patched as no-ops.

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | Create test_query_router.py with full SSE coverage | e92b663 | backend/tests/test_query_router.py |
| 2 | Verify full test suite still passes | e92b663 | (verification only — no new files) |

## Key Implementation Details

**Test coverage (9 tests):**
- `test_unindexed_repo_returns_400` — `get_status` returns `None` → 400
- `test_indexing_in_progress_returns_400` — `get_status` returns `IndexStatus(status="running")` → 400
- `test_happy_path_yields_token_events` — 2 tokens → 2 `event: token` lines in body
- `test_happy_path_yields_citations_event` — `event: citations` data JSON contains `node_id`
- `test_happy_path_yields_done_event` — `event: done` data JSON has `retrieval_stats` key
- `test_event_order` — event lines are exactly `[token, token, citations, done]`
- `test_error_event_on_retrieval_failure` — `graph_rag_retrieve` raises → `event: error` with message
- `test_citations_contain_required_fields` — all 6 VS Code extension fields present
- `test_content_type_is_text_event_stream` — header starts with `text/event-stream`

**Streaming pattern:** `r.read()` called inside `client.stream(...)` context manager before accessing `r.text`. Body access after the context closes raises `httpx.ResponseNotRead`.

**Lifespan isolation:** `patch("app.main.init_db")` and `patch("app.main.init_pgvector_table")` applied as no-ops inside the `client` fixture, preventing postgres validation errors when lifespan runs.

**Async generator mock:** `_make_async_gen(*tokens)` produces an async generator function compatible with `explore_stream`'s signature `(nodes, question, **kwargs)`.

## Decisions Made

1. `r.read()` inside `client.stream()` context — `r.text` is only available after the body is fully read; accessing it after the context manager exits raises `ResponseNotRead`
2. `patch("app.main.init_db/init_pgvector_table")` at lifespan call site — avoids postgres env var requirement in tests using TestClient with lifespan
3. `_read_stream()` helper — DRY pattern for read-then-return-body to avoid repeating `r.read()` in every streaming test

## Verification Results

- `pytest backend/tests/test_query_router.py -v` → 9 passed
- `pytest backend/tests/ -q` → 89 passed (was 80), 4 pre-existing embedder failures (postgres missing) — no regressions

## Deviations from Plan

**1. [Rule 3 - Blocking] Patched lifespan db init to avoid postgres dependency**
- **Found during:** Task 1
- **Issue:** `TestClient(app)` triggers `lifespan`, which calls `init_pgvector_table()` → `pydantic_settings.ValidationError` for missing postgres env vars
- **Fix:** Added `patch("app.main.init_db", return_value=None)` and `patch("app.main.init_pgvector_table", return_value=None)` inside the `client` fixture
- **Files modified:** backend/tests/test_query_router.py
- **Commit:** e92b663

**2. [Rule 1 - Bug] Changed `r.text` access to use `r.read()` inside stream context**
- **Found during:** Task 1
- **Issue:** `r.text` outside `client.stream()` context raises `httpx.ResponseNotRead`; body must be materialized with `r.read()` while the connection is open
- **Fix:** Added `r.read()` inside every `with client.stream(...)` block; added `_read_stream()` helper
- **Files modified:** backend/tests/test_query_router.py
- **Commit:** e92b663

## Self-Check: PASSED
