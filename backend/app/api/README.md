# API Endpoints

FastAPI routers for indexing, querying, and status checking. The API supports both V1 (graph-RAG exploration) and V2 (intent-routed multi-agent) query paths, selected based on `intent_hint` in the request.

## Endpoint Reference

### `POST /index` — Start Indexing

**Request:**
```json
{
  "repo_path": "/abs/path/to/repo",
  "languages": ["python", "typescript"],
  "changed_files": ["/abs/path/modified.py"]  // optional, for incremental re-index
}
```

**Response:**
```json
{
  "status": "pending",
  "repo_path": "/abs/path/to/repo"
}
```

**Status Code:** `202 Accepted` (immediate return, runs in background)

**Behavior:**
- If `changed_files` is provided: incremental re-index (delete old nodes, re-parse only changed files)
- If `changed_files` is None: full repository re-index
- Non-blocking: returns immediately, status available via `/index/status`

**Example:**
```bash
curl -X POST http://localhost:8000/index \
  -H "Content-Type: application/json" \
  -d '{
    "repo_path": "/Users/me/nexus",
    "languages": ["python", "typescript"]
  }'
# Response: {"status": "pending", "repo_path": "/Users/me/nexus"}
```

---

### `GET /index/status` — Poll Indexing Progress

**Query Parameters:**
```
?repo_path=/abs/path/to/repo
```

**Response:**
```json
{
  "status": "running",
  "nodes_indexed": 2500,
  "edges_indexed": 4200,
  "files_processed": 150,
  "error": null
}
```

or (if indexing not started for this repo):
```json
{
  "error": "No index found for repo_path"
}
```

**Status Values:**
- `running`: Indexing in progress
- `complete`: Indexing finished successfully
- `failed`: Indexing failed (see `error` field for details)
- (missing): No status recorded for this repo

**Example:**
```bash
curl http://localhost:8000/index/status?repo_path=/Users/me/nexus
# Response: {"status": "running", "nodes_indexed": 2500, ...}
```

---

### `DELETE /index` — Clear Repository Index

**Query Parameters:**
```
?repo_path=/abs/path/to/repo
```

**Response:**
```json
{
  "status": "deleted",
  "repo_path": "/abs/path/to/repo"
}
```

**Behavior:**
- Deletes all pgvector embeddings for the repo
- Deletes all SQLite graph nodes and edges
- Clears status tracking
- Non-destructive: can re-index immediately after

**Example:**
```bash
curl -X DELETE http://localhost:8000/index?repo_path=/Users/me/nexus
# Response: {"status": "deleted", "repo_path": "/Users/me/nexus"}
```

---

### `POST /query` — Query & Retrieve

**Request:**
```json
{
  "question": "How does authentication work?",
  "repo_path": "/abs/path/to/repo",
  "max_nodes": 10,
  "hop_depth": 1,
  "intent_hint": null,
  "target_node_id": null,
  "selected_file": null,
  "selected_range": null,
  "repo_root": null
}
```

**Required Fields:**
- `question`: str — Natural language query
- `repo_path`: str — Repository identifier

**Optional Fields (V2 specific):**
- `intent_hint`: str | None — "explain" | "debug" | "review" | "test" | "auto" | null
  - null or "auto": Router classifies intent (LLM call)
  - One of four intents: Skip Router, route directly to specialist
  - Default: null
- `target_node_id`: str | None — Required for review/test intents
  - Example: "backend/app/agent/router.py::route"
- `selected_file`: str | None — For range-targeted review
- `selected_range`: tuple | None — (line_start, line_end) for range-targeted review
- `repo_root`: str | None — For framework detection in tester

**Optional Fields (V1/Retrieval specific):**
- `max_nodes`: int = 10 — Max context nodes to return
- `hop_depth`: int = 1 — BFS graph expansion depth

**Response:** Server-Sent Events (SSE) stream

---

## SSE Event Sequences

### V1 Path (intent_hint is None, "auto", or "" ; or invalid)

