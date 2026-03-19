# Phase 10: Query Endpoint - Research

**Researched:** 2026-03-19
**Domain:** FastAPI SSE streaming, graph state management, LLM response orchestration
**Confidence:** HIGH

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| API-03 | `POST /query` accepts `QueryRequest{question, repo_path, max_nodes, hop_depth}`, returns SSE `StreamingResponse` | FastAPI `StreamingResponse` with `media_type="text/event-stream"` wraps an async generator that calls `graph_rag_retrieve` + `explore_stream`. QueryRequest Pydantic model maps directly to existing schema patterns. |
| API-04 | SSE stream format: `event: token\ndata: {...}` → `event: citations\ndata: {...}` → `event: done\ndata: {...}` → `event: error\ndata: {...}` | Exact SSE wire format uses `f"event: {name}\ndata: {json.dumps(payload)}\n\n"`. Each event type maps to one yield in the generator. Error events must be caught inside the generator (headers already sent). |
</phase_requirements>

---

## Summary

Phase 10 wires together Phase 8 (`graph_rag_retrieve`) and Phase 9 (`explore_stream`) behind a single `POST /query` HTTP endpoint that returns a Server-Sent Events stream. The endpoint accepts a `QueryRequest`, calls `graph_rag_retrieve` to get `(nodes, stats)`, then iterates `explore_stream` to yield token events, followed by a citations event and a done event carrying retrieval stats. All error paths inside the generator must yield an `event: error` event rather than raising — HTTP headers have already been sent by the time the generator starts.

The graph is a per-repo `nx.DiGraph`. It cannot be stored globally because different requests target different repos. The correct pattern is a module-level `dict[str, nx.DiGraph]` cache stored in `app.state`, populated by loading from SQLite via `load_graph` on first access (lazy load). This avoids both reading from disk on every request and forcing all graphs into memory at startup.

The FastAPI `StreamingResponse` class is the right choice here — it is already in the project's dependency set (Starlette, which FastAPI depends on), requires no new packages, and gives full control over the raw SSE wire format the requirements specify. The newer `EventSourceResponse` from `sse-starlette` or `fastapi.sse` is not needed because the event names and JSON payloads are custom and do not benefit from the auto-serialization layer those helpers add.

**Primary recommendation:** Add `query_router.py` with `POST /query` using `StreamingResponse(generator(), media_type="text/event-stream")`, where `generator()` is an inner async generator function that calls `graph_rag_retrieve` and then iterates `explore_stream`, yielding raw SSE-formatted strings for each event type. Register the router in `main.py` alongside the existing `index_router`.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `fastapi` | already installed | Router, request body parsing, `StreamingResponse` | Already the project's web framework |
| `starlette` | already installed (FastAPI dependency) | `StreamingResponse` class | `from starlette.responses import StreamingResponse` — zero new deps |
| `json` (stdlib) | stdlib | Serialize SSE data payloads | No external dep; deterministic output |
| `app.retrieval.graph_rag` | local | `graph_rag_retrieve(query, repo_path, G, max_nodes, hop_depth)` | Phase 8 output, returns `(list[CodeNode], stats_dict)` |
| `app.agent.explorer` | local | `explore_stream(nodes, question)` async generator | Phase 9 output, yields token strings |
| `app.ingestion.graph_store` | local | `load_graph(repo_path)` | Loads `nx.DiGraph` from SQLite |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `networkx` | already installed | `nx.DiGraph` type hint in router | Graph cache type |
| `pydantic` | already installed | `QueryRequest` model | Request body validation |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Raw `StreamingResponse` with manual SSE format | `sse-starlette` `EventSourceResponse` | `sse-starlette` adds keep-alive pings and cleaner API, but introduces a new dependency and wraps events in its own serialization which would require mapping to the exact format specified in API-04. Manual format string is simpler and explicit. |
| Lazy graph cache in `app.state` | Load graph on every request | Per-request `load_graph` hits SQLite every call; unacceptable for a 1000-node graph. `app.state` cache is correct. |
| Lazy graph cache in `app.state` | Load all graphs at startup | Cannot know all repo_paths at startup; no index needed yet. Lazy per-repo cache is correct. |

