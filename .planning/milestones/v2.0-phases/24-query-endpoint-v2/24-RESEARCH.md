# Phase 24: query-endpoint-v2 - Research

**Researched:** 2026-03-22
**Domain:** FastAPI SSE endpoint wiring, LangGraph orchestrator integration, backward-compatible schema evolution, offline test strategy
**Confidence:** HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| TST-08 | All V1 tests (`pytest backend/tests/`) continue to pass (zero regressions) | V1 test suite is 8 tests in `test_query_router.py`; the current `query_router.py` and `schemas.py` are the only files V1 tests touch — changes must be additive, not destructive |
| TST-09 | All V2 agent tests use mock LLM + mock graph (no live API calls in test suite) | Established project-wide pattern: patch `app.core.model_factory.get_llm` at source; use `MemorySaver` instead of `SqliteSaver`; mock all I/O (`get_status`, `load_graph`, `graph_rag_retrieve`, `build_graph`) |
</phase_requirements>

---

## Summary

Phase 24 wires the existing `/query` endpoint to the Phase 22 LangGraph orchestrator and adds a V2 test suite, while keeping the 8 existing V1 tests green. The endpoint currently drives the V1 pipeline (`explore_stream` + `graph_rag_retrieve`) directly. The upgrade must be surgically additive: `intent_hint` is added to `QueryRequest`, the endpoint branches on its presence, and V2 responses are serialized into the same SSE frame format V1 consumers already parse. The hardest part is SSE serialization of structured V2 results (DebugResult, ReviewResult, TestResult) — these are Pydantic models that must be JSON-serialized per-field into the `event: result` + `event: done` frames that the frontend will consume.

The V2 test suite pattern is already fully established by Phases 17–23: mock `get_llm` at `app.core.model_factory.get_llm`, use `MemorySaver` for graph checkpointing, mock all blocking I/O with monkeypatch, and never touch live APIs. For the endpoint-level tests, the existing `test_query_router.py` pattern (FastAPI `TestClient` + monkeypatch of all I/O) is the template.

**Primary recommendation:** Add `intent_hint: Optional[str] = None` to `QueryRequest`, gate on its presence in `query_router.py`, and write a new `test_query_router_v2.py` that follows the existing V1 test structure exactly — reusing the same `client` fixture and monkeypatching `build_graph` to return a mock graph.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| FastAPI | already installed | HTTP endpoint, `StreamingResponse` | Existing project standard |
| LangGraph | already installed (`langgraph`) | Orchestrator graph invocation | Phase 22 |
| LangGraph MemorySaver | already installed | In-test checkpointer | Established in `test_orchestrator.py` |
| Pydantic v2 | already installed | Schema validation, `model_dump()` | Used across all agent models |
| FastAPI TestClient | already installed (`httpx`) | SSE stream testing | Used in all existing endpoint tests |
| pytest monkeypatch | stdlib | Patch I/O in tests | Established pattern across all 182 tests |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `json` | stdlib | SSE payload serialization | Every SSE frame |
| `asyncio.to_thread` | stdlib | Offload blocking `build_graph`/`graph.invoke()` to thread pool | Avoids blocking FastAPI event loop |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Inline `graph.invoke()` in endpoint | Separate async service layer | Simpler for now; service layer warranted only if multiple endpoints need orchestration |
| Single unified SSE event for V2 result | Multiple typed events per field | Unified `event: result` with structured JSON is simpler and sufficient |

**Installation:** No new packages needed. All dependencies are already in `requirements.txt`.

---

## Architecture Patterns

### Current V1 Endpoint Flow
```
POST /query
  → get_status(repo_path)          [guard: 400 if not complete]
  → _get_graph(repo_path, request) [cached nx.DiGraph]
  → graph_rag_retrieve(...)        [in thread pool]
  → explore_stream(nodes, question) [async generator]
  → SSE: event: token (×N), event: citations, event: done
```

