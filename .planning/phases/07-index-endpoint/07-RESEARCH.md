# Phase 7: Index Endpoint - Research

**Researched:** 2026-03-18
**Domain:** FastAPI HTTP endpoints — BackgroundTasks, CORS, pydantic-settings, DELETE cleanup
**Confidence:** HIGH

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| API-01 | `POST /index` accepts `IndexRequest{repo_path, languages}`, starts ingestion as BackgroundTask, returns `{status: "pending", repo_path}` | FastAPI BackgroundTasks inject via route parameter; `background_tasks.add_task(run_ingestion, ...)` fires after response |
| API-02 | `GET /index/status?repo_path=...` returns `IndexStatus` | `get_status(repo_path)` already exists in pipeline.py; expose as query-param endpoint returning IndexStatus model |
| API-05 | `GET /health` returns `{status: "ok", version: "1.0.0"}` | Already implemented in main.py — needs no change; verify in this phase |
| API-06 | `DELETE /index?repo_path=...` removes all pgvector, FTS5, SQLite data for repo | No single delete function exists yet; must add `delete_repo_data(repo_path)` to embedder + graph_store modules |
| API-07 | CORS allows `vscode-webview://*` and `http://localhost:3000` | `allow_origin_regex` for vscode-webview pattern + explicit `http://localhost:3000` in allow_origins list |
| API-08 | `app/config.py` uses pydantic-settings; all secrets from `.env`; no hardcoded values | config.py already uses pydantic-settings v2 with lru_cache — already complete; verify no new hardcoded values in router |
</phase_requirements>

---

## Summary

Phase 7 wires the fully-implemented ingestion pipeline (Phase 6) to HTTP. The core work is: creating a FastAPI router with four endpoints, configuring CORS for VS Code webview origins, and adding a repo-scoped delete helper to the embedder and graph_store modules.

The project already has `run_ingestion()` and `get_status()` in `pipeline.py`, `IndexStatus` in `schemas.py`, and the `GET /health` stub in `main.py`. Phase 7 is primarily integration work — no new domain logic is introduced. The one non-trivial piece is DELETE cleanup: three separate stores (pgvector, SQLite FTS5, SQLite graph tables) must all be purged atomically for a given `repo_path`.

CORS needs `allow_origin_regex=r"vscode-webview://.*"` combined with `allow_origins=["http://localhost:3000"]` because `vscode-webview://` is a custom protocol that cannot be whitelisted with a plain string origin — it requires regex matching. `allow_credentials` must stay `False` (or omitted) when combining wildcard regex with explicit origins, otherwise browsers reject the configuration.

**Primary recommendation:** Create `app/api/index_router.py` with all four endpoints, add a `delete_repo_data(repo_path)` function to `embedder.py` and expose repo-delete from `graph_store.py`, then register the router + CORSMiddleware in `main.py`.

---

## Standard Stack

### Core (already in requirements.txt — no new installs needed)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| fastapi | >=0.115.0 | HTTP framework with BackgroundTasks, routing, middleware | Already in use |
| uvicorn[standard] | latest | ASGI server | Already in use |
| pydantic-settings | >=2.0.0 | Settings management via BaseSettings | Already in use (config.py) |
| pydantic | v2 (via fastapi) | Request/response model validation | Already in use (schemas.py) |

### No new dependencies required

All libraries needed for Phase 7 are already installed. `fastapi.middleware.cors.CORSMiddleware` is part of `starlette` which is a FastAPI dependency — no separate install.

**Installation:**
```bash
# No new packages — all dependencies already in requirements.txt
```

---

## Architecture Patterns

### Recommended Project Structure

```
backend/app/
├── api/
│   ├── __init__.py
│   └── index_router.py      # POST /index, GET /index/status, DELETE /index
├── ingestion/
│   ├── embedder.py          # ADD: delete_embeddings_for_repo(repo_path)
│   ├── graph_store.py       # ADD: delete_graph_for_repo(repo_path)
│   └── pipeline.py          # EXISTING: run_ingestion(), get_status()
├── models/
│   └── schemas.py           # ADD: IndexRequest Pydantic model
├── config.py                # EXISTING — no changes needed
└── main.py                  # ADD: register router + CORSMiddleware
```

### Pattern 1: BackgroundTasks for Non-Blocking POST /index

**What:** FastAPI injects a `BackgroundTasks` instance into the route function. Call `background_tasks.add_task(fn, *args)` before returning the response. The task runs after the HTTP response is sent.

**When to use:** When the operation is long-running but must return immediately to the caller.