**Installation:**

No new packages required. All dependencies (`fastapi`, `starlette`, `networkx`, `pydantic`) are already installed in the project.

---

## Architecture Patterns

### Recommended Project Structure

```
backend/app/
├── api/
│   ├── index_router.py    # existing — POST /index, GET /index/status, DELETE /index
│   └── query_router.py    # new — POST /query (this phase)
├── models/
│   └── schemas.py         # add QueryRequest model here
└── main.py                # register query_router + add graph_cache to app.state
```

### Pattern 1: QueryRequest Pydantic Model

**What:** A Pydantic model that maps the `POST /query` request body.
**When to use:** Always — consistent with `IndexRequest` in `schemas.py`.
**Example:**

```python
# schemas.py — append after IndexRequest
class QueryRequest(BaseModel):
    question: str
    repo_path: str
    max_nodes: int = 10
    hop_depth: int = 1
```

### Pattern 2: Graph Cache via app.state

**What:** A `dict[str, nx.DiGraph]` stored in `app.state.graph_cache` during lifespan, accessed via `request.app.state.graph_cache`. On first access for a given `repo_path`, `load_graph` is called and the result is cached.
**When to use:** Any endpoint needing the graph. The `query_router` is the first consumer.

```python
# main.py — update lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    init_pgvector_table()
    app.state.graph_cache = {}   # dict[str, nx.DiGraph]
    yield

# query_router.py — helper
def _get_graph(repo_path: str, request: Request) -> nx.DiGraph:
    cache: dict = request.app.state.graph_cache
    if repo_path not in cache:
        cache[repo_path] = load_graph(repo_path)
    return cache[repo_path]
```

Source: FastAPI official docs — https://fastapi.tiangolo.com/advanced/events/

### Pattern 3: SSE Generator with Ordered Event Sequence

**What:** An inner async generator function inside the route handler that sequences: tokens → citations → done (or error on exception).
**When to use:** This is the entire body of `POST /query`.

```python
# query_router.py
import json
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from app.models.schemas import QueryRequest
from app.retrieval.graph_rag import graph_rag_retrieve
from app.agent.explorer import explore_stream
from app.ingestion.graph_store import load_graph

router = APIRouter()


@router.post("/query")
async def query(request_body: QueryRequest, request: Request):
    """Stream grounded answer tokens + citations over SSE."""

    async def event_generator():
        try:
            # Resolve graph (lazy cache)
            G = _get_graph(request_body.repo_path, request)

            # Step 1: retrieval
            nodes, stats = graph_rag_retrieve(
                request_body.question,
                request_body.repo_path,
                G,
                request_body.max_nodes,
                request_body.hop_depth,
            )

            # Step 2: stream tokens
            async for token in explore_stream(nodes, request_body.question):
                payload = json.dumps({"type": "token", "content": token})
                yield f"event: token\ndata: {payload}\n\n"

            # Step 3: citations event
            citations = [
                {
                    "node_id": n.node_id,
                    "file_path": n.file_path,
                    "line_start": n.line_start,
                    "line_end": n.line_end,
                    "name": n.name,
                }
                for n in nodes
            ]
            yield f"event: citations\ndata: {json.dumps({'type': 'citations', 'citations': citations})}\n\n"

            # Step 4: done event
            yield f"event: done\ndata: {json.dumps({'type': 'done', 'retrieval_stats': stats})}\n\n"

        except Exception as exc:  # noqa: BLE001
            payload = json.dumps({"type": "error", "message": str(exc)})
            yield f"event: error\ndata: {payload}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

Source: FastAPI docs — https://fastapi.tiangolo.com/advanced/custom-response/ + GitHub discussion https://github.com/fastapi/fastapi/discussions/10138

### Pattern 4: Register Router in main.py

**What:** Add `app.include_router(query_router)` alongside the existing `index_router` include.
**When to use:** Required for the endpoint to be reachable.

```python
# main.py — add import and include_router
from app.api.query_router import router as query_router
...
app.include_router(index_router)
app.include_router(query_router)
```

### Pattern 5: Cache Invalidation on DELETE /index

**What:** When `DELETE /index` is called, the cached graph for that `repo_path` should be evicted so the next query loads a fresh (empty) graph.
**When to use:** After deleting the index; otherwise stale graph data is returned.

```python
# query_router.py — expose eviction helper OR handle in index_router
def evict_graph_cache(repo_path: str, request: Request) -> None:
    cache: dict = request.app.state.graph_cache
    cache.pop(repo_path, None)