### V2 Extension Pattern (Branching on intent_hint)
```
POST /query
  → get_status(repo_path)          [same guard as V1]
  → _get_graph(repo_path, request) [same cache as V1]

  if intent_hint is None or intent_hint == "auto":
    → [V1 path unchanged]
    → graph_rag_retrieve + explore_stream
    → SSE: event: token (×N), event: citations, event: done

  else:
    → build_graph(checkpointer=SqliteSaver(conn))
    → graph.invoke(NexusState{...})  [in thread pool via asyncio.to_thread]
    → serialize specialist_result to JSON
    → SSE: event: result (data: {type, intent, result: {...}}), event: done
```

### Recommended File Changes
```
backend/
├── app/
│   ├── models/
│   │   └── schemas.py           # Add intent_hint: Optional[str] = None to QueryRequest
│   │                            # Add target_node_id, selected_file, selected_range, repo_root (all Optional)
│   └── api/
│       └── query_router.py      # Branch on intent_hint; add V2 event_generator path
└── tests/
    └── test_query_router_v2.py  # New V2 test file (8-10 tests, all offline)
```

### Pattern 1: Backward-Compatible Schema Extension
**What:** Add new optional fields to `QueryRequest` with `None` defaults. The V1 test payload `{"question": "...", "repo_path": "..."}` stays valid because all new fields are optional.

**When to use:** Anytime an existing Pydantic model must accept new fields without breaking callers.

**Example:**
```python
# app/models/schemas.py — CURRENT
class QueryRequest(BaseModel):
    question: str
    repo_path: str
    max_nodes: int = 10
    hop_depth: int = 1

# AFTER Phase 24
class QueryRequest(BaseModel):
    question: str
    repo_path: str
    max_nodes: int = 10
    hop_depth: int = 1
    # V2 fields — all optional so V1 callers remain valid (ORCH-03)
    intent_hint: Optional[str] = None         # None / "auto" → V1 path; named intent → V2 path
    target_node_id: Optional[str] = None      # required by review_node, test_node
    selected_file: Optional[str] = None       # REVW-03
    selected_range: Optional[tuple] = None    # REVW-03: (line_start, line_end)
    repo_root: Optional[str] = None           # for tester framework detection
```

### Pattern 2: V2 SSE Serialization
**What:** LangGraph result types are Pydantic models. They must be serialized to dicts for `json.dumps()`.

**When to use:** Whenever `specialist_result` is a DebugResult / ReviewResult / TestResult / _ExplainResult.

**Example:**
```python
# In the V2 event_generator branch
result_state = await asyncio.to_thread(graph.invoke, initial_state, config)
specialist = result_state["specialist_result"]
intent = result_state["intent"]

# Pydantic v2: model_dump() → dict; _ExplainResult.answer is a plain str attr
if hasattr(specialist, "model_dump"):
    result_dict = specialist.model_dump()
else:
    result_dict = {"answer": specialist.answer, "nodes": [], "stats": {}}

payload = json.dumps({"type": "result", "intent": intent, "result": result_dict})
yield f"event: result\ndata: {payload}\n\n"
yield f"event: done\ndata: {json.dumps({'type': 'done'})}\n\n"
```

### Pattern 3: Blocking Graph Invocation in Async Context
**What:** `graph.invoke()` is synchronous and blocking. FastAPI runs on an asyncio event loop. The established project pattern (see Phase 22 note in STATE.md) is `asyncio.to_thread()`.

**When to use:** Any time synchronous blocking code must run inside a FastAPI async endpoint.

**Example:**
```python
# graph.invoke() is sync — offload to thread pool (established in existing endpoint)
result_state = await asyncio.to_thread(
    graph.invoke,
    initial_state,
    {"configurable": {"thread_id": thread_id}},
)
```

### Pattern 4: SqliteSaver in Endpoint vs MemorySaver in Tests
**What:** Production uses `SqliteSaver` (requires `check_same_thread=False`); tests use `MemorySaver`. The endpoint must create the `SqliteSaver` connection and graph once (or use the app lifespan cache pattern already present in `app.state.graph_cache`).