**Critical detail:** `run_ingestion` is an `async def`. Passing an async function to `add_task` is supported — FastAPI/Starlette will `await` it correctly in the background.

```python
# Source: https://fastapi.tiangolo.com/tutorial/background-tasks/
from fastapi import APIRouter, BackgroundTasks
from app.ingestion.pipeline import run_ingestion
from app.models.schemas import IndexRequest

router = APIRouter()

@router.post("/index")
async def start_index(request: IndexRequest, background_tasks: BackgroundTasks):
    background_tasks.add_task(
        run_ingestion,
        request.repo_path,
        request.languages,
        request.changed_files,
    )
    return {"status": "pending", "repo_path": request.repo_path}
```

### Pattern 2: GET /index/status with Query Parameter

**What:** FastAPI auto-maps plain `str` function parameters to query parameters.

```python
from fastapi import HTTPException
from app.ingestion.pipeline import get_status

@router.get("/index/status")
async def index_status(repo_path: str):
    status = get_status(repo_path)
    if status is None:
        raise HTTPException(status_code=404, detail="No index found for repo_path")
    return status
```

### Pattern 3: DELETE /index with Query Parameter

**What:** DELETE endpoints can accept query parameters the same way GET does — plain `str` parameter in function signature.

```python
@router.delete("/index")
async def delete_index(repo_path: str):
    # Must purge all three stores:
    # 1. pgvector (code_embeddings table)
    # 2. SQLite FTS5 (code_fts table)
    # 3. SQLite graph tables (graph_nodes, graph_edges)
    from app.ingestion.embedder import delete_embeddings_for_repo
    from app.ingestion.graph_store import delete_graph_for_repo
    delete_embeddings_for_repo(repo_path)
    delete_graph_for_repo(repo_path)
    return {"status": "deleted", "repo_path": repo_path}
```

### Pattern 4: CORS Configuration for vscode-webview

**What:** `vscode-webview://` is a custom protocol scheme. It cannot be listed as a plain string origin because it uses a dynamic UUID suffix (e.g., `vscode-webview://abc123xyz...`). Use `allow_origin_regex` for the webview pattern and list `http://localhost:3000` explicitly in `allow_origins`.

**Critical:** Do NOT set `allow_credentials=True` when using wildcard regex — browsers reject that combination.

```python
# Source: https://fastapi.tiangolo.com/tutorial/cors/
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_origin_regex=r"vscode-webview://.*",
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
    allow_credentials=False,
)
```

### Pattern 5: IndexRequest Pydantic Model

Add to `schemas.py` — used as the POST /index request body:

```python
class IndexRequest(BaseModel):
    repo_path: str
    languages: list[str] = ["python", "typescript"]
    changed_files: list[str] | None = None
```

### Pattern 6: Router Registration in main.py

```python
from app.api.index_router import router as index_router

app.include_router(index_router)
```

Register CORSMiddleware before including routers (middleware order matters in Starlette).

### Anti-Patterns to Avoid

- **Blocking the route handler:** Do NOT `await run_ingestion(...)` directly in the route — that blocks the HTTP response until ingestion completes, violating API-01.
- **Pydantic model as DELETE query param:** FastAPI interprets Pydantic models as request bodies. Use plain `str repo_path` parameter for query-param-style DELETE, not a model wrapper.
- **Using `allow_credentials=True` with `allow_origin_regex`:** Browsers reject `Access-Control-Allow-Credentials: true` when the origin was matched by wildcard/regex. Keep credentials False for this use case.
- **Hardcoding CORS origins in router:** CORS middleware is app-level, not router-level. Register it in `main.py` only.
- **Forgetting FTS5 cleanup in DELETE:** The DELETE endpoint must purge all three stores. FTS5 is in SQLite (separate from graph tables but same DB file). Missing it leaves stale search data.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Background task execution | Custom thread pool / asyncio.create_task at module level | `BackgroundTasks` from fastapi | Lifecycle-managed, exception-safe, no orphaned tasks |
| CORS header injection | Custom middleware inspecting `Origin` header | `CORSMiddleware` from starlette | Handles preflight OPTIONS, credential constraints, header lists |
| Request body validation | Manual `json.loads()` + dict checks | Pydantic `BaseModel` request body | Type coercion, error messages, OpenAPI schema auto-generation |
| Settings management | `os.getenv()` scattered in router | `get_settings()` from `app.config` | Already implemented with lru_cache; use it |

**Key insight:** FastAPI's BackgroundTasks is intentionally simple — for this use case (running one async ingestion job per request), it is exactly right. Don't add Celery/Redis complexity to satisfy what a 5-line BackgroundTasks call solves.