```

The `DELETE /index` route in `index_router.py` should call this after deleting the data. Since `index_router.py` cannot import from `query_router.py` without a circular dependency, the cache should live in a shared location (e.g., accessed directly via `request.app.state.graph_cache`).

### Anti-Patterns to Avoid

- **Raising HTTPException inside the generator:** Headers are already sent. This will cause a connection error on the client side, not a clean HTTP error response. Use `yield event: error` instead.
- **Global graph dict at module level:** Module-level state cannot be cleared safely via the lifespan pattern. Use `app.state.graph_cache`.
- **Running `graph_rag_retrieve` in an async thread without awaiting:** `graph_rag_retrieve` is synchronous (blocking I/O: pgvector, SQLite). Wrap it with `asyncio.to_thread` to avoid blocking the event loop.
- **Loading graph inside `graph_rag_retrieve` on every call:** The graph is passed in as a parameter — correct. Never move graph loading inside the retrieval function.
- **Not flushing on each yield:** `StreamingResponse` flushes automatically on each `yield` from an async generator. No explicit flush needed.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| SSE wire format | Custom bytes framing | `f"event: {name}\ndata: {data}\n\n"` string format | SSE is a line-protocol text spec; the format is 3 lines + blank line, nothing more. |
| Graph loading/caching | Custom cache class | `dict` in `app.state` | Simplest possible structure; `lru_cache` is not appropriate (keyed on mutable args). |
| LLM streaming | Custom OpenAI wrapper | `explore_stream()` from Phase 9 | Already built, tested, traces to LangSmith. |
| Retrieval | Custom vector+graph search | `graph_rag_retrieve()` from Phase 8 | Already built with full scoring formula. |
| Request body parsing | Manual JSON parsing | Pydantic `QueryRequest` model | Consistent with every other endpoint in the project. |

**Key insight:** This phase is pure orchestration — it assembles already-built pieces behind one HTTP boundary. The only new code is the router, the `QueryRequest` schema, and the event generator.

---

## Common Pitfalls

### Pitfall 1: Blocking the Event Loop with Synchronous Retrieval

**What goes wrong:** `graph_rag_retrieve` calls `semantic_search` which opens a psycopg2 connection and executes a synchronous SQL query. `load_graph` reads from SQLite synchronously. Calling these directly in an `async def` route blocks all other requests while they complete.
**Why it happens:** Phase 8 and the graph store were written as synchronous blocking I/O, consistent with the patterns set in earlier phases.
**How to avoid:** Wrap both calls in `asyncio.to_thread`:

```python
import asyncio
nodes, stats = await asyncio.to_thread(
    graph_rag_retrieve, question, repo_path, G, max_nodes, hop_depth
)
```

And for graph loading:
```python
G = await asyncio.to_thread(load_graph, repo_path)
```

**Warning signs:** Requests queue up; uvicorn worker appears unresponsive during retrieval.

### Pitfall 2: Stale Graph Cache After Re-Index

**What goes wrong:** User runs `POST /index` to re-index the repo. The cached `nx.DiGraph` in `app.state.graph_cache` is stale (contains old nodes). The next `POST /query` returns answers based on old graph data.
**Why it happens:** The cache is populated lazily on first query and never invalidated.
**How to avoid:** The `POST /index` pipeline calls `save_graph` at the end. After `run_ingestion` completes, the cache entry for that `repo_path` must be evicted. Since `run_ingestion` runs as a `BackgroundTask`, cache eviction should happen at the end of `run_ingestion` itself (or in `index_router.py` after adding a completion hook).

The simplest approach: At the end of `run_ingestion`, also clear the `app.state.graph_cache` entry. However, `run_ingestion` in `pipeline.py` has no access to `app.state`. Instead, after a `POST /index` completes, `query_router` should evict on the next query by checking the index status timestamp — or more simply, the cache entry should always be refreshed after a `complete` status is detected.

**Recommended simple solution:** On each `POST /query`, check if graph is already in cache and if `get_status(repo_path)` is `complete` — if so, skip cache and reload. This trades a single extra SQLite load for simplicity. Alternatively, just clear `graph_cache[repo_path]` at the start of every `POST /index` completion.

**Warning signs:** `event: token` output references deleted functions or old file paths.

### Pitfall 3: HTTPException Does Not Propagate Through StreamingResponse

**What goes wrong:** A `raise HTTPException(status_code=404, detail="no graph")` inside `event_generator()` causes an unhandled server error log entry but sends no useful error to the client — the client sees the connection close unexpectedly.
**Why it happens:** HTTP status code is written in the response headers before any generator body is sent. Mid-stream exceptions cannot change the already-sent 200 status.
**How to avoid:** Validate eagerly before returning `StreamingResponse`. Check that `repo_path` has been indexed (via `get_status`) before starting the stream. Raise `HTTPException` in the route handler body, before constructing `StreamingResponse`.

```python
@router.post("/query")
async def query(request_body: QueryRequest, request: Request):
    status = get_status(request_body.repo_path)
    if status is None or status.status != "complete":
        raise HTTPException(status_code=400, detail="repo not indexed")
    # safe to start stream now
    return StreamingResponse(event_generator(), ...)