**Critical:** The SqliteSaver DB must be a separate file from `data/nexus.db` (graph store). This is a locked decision from STATE.md: "SqliteSaver checkpointer uses a separate DB from graph_store.py's 'data/nexus.db'".

**Example (production):**
```python
import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver

conn = sqlite3.connect("data/checkpoints.db", check_same_thread=False)
checkpointer = SqliteSaver(conn)
graph = build_graph(checkpointer=checkpointer)
```

**Example (test):**
```python
from langgraph.checkpoint.memory import MemorySaver
mock_graph = MagicMock()
mock_graph.invoke.return_value = {...}  # mock NexusState output
monkeypatch.setattr("app.api.query_router.build_graph", lambda **kwargs: mock_graph)
```

### Pattern 5: V2 Test Structure (following established project pattern)
**What:** All V2 endpoint tests use the same `client` fixture as V1 tests, monkeypatch all I/O, and assert on SSE event sequences.

**Patch targets for V2 tests:**
```python
monkeypatch.setattr("app.api.query_router.get_status", lambda _: IndexStatus(status="complete"))
monkeypatch.setattr("app.api.query_router.load_graph", lambda _: nx.DiGraph())
monkeypatch.setattr("app.api.query_router.build_graph", lambda **kw: mock_graph)
# mock_graph.invoke returns a dict matching NexusState shape
```

### Anti-Patterns to Avoid
- **Importing `build_graph` or `SqliteSaver` at module level in `query_router.py`:** Import lazily inside the V2 branch to avoid import-time ValidationError when API keys are absent (established project pattern for all V2 agents).
- **Calling `graph.invoke()` directly in the async endpoint without `asyncio.to_thread`:** This blocks the event loop. Phase 22 STATE.md explicitly documents `asyncio.run()` inside FastAPI raises "event loop already running".
- **Sharing the checkpointer DB with `data/nexus.db`:** Locked decision — use `data/checkpoints.db`.
- **Modifying `app/agent/explorer.py`:** This is a hard constraint — never modify this file.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON serialization of Pydantic models | Custom `__dict__` extraction | `.model_dump()` (Pydantic v2) | Handles nested models, Optional fields, enums correctly |
| Thread-safe blocking invocation | `threading.Thread` | `asyncio.to_thread()` | Already used in existing endpoint; consistent pattern |
| SSE framing | Custom protocol | `f"event: {name}\ndata: {payload}\n\n"` | Exact format already established in V1 implementation |
| In-memory checkpointing for tests | SQLite fixture | `MemorySaver()` | No thread safety concerns, no file cleanup needed |

**Key insight:** The SSE frame format (`event: name\ndata: payload\n\n`) is already implemented in the V1 endpoint. V2 only adds new event types using the same format.

---

## Common Pitfalls

### Pitfall 1: V1 Tests Broken by Schema Change
**What goes wrong:** Adding required fields to `QueryRequest` breaks the 8 existing V1 tests that POST only `{question, repo_path}`.
**Why it happens:** Pydantic raises `ValidationError` if a required field is missing from the request body.
**How to avoid:** All new V2 fields MUST have `Optional[str] = None` defaults (never required).
**Warning signs:** `test_unindexed_repo_returns_400` or `test_happy_path_yields_token_events` fail with 422 Unprocessable Entity.

### Pitfall 2: graph.invoke() Blocking the Event Loop
**What goes wrong:** `graph.invoke()` called directly in an `async def event_generator()` freezes all concurrent requests.
**Why it happens:** LangGraph's `graph.invoke()` is synchronous; calling it directly in an async function blocks the asyncio event loop.
**How to avoid:** Always `await asyncio.to_thread(graph.invoke, state, config)`.
**Warning signs:** Tests hang; endpoint appears to process only one request at a time.