---

## Common Pitfalls

### Pitfall 1: run_ingestion is async — BackgroundTasks handles it correctly, but don't wrap it

**What goes wrong:** Developer wraps `run_ingestion` in `asyncio.run()` or `asyncio.to_thread()` before passing to `add_task`, breaking the event loop.
**Why it happens:** Habit from other frameworks where background tasks are always sync.
**How to avoid:** Pass `run_ingestion` directly to `add_task`. Starlette's BackgroundTasks correctly awaits async task functions.
**Warning signs:** `RuntimeError: This event loop is already running` in logs.

### Pitfall 2: Incomplete DELETE — only purging one store

**What goes wrong:** DELETE endpoint calls only `delete_graph_for_repo()` but leaves pgvector `code_embeddings` rows and FTS5 `code_fts` rows intact.
**Why it happens:** graph_store.py and embedder.py are separate modules with no unified delete function.
**How to avoid:** Add `delete_embeddings_for_repo(repo_path)` to `embedder.py` (DELETE from `code_embeddings WHERE repo_path = ?` + DELETE from `code_fts WHERE ...` — use FTS5 match or rowid). Call both in the DELETE route.
**Warning signs:** After DELETE, `GET /index/status` returns 404 (good) but `POST /index` on the same repo produces duplicate/stale search results.

### Pitfall 3: FTS5 delete by repo_path is non-trivial

**What goes wrong:** `code_fts` is a FTS5 virtual table that does NOT have a `repo_path` column — it only has `node_id`, `name`, `file_path` (per embedder.py). Deleting by repo_path requires knowing which node_ids belong to that repo.
**Why it happens:** FTS5 was designed for text search, not relational filtering.
**How to avoid:** Join against `graph_nodes` (which HAS `repo_path`) to get all `node_id` values, then DELETE from `code_fts WHERE node_id IN (...)`. Alternatively, add `repo_path` as UNINDEXED column to `code_fts` when creating the table — but the current schema doesn't have it. The safest path: query `code_embeddings` in pgvector (which has `repo_path`) to get all `id` values, then bulk DELETE from `code_fts`.
**Warning signs:** FTS5 rows persist after DELETE endpoint is called.

### Pitfall 4: CORS middleware registered after router

**What goes wrong:** `app.include_router(...)` appears before `app.add_middleware(CORSMiddleware, ...)` in main.py — CORS headers may not be applied.
**Why it happens:** In Starlette, middleware wraps the entire application stack. Registration order matters.
**How to avoid:** Add CORSMiddleware in the `lifespan` setup area or immediately after `app = FastAPI(...)`, before `include_router` calls.
**Warning signs:** Browser console shows `No 'Access-Control-Allow-Origin' header` despite middleware being "added."

### Pitfall 5: vscode-webview origin matching fails with plain string

**What goes wrong:** `allow_origins=["vscode-webview://*"]` does NOT match the actual origin `vscode-webview://abc123...`. String matching in CORSMiddleware is exact (not glob).
**Why it happens:** Glob syntax is not supported in `allow_origins` — it only supports exact strings or `["*"]` (allow all).
**How to avoid:** Use `allow_origin_regex=r"vscode-webview://.*"` which uses Python `re.fullmatch` against the incoming Origin header.
**Warning signs:** OPTIONS preflight from VS Code extension returns 403 or no CORS headers.

---

## Code Examples

Verified patterns from official sources:

### BackgroundTasks — Basic Add Task Pattern

```python
# Source: https://fastapi.tiangolo.com/tutorial/background-tasks/
from fastapi import BackgroundTasks, FastAPI

app = FastAPI()

@app.post("/index")
async def start_index(request: IndexRequest, background_tasks: BackgroundTasks):
    background_tasks.add_task(run_ingestion, request.repo_path, request.languages)
    return {"status": "pending", "repo_path": request.repo_path}
```

### CORSMiddleware — Combined Origins and Regex

```python
# Source: https://fastapi.tiangolo.com/tutorial/cors/
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_origin_regex=r"vscode-webview://.*",
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)
```

### IndexRequest Schema (add to schemas.py)

```python
class IndexRequest(BaseModel):
    repo_path: str
    languages: list[str] = ["python", "typescript"]
    changed_files: list[str] | None = None
```

### delete_embeddings_for_repo — New function for embedder.py