```
event: token
data: {"type": "token", "content": "The "}

event: token
data: {"type": "token", "content": "authentication "}

event: token
data: {"type": "token", "content": "middleware ..."}

event: citations
data: {"type": "citations", "citations": [
  {"node_id": "auth/middleware.py::verify_token", "file_path": "/abs/.../middleware.py", "line_start": 45, "line_end": 67, "name": "verify_token", "type": "function"},
  ...
]}

event: done
data: {"type": "done", "retrieval_stats": {"seed_count": 10, "expanded_count": 42, "returned_count": 10, "hop_depth": 1}}
```

**Event Order:**
1. **token** (1 per LLM token) — Streaming answer content
2. **citations** (single event) — Retrieved nodes used in context
3. **done** (final event) — Retrieval statistics

**Event Schema:**

| Event | Data Structure |
|-------|---|
| `token` | `{"type": "token", "content": str}` |
| `citations` | `{"type": "citations", "citations": [{"node_id": str, "file_path": str, "line_start": int, "line_end": int, "name": str, "type": str}, ...]}` |
| `done` | `{"type": "done", "retrieval_stats": {"seed_count": int, "expanded_count": int, "returned_count": int, "hop_depth": int}}` |
| `error` | `{"type": "error", "message": str}` |

---

### V2 Path (intent_hint in {explain, debug, review, test})

```
event: result
data: {
  "type": "result",
  "intent": "debug",
  "result": {
    "suspects": [
      {"node_id": "...", "file_path": "...", "line_start": 42, "anomaly_score": 0.82, "reasoning": "..."},
      ...
    ],
    "traversal_path": ["node1", "node2", ...],
    "impact_radius": ["caller1", "caller2"],
    "diagnosis": "..."
  },
  "has_github_token": false,
  "file_written": false,
  "written_path": null
}

event: done
data: {"type": "done"}
```

**Event Order:**
1. **result** (single event) — Full specialist output + metadata
2. **done** (final event) — Completion signal

**Result Structure (varies by intent):**

| Intent | Result Type | Fields |
|--------|---|---|
| explain | _ExplainResult | `answer: str, nodes: list[CodeNode], stats: dict` |
| debug | DebugResult | `suspects: list[SuspectNode], traversal_path: list[str], impact_radius: list[str], diagnosis: str` |
| review | ReviewResult | `findings: list[Finding], retrieved_nodes: list[str], summary: str` |
| test | TestResult | `test_code: str, test_file_path: str, framework: str` |

**Metadata Fields:**
- `has_github_token`: bool — Extension can show/hide "Post to PR" button
- `file_written`: bool — Whether MCP `write_test_file` succeeded (test intent only)
- `written_path`: str | None — Path to written file (if file_written=true)

---

### Error Event (Any Path)

```
event: error
data: {"type": "error", "message": "Repository 'xxx' has not been indexed or indexing is not complete"}
```

---

## Implementation Details

### Lazy Imports in `query_router.py`

The V2 path uses lazy imports inside the SSE generator to prevent import-time validation errors:

```python
async def v2_event_generator():
    try:
        from app.agent.orchestrator import build_graph  # LAZY
        import sqlite3 as _sqlite3                       # LAZY
        from langgraph.checkpoint.sqlite import SqliteSaver  # LAZY

        # ... rest of implementation
    except Exception as exc:
        yield f"event: error\ndata: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
```

**Why?** API key validation happens when `get_llm()` is called inside orchestrator. If we import at module level, pytest collection fails. Lazy imports defer validation until actual request time.

### Graph Caching

Graphs are cached in `request.app.state.graph_cache` (dict[str, nx.DiGraph]):

```python
def _get_graph(repo_path: str, request: Request) -> nx.DiGraph:
    cache: dict = request.app.state.graph_cache
    if repo_path not in cache:
        cache[repo_path] = load_graph(repo_path)  # SQLite load
    return cache[repo_path]
```

This avoids re-loading from SQLite on every query for the same repo. Cache is in-memory and cleared on server restart.

### Checkpointing (V2 Only)

LangGraph state is checkpointed to `data/checkpoints.db` (separate from `data/nexus.db`):

```python
conn = _sqlite3.connect("data/checkpoints.db", check_same_thread=False)
graph = build_graph(checkpointer=SqliteSaver(conn))
```

**Important:** `check_same_thread=False` is required because LangGraph writes checkpoints in background threads.