### Pitfall 3: SqliteSaver Created per Request (Connection Leak)
**What goes wrong:** Each POST creates a new `sqlite3.connect()` and `SqliteSaver`; connections accumulate.
**Why it happens:** Naive implementation creates the connection inside the endpoint handler.
**How to avoid:** Create and cache the graph (with its SqliteSaver) on app startup in the lifespan handler, stored in `app.state` (same pattern as `app.state.graph_cache`).
**Warning signs:** "database is locked" errors under concurrent load; memory growth.

### Pitfall 4: Serializing _ExplainResult (Not a Standard Pydantic v2 Model)
**What goes wrong:** `_ExplainResult` is a Pydantic BaseModel but is a private class in `orchestrator.py`; its `nodes` field is `List[Any]` containing `CodeNode` objects which themselves need serialization.
**Why it happens:** `json.dumps(specialist.model_dump())` may fail if `nodes` contains `CodeNode` Pydantic objects (not plain dicts).
**How to avoid:** Call `model_dump(mode="json")` on Pydantic v2 models — this recursively serializes nested Pydantic objects to JSON-safe dicts. Or explicitly call `[n.model_dump() for n in nodes]`.
**Warning signs:** `TypeError: Object of type CodeNode is not JSON serializable` in test output.

### Pitfall 5: Wrong Patch Target for build_graph in Tests
**What goes wrong:** Patching `app.agent.orchestrator.build_graph` instead of `app.api.query_router.build_graph` — the import in `query_router.py` binds the name at import time; patching the source module has no effect.
**Why it happens:** Python's `unittest.mock.patch` patches the name where it is used, not where it is defined (established lesson from router/debugger patches in STATE.md).
**How to avoid:** Always patch `app.api.query_router.build_graph` (the consumer module binding).
**Warning signs:** `mock_graph.invoke` is never called in tests; real `build_graph` executes instead.

### Pitfall 6: intent_hint="auto" Must Route to V1 Path
**What goes wrong:** `intent_hint="auto"` routes to V2 orchestrator, which passes "auto" to `route()`, which causes an LLM call (or unknown intent error).
**Why it happens:** "auto" is the UI sentinel meaning "let the system decide" — it must be treated as `None` at the endpoint level.
**How to avoid:** Gate the V2 branch with `if request_body.intent_hint and request_body.intent_hint != "auto"` — both `None` and `"auto"` use the V1 path.
**Warning signs:** Tests passing "auto" fail with routing errors; intent_hint is not in `["explain", "debug", "review", "test"]`.

---

## Code Examples

### V2 Branch in query_router.py (Structural Pattern)

```python
# Source: STATE.md (Phase 22 decisions), orchestrator.py (NexusState definition)
@router.post("/query")
async def query(request_body: QueryRequest, request: Request) -> StreamingResponse:
    status = get_status(request_body.repo_path)
    if status is None or status.status != "complete":
        raise HTTPException(status_code=400, detail=f"repo '{request_body.repo_path}' not indexed")

    # V2 path: intent_hint is a named intent (not None and not "auto")
    if request_body.intent_hint and request_body.intent_hint != "auto":
        async def v2_event_generator():
            try:
                # Lazy import to prevent import-time ValidationError (established pattern)
                from app.agent.orchestrator import build_graph  # noqa: PLC0415
                import sqlite3  # noqa: PLC0415
                from langgraph.checkpoint.sqlite import SqliteSaver  # noqa: PLC0415

                G = await asyncio.to_thread(_get_graph, request_body.repo_path, request)
                conn = sqlite3.connect("data/checkpoints.db", check_same_thread=False)
                graph = build_graph(checkpointer=SqliteSaver(conn))

                initial_state = {
                    "question": request_body.question,
                    "repo_path": request_body.repo_path,
                    "intent_hint": request_body.intent_hint,
                    "G": G,
                    "target_node_id": request_body.target_node_id,
                    "selected_file": request_body.selected_file,
                    "selected_range": request_body.selected_range,
                    "repo_root": request_body.repo_root,
                    "intent": None,
                    "specialist_result": None,
                    "critic_result": None,
                    "loop_count": 0,
                }
                thread_id = f"{request_body.repo_path}::{request_body.question[:40]}"
                result_state = await asyncio.to_thread(
                    graph.invoke,
                    initial_state,
                    {"configurable": {"thread_id": thread_id}},
                )

                specialist = result_state["specialist_result"]
                intent = result_state["intent"]

                if hasattr(specialist, "model_dump"):
                    result_dict = specialist.model_dump(mode="json")
                else:
                    result_dict = {"answer": str(specialist)}

                payload = json.dumps({"type": "result", "intent": intent, "result": result_dict})
                yield f"event: result\ndata: {payload}\n\n"
                yield f"event: done\ndata: {json.dumps({'type': 'done'})}\n\n"

            except Exception as exc:  # noqa: BLE001
                payload = json.dumps({"type": "error", "message": str(exc)})
                yield f"event: error\ndata: {payload}\n\n"

        return StreamingResponse(v2_event_generator(), media_type="text/event-stream")

    # V1 path (unchanged — no modifications to existing code below this point)
    async def event_generator():
        ...  # existing V1 implementation unchanged
    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

### V2 Test Structure (test_query_router_v2.py)

```python
# Source: test_query_router.py (V1 pattern), test_orchestrator.py (mock patterns)
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models.schemas import IndexStatus
from app.agent.debugger import DebugResult, SuspectNode

