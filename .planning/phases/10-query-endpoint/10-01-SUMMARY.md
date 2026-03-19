---
phase: 10-query-endpoint
plan: "01"
subsystem: api
tags: [sse, streaming, query-endpoint, graph-rag, fastapi]
dependency_graph:
  requires:
    - Phase 8 — graph_rag_retrieve (graph_rag.py)
    - Phase 9 — explore_stream (explorer.py)
    - Phase 6 — pipeline.get_status
    - Phase 5 — graph_store.load_graph
  provides:
    - POST /query SSE streaming endpoint
    - QueryRequest Pydantic model
    - app.state.graph_cache (lazy per-repo nx.DiGraph cache)
  affects:
    - backend/app/main.py (lifespan + router registration)
tech_stack:
  added: []
  patterns:
    - SSE streaming via StreamingResponse + async generator
    - asyncio.to_thread for blocking retrieval I/O
    - lazy graph cache in app.state keyed by repo_path
key_files:
  created:
    - backend/app/api/query_router.py
  modified:
    - backend/app/models/schemas.py
    - backend/app/main.py
decisions:
  - HTTPException raised before StreamingResponse so headers are not yet sent
  - asyncio.to_thread wraps both _get_graph and graph_rag_retrieve (blocking SQLite/pgvector I/O)
  - Citation dicts use plain Python dicts not model_dump — only VS Code extension fields included
  - OPTIONS added to CORS allow_methods for POST /query preflight
metrics:
  duration: "2 min"
  completed: "2026-03-19"
  tasks: 3
  files_modified: 3
requirements:
  - API-03
  - API-04
---

# Phase 10 Plan 01: Query Endpoint Summary

**One-liner:** POST /query SSE endpoint streaming token, citations, and done events via graph-RAG retrieval and LangChain explorer agent.

## What Was Built

Implemented the POST /query streaming endpoint that exposes the Phase 8 graph-RAG retrieval stack and Phase 9 explorer agent over HTTP SSE. A curl client (or VS Code extension) sends a `QueryRequest` JSON body and receives a stream of `token`, `citations`, and `done` server-sent events.

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | Add QueryRequest schema | e4d4bd9 | backend/app/models/schemas.py |
| 2 | Create query_router.py | 6dc9c8f | backend/app/api/query_router.py |
| 3 | Wire graph_cache + query_router into main.py | b6d9f1e | backend/app/main.py |

## Key Implementation Details

**SSE event sequence (API-04):**
- `event: token` — one per LLM token, `{"type": "token", "content": str}`
- `event: citations` — after last token, `{"type": "citations", "citations": [...]}`
- `event: done` — final, `{"type": "done", "retrieval_stats": dict}`
- `event: error` — on exception inside generator, `{"type": "error", "message": str}`

**400 gate before stream start:** `get_status(repo_path)` checked before `StreamingResponse` is returned. An unindexed or incomplete repo raises `HTTPException(400)` — headers have not been sent yet, so this is the safe location for HTTP errors (API-03).

**asyncio.to_thread pattern:** Both `_get_graph` and `graph_rag_retrieve` run blocking SQLite/pgvector I/O; both are wrapped in `asyncio.to_thread` to avoid blocking the event loop. `explore_stream` is an async generator and runs directly.

**Lazy graph cache:** `app.state.graph_cache = {}` initialized in lifespan. `_get_graph` checks cache before calling `load_graph`, avoiding repeated SQLite reads per query.

## Decisions Made

1. `HTTPException` raised before `StreamingResponse` — headers not yet sent; only safe error point
2. `asyncio.to_thread` on both graph load and retrieval — both are blocking I/O
3. Citation dicts are plain Python dicts, not `model_dump()` — includes only fields needed by VS Code extension (node_id, file_path, line_start, line_end, name, type)
4. `OPTIONS` added to CORS `allow_methods` — required for browser preflight on POST /query

## Verification Results

- `QueryRequest(question='x', repo_path='/tmp')` — no error, defaults 10/1 correct
- `router.routes[0].path` == `/query` — route exposed correctly
- App routes include both `/query` and `/index` — True True
- Full import chain: no ImportError or ValidationError
- Test suite: 80 passed (4 pre-existing embedder failures due to missing postgres env vars — unrelated to this plan)

## Deviations from Plan

None — plan executed exactly as written. (OPTIONS addition to allow_methods was explicitly called out in Task 3 action.)

## Self-Check: PASSED
