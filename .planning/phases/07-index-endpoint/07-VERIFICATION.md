---
phase: 07-index-endpoint
verified: 2026-03-18T00:00:00Z
status: human_needed
score: 8/8 must-haves verified
human_verification:
  - test: "POST /index non-blocking response time"
    expected: "Response returns {status: pending, repo_path} immediately, before ingestion completes"
    why_human: "BackgroundTasks dispatch is correct in code but actual non-blocking wall-clock behavior requires a live server to confirm"
  - test: "CORS preflight from vscode-webview://abc123 origin"
    expected: "Response includes access-control-allow-origin: vscode-webview://abc123"
    why_human: "allow_origin_regex wiring is correct in code; actual header emission requires HTTP-level verification"
---

# Phase 7: Index Endpoint Verification Report

**Phase Goal:** The ingestion pipeline is accessible over HTTP with non-blocking background execution
**Verified:** 2026-03-18
**Status:** human_needed — all automated checks pass; 2 items need live-server confirmation
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | POST /index starts ingestion as BackgroundTask and returns {status: pending, repo_path} without awaiting completion | VERIFIED | `index_router.py:14` — `background_tasks.add_task(run_ingestion, ...)` followed by immediate `return {"status": "pending", ...}` |
| 2 | GET /index/status?repo_path=... returns live IndexStatus or 404 if not found | VERIFIED | `index_router.py:23-29` — calls `get_status(repo_path)`, raises `HTTPException(404)` on None |
| 3 | DELETE /index?repo_path=... removes all pgvector, FTS5, and SQLite graph data for that repo | VERIFIED | `index_router.py:32-38` — calls `delete_embeddings_for_repo`, `delete_graph_for_repo`, `clear_status` in sequence |
| 4 | IndexRequest Pydantic model validates repo_path, languages, and optional changed_files | VERIFIED | `schemas.py:32-35` — `class IndexRequest(BaseModel)` with all three fields and correct defaults |
| 5 | GET /health returns {status: ok, version: 1.0.0} | VERIFIED | `main.py:32-34` — `@app.get("/health")` returns `{"status": "ok", "version": "1.0.0"}` |
| 6 | CORS headers allow requests from vscode-webview://* origins | VERIFIED (code) | `main.py:24` — `allow_origin_regex=r"vscode-webview://.*"` present; live preflight needs human confirmation |
| 7 | CORS headers allow requests from http://localhost:3000 | VERIFIED | `main.py:23` — `allow_origins=["http://localhost:3000"]` present |
| 8 | Concurrent DELETE race condition guarded — final status write skipped if repo deleted mid-ingestion | VERIFIED | `pipeline.py:88` — `if repo_path in _status:` guard before final `_status[repo_path] = result` |