@pytest.fixture()
def client():
    with (
        patch("app.main.init_db", return_value=None),
        patch("app.main.init_pgvector_table", return_value=None),
        TestClient(app) as c,
    ):
        yield c

def _make_mock_graph(intent: str, specialist_result):
    """Return a mock graph whose invoke() returns a complete NexusState dict."""
    mock_graph = MagicMock()
    mock_graph.invoke.return_value = {
        "question": "test",
        "repo_path": "/repo",
        "intent_hint": intent,
        "G": None,
        "target_node_id": None,
        "selected_file": None,
        "selected_range": None,
        "repo_root": None,
        "intent": intent,
        "specialist_result": specialist_result,
        "critic_result": MagicMock(passed=True),
        "loop_count": 0,
    }
    return mock_graph

def test_v2_debug_intent_returns_result_event(client, monkeypatch):
    """intent_hint='debug' invokes orchestrator; stream yields event: result with debug data."""
    monkeypatch.setattr("app.api.query_router.get_status", lambda _: IndexStatus(status="complete"))
    monkeypatch.setattr("app.api.query_router.load_graph", lambda _: nx.DiGraph())

    debug_result = DebugResult(
        suspects=[SuspectNode(node_id="a.py::func_a", file_path="/repo/a.py",
                              line_start=1, anomaly_score=0.8, reasoning="high complexity")],
        traversal_path=["a.py::func_a"],
        impact_radius=[],
        diagnosis="func_a is the likely root cause.",
    )
    mock_graph = _make_mock_graph("debug", debug_result)

    with patch("app.api.query_router.build_graph", return_value=mock_graph):
        with client.stream("POST", "/query",
                           json={"question": "Why does func_a crash?",
                                 "repo_path": "/repo",
                                 "intent_hint": "debug"}) as r:
            r.read()
            body = r.text

    assert "event: result" in body
    assert "event: done" in body
    assert '"intent": "debug"' in body
```

### Patching build_graph at the Consumer Module

```python
# Source: STATE.md (Phase 17 — "Patch lazy-imported get_llm at source module")
# For query_router.py, build_graph is lazy-imported inside the handler.
# Patch the module-level name AFTER the lazy import binds it — use the
# full import path as it appears in query_router.py.
with patch("app.api.query_router.build_graph", return_value=mock_graph):
    ...