```

**Warning signs:** curl returns 200 with empty body, or connection reset without any event data.

### Pitfall 4: JSON Serialization of CodeNode in Citations

**What goes wrong:** Passing a `CodeNode` object directly to `json.dumps()` raises `TypeError: Object of type CodeNode is not JSON serializable`.
**Why it happens:** Pydantic models are not plain dicts.
**How to avoid:** Either call `node.model_dump()` or construct a plain dict with only the fields needed for the citation event. See the code example in Pattern 3 above.

### Pitfall 5: Graph Not Found for Repo Path

**What goes wrong:** `load_graph(repo_path)` returns an empty `nx.DiGraph()` if the repo has not been indexed (no rows in SQLite). `graph_rag_retrieve` then returns 0 nodes. The stream emits `event: done` with 0 returned nodes — no error, just empty answers.
**Why it happens:** `load_graph` is designed to return an empty graph rather than raise. This is correct for incremental indexing but misleading for the query path.
**How to avoid:** Before streaming, call `get_status(repo_path)`. If status is `None` or not `complete`, return HTTP 400 with a clear message (see Pitfall 3 solution above).

---

## Code Examples

Verified patterns from official sources:

### SSE Wire Format (W3C spec)

```python
# Source: FastAPI official docs + W3C SSE specification
# Each event is: optional event name line + data line(s) + blank line

# Named event with JSON payload:
f"event: token\ndata: {json.dumps({'type': 'token', 'content': text})}\n\n"

# Unnamed event (data only):
f"data: {json.dumps({'type': 'done'})}\n\n"
```

### StreamingResponse with Async Generator

```python
# Source: https://fastapi.tiangolo.com/advanced/custom-response/
from fastapi.responses import StreamingResponse

async def event_generator():
    yield "event: token\ndata: hello\n\n"
    yield "event: done\ndata: {}\n\n"

return StreamingResponse(event_generator(), media_type="text/event-stream")
```

### app.state for Shared Per-Request State

```python
# Source: https://fastapi.tiangolo.com/advanced/events/
# Lifespan setup:
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.graph_cache = {}
    yield

# Route access:
@router.post("/query")
async def query(request_body: QueryRequest, request: Request):
    cache = request.app.state.graph_cache
```

### asyncio.to_thread for Blocking I/O in Async Context

```python
# Source: Python 3.9+ docs — asyncio.to_thread
# Consistent with existing pipeline.py pattern in this project
import asyncio

