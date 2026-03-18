---
phase: 07-index-endpoint
plan: 02
subsystem: api
tags: [fastapi, cors, middleware, smoke-test, main]
dependency_graph:
  requires:
    - phase: 07-01
      provides: index_router with POST/GET/DELETE /index endpoints
  provides:
    - CORSMiddleware wired into FastAPI app for vscode-webview and localhost origins
    - index_router included in app — all Phase 7 endpoints live over HTTP
    - Concurrent DELETE guard on pipeline status write
  affects: [phase-08-graph-rag, backend/app/main.py]
tech-stack:
  added: [fastapi.middleware.cors.CORSMiddleware]
  patterns: [middleware-before-router registration, allow_origin_regex for vscode-webview, guard-final-write-against-concurrent-delete]
key-files:
  created: []
  modified:
    - backend/app/main.py
    - backend/app/ingestion/pipeline.py

key-decisions:
  - "CORSMiddleware registered before include_router — Starlette middleware wraps full app stack; registration order matters for OPTIONS preflight interception"
  - "allow_credentials=True omitted — combining wildcard allow_origin_regex with allow_credentials causes browser CORS rejection"
  - "allow_origin_regex=r'vscode-webview://.*' uses raw string — backslash in .* must not be consumed by Python string processing"
  - "run_ingestion final status write guarded with repo_path presence check — prevents stale 'complete' status being written after concurrent DELETE"

patterns-established:
  - "CORS-before-router: add_middleware(CORSMiddleware) must precede include_router in Starlette apps"
  - "Status write guard: always check that _status still contains repo_path before final write in async background tasks"

requirements-completed: [API-05, API-07]

# Metrics
duration: ~5 min
completed: 2026-03-18
tasks_completed: 2
files_modified: 2
---

# Phase 07 Plan 02: Wire CORSMiddleware + main.py + Live Smoke Test Summary

**FastAPI app wired with CORSMiddleware (vscode-webview regex + localhost:3000) and index_router; all 8 smoke-test checks pass including concurrent DELETE race-condition fix on pipeline status write.**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-03-18
- **Completed:** 2026-03-18
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- `main.py` updated: CORSMiddleware registered before `include_router` (correct Starlette order), with `allow_origin_regex=r"vscode-webview://.*"` and `allow_origins=["http://localhost:3000"]`
- All four Phase 7 endpoints (`GET /health`, `POST /index`, `GET /index/status`, `DELETE /index`) confirmed live via curl smoke tests
- Concurrent DELETE race condition fixed: `run_ingestion` guards its final `_status` write with a check that the repo_path is still present, preventing a stale `"complete"` status being written after a `DELETE /index` clears the entry

## Task Commits

Each task was committed atomically:

1. **Task 1: Register CORSMiddleware + index_router in main.py** - `c64676f` (feat)
2. **Deviation fix: Guard run_ingestion final status write against concurrent DELETE** - `9cbda0c` (fix)
3. **Task 2: Live smoke test checkpoint — human-verified approved** - (no code commit; verification complete)

**Plan metadata:** (this commit)

## Files Created/Modified

- `backend/app/main.py` — Added CORSMiddleware (before include_router) and index_router inclusion; preserved lifespan, init_db, init_pgvector_table, and /health endpoint unchanged
- `backend/app/ingestion/pipeline.py` — Added guard in `run_ingestion` to check `repo_path in _status` before writing final `"complete"` status, preventing stale write after concurrent DELETE

## Smoke Test Results (all 8 pass)

| # | Check | Result |
|---|-------|--------|
| 1 | GET /health | `{"status":"ok","version":"1.0.0"}` |
| 2 | POST /index | `{"status":"pending","repo_path":"..."}` (non-blocking) |
| 3 | GET /index/status (unknown repo) | HTTP 404 |
| 4 | GET /index/status (known repo) | `{"status":"running",...}` |
| 5 | CORS preflight vscode-webview://abc123 | `access-control-allow-origin: vscode-webview://abc123` |
| 6 | DELETE /index | `{"status":"deleted","repo_path":"..."}` |
| 7 | GET /index/status after delete | HTTP 404 |
| 8 | CORS localhost:3000 | `access-control-allow-origin: http://localhost:3000` |

## Decisions Made

- CORSMiddleware placed before `include_router` — Starlette middleware wraps the full ASGI app; adding it after routers risks missing CORS headers on some preflight responses
- `allow_credentials=True` deliberately omitted — browsers reject CORS responses that pair wildcard `allow_origin_regex` with `allow_credentials=True`
- Raw string `r"vscode-webview://.*"` required to preserve the backslash in `.*` without Python string processing consuming it
- Final status write in `run_ingestion` guarded with `if repo_path in _status` — required for correctness when DELETE races with background ingestion

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Guard run_ingestion final status write against concurrent DELETE**
- **Found during:** Task 2 (live smoke test — DELETE followed by GET /index/status)
- **Issue:** After `DELETE /index`, calling `GET /index/status` returned HTTP 404 correctly, but a background ingestion still running would eventually overwrite the cleared `_status` entry with `"complete"`, making status queryable again after deletion
- **Fix:** Added `if repo_path in _status:` guard before the final `_status[repo_path] = final_status` write in `pipeline.py`
- **Files modified:** `backend/app/ingestion/pipeline.py`
- **Verification:** Smoke test 7 (GET /index/status after DELETE) returns HTTP 404 consistently
- **Committed in:** `9cbda0c` (separate fix commit during Task 2)

---

**Total deviations:** 1 auto-fixed (Rule 1 — bug)
**Impact on plan:** Fix required for correct DELETE semantics. No scope creep.

## Issues Encountered

None beyond the concurrent DELETE race condition handled above.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Phase 7 fully complete: all six requirements verified (API-01, API-02, API-05, API-06, API-07, API-08)
- FastAPI app serves all endpoints live over HTTP with correct CORS headers
- Phase 8 (Graph RAG) can proceed — backend is accessible and all ingestion/query infrastructure is in place

## Self-Check

- [x] `backend/app/main.py` modified (CORSMiddleware + include_router)
- [x] `backend/app/ingestion/pipeline.py` modified (status write guard)
- [x] Commit `c64676f` exists (feat: register CORSMiddleware + index_router)
- [x] Commit `9cbda0c` exists (fix: guard run_ingestion final status write)
- [x] All 8 smoke tests confirmed passing by human verification

---
*Phase: 07-index-endpoint*
*Completed: 2026-03-18*