# Alternative: patch the orchestrator module directly if imported lazily inside function
# Use monkeypatch.setattr for the source: "app.agent.orchestrator.build_graph"
# BUT only if query_router.py uses: from app.agent.orchestrator import build_graph
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| V1: `explore_stream()` async generator piped as SSE | V2: `graph.invoke()` (sync) in `asyncio.to_thread` | Phase 22 | Sync graph invocation; no async graph.astream for V2 path |
| Direct LLM call in endpoint | LangGraph orchestrator delegates to agents | Phase 22 | Full critic/retry loop happens inside `graph.invoke()` |
| No `intent_hint` field | `intent_hint: Optional[str]` in `QueryRequest` | Phase 24 | Router uses it directly without LLM call (ROUT-03) |

**Deprecated/outdated:**
- `explore_stream()` for V2 path: The V2 path does NOT use `explore_stream()` — it uses the orchestrator's `_explain_node` which calls `chain.invoke()` (sync). The V1 path keeps using `explore_stream()` unchanged.

---

## Open Questions

1. **Graph/checkpointer lifecycle: create per-request vs. app startup?**
   - What we know: Creating `SqliteSaver` per request causes connection leaks under load. `app.state.graph_cache` pattern exists for nx.DiGraph.
   - What's unclear: The success criteria says "streams correct SSE" — no explicit requirement for connection pooling. Phase is focused on correctness, not production hardening.
   - Recommendation: For Phase 24 (correctness focus), create per-request to keep scope tight. Add lifecycle comment noting this should move to app startup before production. The planner can decide.

2. **thread_id generation strategy for SqliteSaver**
   - What we know: `graph.invoke()` requires `config={"configurable": {"thread_id": "..."}}` when a checkpointer is present. Thread IDs scope conversation state.
   - What's unclear: Whether Phase 24 needs session-level persistence or request-level isolation.
   - Recommendation: Use `f"{repo_path}::{uuid4()}"` per request for isolation (no cross-request state bleed). This is safe and testable.

3. **V2 SSE event name: `result` vs intent-specific names**
   - What we know: Success criteria says "debug-structured response via Debugger" for intent_hint=debug. Phase 25-26 (extension rendering) will consume these events.
   - What's unclear: Whether to emit `event: result` (generic) or `event: debug_result`, `event: review_result` etc. (specific).
   - Recommendation: Use `event: result` with `intent` field in the JSON payload (`{"type": "result", "intent": "debug", "result": {...}}`). This is extensible and keeps the endpoint simple. The planner can decide.

---

## Sources

### Primary (HIGH confidence)
- `backend/app/api/query_router.py` — V1 endpoint implementation; SSE frame format; monkeypatch targets
- `backend/tests/test_query_router.py` — V1 test suite; 8 tests that MUST remain green; exact patch target strings
- `backend/app/agent/orchestrator.py` — `NexusState` TypedDict (all 12 fields); `build_graph()` signature; `_ExplainResult` Pydantic model
- `backend/app/models/schemas.py` — `QueryRequest` current fields; `CodeNode` structure
- `backend/tests/test_orchestrator.py` — V2 mock pattern (MemorySaver, patch `app.core.model_factory.get_llm`, `_make_mock_*` builders)
- `backend/tests/conftest.py` — `sample_graph`, `client` fixture pattern
- `.planning/STATE.md` — All locked decisions: SqliteSaver DB separation, lazy import pattern, `asyncio.to_thread` for sync calls

### Secondary (MEDIUM confidence)
- `.planning/REQUIREMENTS.md` — TST-08 and TST-09 requirements verbatim; ORCH-03 (V1 queries continue to work unchanged)

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already in requirements.txt; no new dependencies
- Architecture: HIGH — V1 endpoint code fully read; V2 orchestrator fully read; NexusState fields verified
- V1 regression risk: HIGH — all 8 V1 tests read and understood; change is additive only
- SSE serialization of V2 results: MEDIUM — `model_dump(mode="json")` is Pydantic v2 standard but CodeNode nesting in `_ExplainResult.nodes` not experimentally verified
- Pitfalls: HIGH — derived from direct code inspection and project STATE.md decisions

**Research date:** 2026-03-22
**Valid until:** 2026-04-22 (stable stack, no fast-moving dependencies)