nodes, stats = await asyncio.to_thread(
    graph_rag_retrieve,
    request_body.question,
    request_body.repo_path,
    G,
    request_body.max_nodes,
    request_body.hop_depth,
)
```

### curl Client Consuming the SSE Stream

```bash
# Verify SSE stream manually (success criteria item 4)
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What does run_ingestion do?", "repo_path": "/path/to/repo"}' \
  --no-buffer
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `@app.on_event("startup")` | `lifespan` context manager | FastAPI 0.93 (2023) | Old approach deprecated; lifespan is the only correct way for new code |
| Synchronous generators in StreamingResponse | Async generators | FastAPI 0.88+ | Async generators avoid thread pool overhead |
| `sse-starlette` external lib for all SSE | Manual SSE format strings for custom events | Stable practice | For LLM streaming with custom event names, raw format strings give full control |

**Deprecated/outdated:**
- `@app.on_event("startup")` / `@app.on_event("shutdown")`: replaced by `lifespan` context manager. This project already uses lifespan in `main.py`.

---

## Open Questions

1. **Cache invalidation after re-index**
   - What we know: `run_ingestion` runs as a `BackgroundTask`. When it completes, `save_graph` is called which writes new graph data to SQLite. The in-memory `graph_cache` is not updated.
   - What's unclear: Where to trigger cache eviction — pipeline.py has no app reference; index_router has no post-completion hook.
   - Recommendation: Simplest approach is to evict `graph_cache[repo_path]` at the start of `POST /index` (before the background task runs), so the next query always reloads. This sacrifices one concurrent query window but is easy and correct for V1.

2. **Thread safety of graph_cache dict**
   - What we know: Python's GIL protects simple dict `get`/`set` operations from races. Multiple concurrent queries for the same `repo_path` could each call `load_graph` simultaneously before the cache is populated.
   - What's unclear: Whether concurrent cache misses for the same key cause any real problem.
   - Recommendation: For V1, this is acceptable — the worst case is `load_graph` called twice for the same key; the second write just overwrites the first with an identical graph. No lock needed.

---

## Sources

### Primary (HIGH confidence)

- https://fastapi.tiangolo.com/advanced/events/ — lifespan, app.state pattern
- https://fastapi.tiangolo.com/advanced/custom-response/ — StreamingResponse usage
- https://fastapi.tiangolo.com/tutorial/server-sent-events/ — SSE in FastAPI (new native SSE support)
- https://github.com/fastapi/fastapi/discussions/10138 — exception handling in StreamingResponse generators (community verified, matches Starlette internals)
- Project source: `backend/app/api/index_router.py` — exact router registration and Pydantic model patterns to follow
- Project source: `backend/app/agent/explorer.py` — `explore_stream` signature and behavior
- Project source: `backend/app/retrieval/graph_rag.py` — `graph_rag_retrieve` signature, return type, stats dict keys
- Project source: `backend/app/models/schemas.py` — existing model patterns for `QueryRequest` addition
- Project source: `backend/app/main.py` — existing lifespan, CORS, router registration pattern

### Secondary (MEDIUM confidence)

- https://blog.gopenai.com/how-to-stream-llm-responses-in-real-time-using-fastapi-and-sse-d2a5a30f2928 — LLM streaming via SSE with FastAPI (verified against official docs)
- https://python.plainenglish.io/streaming-apis-for-beginners-python-fastapi-and-async-generators-848b73a8fc06 — async generator with StreamingResponse

### Tertiary (LOW confidence)

None. All critical claims verified against official FastAPI docs or project source.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; all libraries already in project
- Architecture: HIGH — patterns verified against FastAPI official docs and existing project code
- Pitfalls: HIGH — error-handling limitation verified against FastAPI GitHub discussion and Starlette source behavior
- SSE format: HIGH — verified against W3C SSE spec and FastAPI docs

**Research date:** 2026-03-19
**Valid until:** 2026-04-18 (FastAPI SSE API is stable; project conventions are frozen)