Each request gets a unique thread ID for isolation:

```python
thread_id = f"{request_body.repo_path}::{uuid4()}"
result_state = await asyncio.to_thread(
    graph.invoke,
    initial_state,
    {"configurable": {"thread_id": thread_id}},
)
```

### MCP Tool Integration

For test intent, the result handler attempts to write the test file via MCP:

```python
if intent == "test":
    try:
        from app.mcp.tools import write_test_file as _write_test_file
        _mcp_result = _write_test_file(
            result_dict.get("test_code", ""),
            result_dict.get("test_file_path", "tests/test_output.py"),
            base_dir=str(request_body.repo_root or "."),
        )
        file_written = bool(_mcp_result.get("success", False))
        written_path = _mcp_result.get("path")
    except Exception as _mcp_exc:
        # Silently fail; file_written=False signals fallback to clipboard
        pass
```

---

## Gateway Logic: V1 vs. V2

The `query_router.py` dispatcher uses this logic:

```python
# V2 path: intent_hint is a named intent (not None, not "auto")
if request_body.intent_hint and request_body.intent_hint != "auto":
    # Use orchestrator (multi-agent)
    async def v2_event_generator():
        ...
    return StreamingResponse(v2_event_generator(), ...)

# V1 path: default
async def event_generator():
    ...
return StreamingResponse(event_generator(), ...)
```

**Decision Tree:**
```
intent_hint == null or "auto"?
  ├─ YES: V1 path (graph-RAG)
  └─ NO: Check if intent_hint in {explain, debug, review, test}
         ├─ YES: V2 path (orchestrator)
         └─ NO: V1 path (fallback)
```

---

## Health Check

### `GET /health`

**Response:**
```json
{
  "status": "ok",
  "version": "1.0.0"
}
```

Used by Docker health checks and load balancers.

---

## Error Handling

**HTTP Errors:**

| Status | Scenario |
|--------|----------|
| 400 | Repository not indexed, indexing not complete, or invalid parameters |
| 500 | Unexpected server error (check logs) |

**SSE Errors:**

Errors during SSE streaming are emitted as `error` events (not HTTP status):

```
event: error
data: {"type": "error", "message": "pgvector connection failed"}
```

This allows partial results to be returned before error occurs.

---

## Request Validation

**Pydantic Models:**

```python
class IndexRequest(BaseModel):
    repo_path: str
    languages: list[str] = ["python", "typescript"]
    changed_files: list[str] | None = None

class QueryRequest(BaseModel):
    question: str
    repo_path: str
    max_nodes: int = 10
    hop_depth: int = 1
    intent_hint: Optional[str] = None
    target_node_id: Optional[str] = None
    selected_file: Optional[str] = None
    selected_range: Optional[tuple] = None
    repo_root: Optional[str] = None

class IndexStatus(BaseModel):
    status: str  # "running" | "complete" | "failed"
    nodes_indexed: int = 0
    edges_indexed: int = 0
    files_processed: int = 0
    error: str | None = None
```

---

## CORS & Middleware

**Allowed Origins:**
- `http://localhost:3000` — Local dev
- `vscode-webview://.*` — VS Code extension

**Methods:** GET, POST, DELETE, OPTIONS

**Headers:** All allowed

---

## Testing

All endpoints are integration-tested:

| Test File | Coverage |
|-----------|----------|
| `test_query_router.py` | V1 event order, content validation |
| `test_query_router_v2.py` | V2 all intents, auto sentinel, error handling |
| `test_index_router.py` | POST /index, GET /status, DELETE /index |

Run tests:
```bash
python -m pytest backend/tests/test_*_router.py -v
```

---

## Performance Notes

| Endpoint | Latency |
|----------|---------|
| POST /index (returns immediately) | <10ms |
| GET /index/status (checks in-memory) | <1ms |
| POST /query (V1) | 50–200ms (depends on LLM token generation) |
| POST /query (V2) | 5–15s (depends on specialist + LLM latency) |

---

## Future Work (Phase 27+)

- [ ] Pagination for large result sets
- [ ] Filtering by language, file path, severity (for review findings)
- [ ] Request cancellation (for long-running agents)
- [ ] Async task API (separate query submission from result polling)