**Score:** 8/8 truths verified (2 need live-server human confirmation)

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/app/models/schemas.py` | IndexRequest Pydantic model | VERIFIED | `class IndexRequest(BaseModel)` at line 32; fields: `repo_path: str`, `languages: list[str] = ["python", "typescript"]`, `changed_files: list[str] \| None = None` |
| `backend/app/ingestion/embedder.py` | delete_embeddings_for_repo function | VERIFIED | Defined at line 166; selects node IDs from pgvector, deletes from `code_embeddings`, conditionally deletes from `code_fts` via SQLite |
| `backend/app/ingestion/graph_store.py` | delete_graph_for_repo function | VERIFIED | Defined at line 112; deletes from `graph_nodes` and `graph_edges` using `_get_conn(_db_path())` pattern |
| `backend/app/ingestion/pipeline.py` | clear_status function | VERIFIED | Defined at line 21; `_status.pop(repo_path, None)` — correct no-op-on-miss semantics |
| `backend/app/api/index_router.py` | POST /index, GET /index/status, DELETE /index endpoints | VERIFIED | All 3 routes present; router exported as `router` |
| `backend/app/api/__init__.py` | Empty package marker | VERIFIED | File exists, empty (blank line only) |
| `backend/app/main.py` | CORSMiddleware registration + index_router inclusion | VERIFIED | `add_middleware(CORSMiddleware, ...)` at line 21, `include_router(index_router)` at line 29 |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `index_router.py` | `pipeline.py` | `background_tasks.add_task(run_ingestion, ...)` | WIRED | Line 14-18: `add_task` receives `run_ingestion` directly (no asyncio.run wrapper — correct) |
| `index_router.py` | `embedder.py` | `delete_embeddings_for_repo(repo_path)` | WIRED | Line 35: called unconditionally in DELETE handler |
| `index_router.py` | `graph_store.py` | `delete_graph_for_repo(repo_path)` | WIRED | Line 36: called unconditionally in DELETE handler |
| `main.py` | `index_router.py` | `app.include_router(index_router)` | WIRED | Line 29: router imported from `app.api.index_router` and included |
| `main.py` | `CORSMiddleware` | `app.add_middleware(CORSMiddleware, ...)` | WIRED | Lines 21-27: middleware registered before `include_router` (correct Starlette order) |

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| API-01 | 07-01 | POST /index accepts IndexRequest, starts BackgroundTask, returns {status: pending, repo_path} | SATISFIED | `index_router.py:11-20` — `@router.post("/index")` with `background_tasks.add_task(run_ingestion, ...)` and immediate return |
| API-02 | 07-01 | GET /index/status?repo_path=... returns IndexStatus | SATISFIED | `index_router.py:23-29` — `@router.get("/index/status", response_model=IndexStatus)` calls `get_status()`, raises 404 on None |
| API-05 | 07-02 | GET /health returns {status: ok, version: 1.0.0} | SATISFIED | `main.py:32-34` — route defined, returns exact shape |
| API-06 | 07-01 | DELETE /index?repo_path=... removes all pgvector, FTS5, SQLite data for repo | SATISFIED | `index_router.py:32-38` — calls all three delete functions: `delete_embeddings_for_repo`, `delete_graph_for_repo`, `clear_status` |
| API-07 | 07-02 | CORS allows vscode-webview://* and http://localhost:3000 | SATISFIED (code) | `main.py:23-24` — both origins configured; live behavior needs human confirmation |
| API-08 | 07-01 | app/config.py uses pydantic-settings; all secrets from .env; no hardcoded values | SATISFIED | `config.py:2` uses `pydantic_settings.BaseSettings`; no secrets in `index_router.py` or `main.py` |

No orphaned requirements: REQUIREMENTS.md maps API-01, API-02, API-05, API-06, API-07, API-08 to Phase 7 — all six are claimed by plans 07-01 and 07-02. Full coverage confirmed.

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | — | — | No anti-patterns found |

Scan notes:
- "placeholder" matches in `embedder.py` and `graph_store.py` are SQL parameterized query placeholders, not stub code
- No `TODO`, `FIXME`, `XXX`, or `HACK` comments in any phase 7 file
- No empty handler bodies (`return null`, `return {}`, `return []`)
- No console.log-only implementations

---

## Human Verification Required

### 1. POST /index Non-Blocking Response

**Test:** Start server (`uvicorn app.main:app --reload --port 8000`), run `curl -s -X POST http://localhost:8000/index -H "Content-Type: application/json" -d '{"repo_path":"/tmp/test-repo","languages":["python"]}'`
**Expected:** `{"status":"pending","repo_path":"/tmp/test-repo"}` returned immediately, not after ingestion completes (ingestion of a real repo can take seconds)
**Why human:** BackgroundTasks wiring is verifiably correct in code (`add_task` with no await), but actual wall-clock non-blocking behavior requires a live server call against a non-trivial repo_path to observe

### 2. CORS Preflight from vscode-webview Origin

**Test:** Run `curl -s -X OPTIONS http://localhost:8000/index -H "Origin: vscode-webview://abc123" -H "Access-Control-Request-Method: POST" -D -`
**Expected:** Response headers include `access-control-allow-origin: vscode-webview://abc123`
**Why human:** `allow_origin_regex=r"vscode-webview://.*"` is present and syntactically correct, but regex matching behavior and header emission by Starlette's CORSMiddleware must be confirmed at the HTTP level

---

## Gaps Summary

No gaps found. All eight must-have truths are satisfied in the codebase. Both human verification items are confirmatory checks on behavior that is correctly implemented in code — they are not risks of failure but standard HTTP-level smoke tests already documented as passing in the 07-02-SUMMARY.md (smoke test items 2 and 5).

The SUMMARY records human approval of all 8 smoke tests on 2026-03-18. Automated code verification confirms every wiring path is correctly implemented. No re-verification is needed unless the human confirmation items above are re-run and produce unexpected results.

---

_Verified: 2026-03-18_
_Verifier: Claude (gsd-verifier)_