```python
def delete_embeddings_for_repo(repo_path: str) -> None:
    """Remove all pgvector and FTS5 data for the given repo_path."""
    # 1. Get all node_ids for this repo from pgvector
    pg_conn = get_db_connection()
    register_vector(pg_conn)
    try:
        with pg_conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM code_embeddings WHERE repo_path = %s",
                (repo_path,)
            )
            node_ids = [row[0] for row in cur.fetchall()]
            cur.execute(
                "DELETE FROM code_embeddings WHERE repo_path = %s",
                (repo_path,)
            )
    finally:
        pg_conn.close()

    # 2. Delete from FTS5 by node_id
    if node_ids:
        db_path = _sqlite_db_path()
        conn = sqlite3.connect(db_path)
        try:
            placeholders = ",".join("?" * len(node_ids))
            conn.execute(
                f"DELETE FROM code_fts WHERE node_id IN ({placeholders})",
                node_ids,
            )
            conn.commit()
        finally:
            conn.close()
```

### delete_graph_for_repo — New function for graph_store.py

```python
def delete_graph_for_repo(repo_path: str) -> None:
    """Remove all graph_nodes and graph_edges for the given repo_path."""
    conn = _get_conn(_db_path())
    conn.execute("DELETE FROM graph_nodes WHERE repo_path = ?", (repo_path,))
    conn.execute("DELETE FROM graph_edges WHERE repo_path = ?", (repo_path,))
    conn.commit()
    conn.close()
```

### Full main.py after Phase 7

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.db.database import init_db
from app.ingestion.embedder import init_pgvector_table
from app.api.index_router import router as index_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    init_pgvector_table()
    yield

app = FastAPI(title="Nexus API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_origin_regex=r"vscode-webview://.*",
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

app.include_router(index_router)

@app.get("/health")
def health():
    return {"status": "ok", "version": "1.0.0"}
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `from pydantic import BaseSettings` | `from pydantic_settings import BaseSettings` | Pydantic v2 | Already handled in config.py |
| Manual CORS headers in response | `CORSMiddleware` from starlette | FastAPI 0.x | Declarative, handles preflight automatically |
| `@app.on_event("startup")` | `@asynccontextmanager lifespan` | FastAPI 0.93+ | Already using lifespan pattern in main.py |

**Deprecated/outdated:**
- `@app.on_event("startup")` / `@app.on_event("shutdown")`: Replaced by `lifespan` context manager — project already uses the modern pattern.

---

## Open Questions

1. **FTS5 code_fts table does not have a repo_path column**
   - What we know: The current `code_fts` schema is `(node_id UNINDEXED, name, file_path UNINDEXED)` — no `repo_path`.
   - What's unclear: Delete by repo_path must join via another table to identify affected node_ids.
   - Recommendation: Use `code_embeddings` pgvector table (which has `repo_path`) to collect `id` values, then delete from `code_fts WHERE node_id IN (...)`. This is the cleanest approach given current schema.

2. **Should DELETE /index also clear the in-memory `_status` dict?**
   - What we know: `pipeline._status` dict (keyed by repo_path) persists across requests. After DELETE, `GET /index/status` still returns the old status.
   - What's unclear: Whether this is correct behavior (stale status after delete?) or should return 404.
   - Recommendation: In the DELETE route, call `pipeline._status.pop(repo_path, None)` (or expose a `clear_status(repo_path)` function from pipeline.py) so subsequent status checks correctly return 404.

---

## Sources

### Primary (HIGH confidence)
- https://fastapi.tiangolo.com/tutorial/background-tasks/ — BackgroundTasks API, add_task signature, async task support
- https://fastapi.tiangolo.com/tutorial/cors/ — CORSMiddleware parameters, allow_origin_regex, credential constraints

### Secondary (MEDIUM confidence)
- https://fastapi.tiangolo.com/advanced/settings/ — pydantic-settings v2 with FastAPI (verified against existing config.py)
- WebSearch results (2025) — confirmed BackgroundTasks runs after response is returned; confirmed allow_origin_regex regex syntax

### Tertiary (LOW confidence)
- vscode-webview:// exact origin format — not officially documented by VS Code for CORS regex matching; `vscode-webview://.*` is inferred from how VS Code webview origins are structured (UUID suffix after scheme)

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new libraries; all existing fastapi/starlette features
- Architecture: HIGH — BackgroundTasks and CORSMiddleware are stable, well-documented FastAPI features
- Pitfalls: HIGH for BackgroundTasks/CORS patterns (verified via official docs); MEDIUM for FTS5 delete approach (inferred from schema, no official FastAPI source)
- vscode-webview regex: MEDIUM — inferred from VS Code extension behavior, not a FastAPI-specific claim

**Research date:** 2026-03-18
**Valid until:** 2026-04-18 (stable FastAPI features — no fast-moving concerns)
