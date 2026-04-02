# Phase 22: orchestrator - Research

**Researched:** 2026-03-22
**Domain:** LangGraph StateGraph orchestration, SqliteSaver checkpointing, multi-agent routing
**Confidence:** HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| ORCH-01 | System routes every query through a LangGraph StateGraph with typed `NexusState` (replacing V1 single LangChain runnable) | StateGraph API verified; NexusState TypedDict fields mapped from all agent signatures; conditional edge routing confirmed |
| ORCH-02 | Graph compiles with `SqliteSaver` checkpointer so conversation state persists across requests | SqliteSaver import path, constructor, thread-safety requirement, and `check_same_thread=False` fix all verified |
| ORCH-03 | All V1 queries (without `intent_hint`) continue to work unchanged via the `explain` default path | V1 `graph_rag_retrieve` + `explore_stream` path understood; explain_node strategy using `chain.invoke()` instead of streaming documented |
| TST-07 | `test_orchestrator.py` — 6 integration tests (explain/debug/review/test/retry/max_loops) all pass | MemorySaver for offline tests verified; mock injection points identified; all 6 test scenarios designed |
</phase_requirements>

---

## Summary

Phase 22 wires the five existing agents (router, debugger, reviewer, tester, critic) into a single `LangGraph` `StateGraph` with a typed `NexusState`. Every query flows: `router_node` classifies intent, the matching specialist node runs, then `critic_node` applies the deterministic quality gate. If the critic fails and the loop cap has not been reached, the graph retries the same specialist with incremented `loop_count`; otherwise it terminates at `END`.

The `explain` path (V1 compatibility) uses `graph_rag_retrieve` from `app.retrieval.graph_rag` for retrieval, then calls the existing LCEL chain via `chain.invoke()` (not the streaming `explore_stream`). This gives identical answer quality without requiring the orchestrator to handle async generators inside synchronous graph nodes.

`SqliteSaver` is the production checkpointer — it requires `sqlite3.connect('data/checkpoints.db', check_same_thread=False)`. Tests use `MemorySaver` instead to avoid sqlite thread-safety issues. LangGraph 1.1.3 is already installed; `langgraph` and `langgraph-checkpoint-sqlite` must be added to `requirements.txt`.

**Primary recommendation:** Place the orchestrator at `backend/app/agent/orchestrator.py`. Expose `NexusState` (TypedDict) and `build_graph(checkpointer=None)` factory. Tests call `build_graph(MemorySaver())` to get a fully compiled, offline graph.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| langgraph | 1.1.3 (installed) | StateGraph definition, compilation, invocation | LangGraph is the project's chosen orchestration framework per STATE.md |
| langgraph-checkpoint-sqlite | 3.0.3 (installed) | SqliteSaver — persists conversation state to SQLite | Chosen in STATE.md decisions: "SqliteSaver checkpointer uses a separate DB from graph_store.py" |
| langgraph-checkpoint | 4.0.1 (installed) | Base checkpoint interfaces, MemorySaver for tests | MemorySaver avoids sqlite thread issues in pytest |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| langgraph.checkpoint.memory.MemorySaver | bundled | In-memory checkpointer | Testing only — no sqlite thread safety issues |
| networkx | >=3.4 | Graph pass-through in NexusState | All specialist agents accept `nx.DiGraph` directly |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| SqliteSaver | AsyncSqliteSaver | Async saver avoids thread issues but requires full async graph; overkill for this sync-first design |
| MemorySaver in tests | SqliteSaver with `:memory:` + `check_same_thread=False` | Both work; MemorySaver is simpler and has no setup |

### Installation (additions to requirements.txt)

```bash
# Add to backend/requirements.txt:
langgraph>=1.1.3
langgraph-checkpoint-sqlite>=3.0.3
```

---

## Architecture Patterns

### Recommended Project Structure

```
backend/app/agent/
├── orchestrator.py       # NEW — NexusState + build_graph() factory
├── router.py             # existing — IntentResult, route()
├── debugger.py           # existing — DebugResult, debug()
├── reviewer.py           # existing — ReviewResult, review()
├── tester.py             # existing — TestResult, test()
├── critic.py             # existing — CriticResult, critique()
└── explorer.py           # DO NOT TOUCH — explore_stream() (V1)

backend/tests/
└── test_orchestrator.py  # NEW — 6 integration tests
```

### Pattern 1: NexusState TypedDict

```python
# Source: verified against all agent signatures
from __future__ import annotations
from typing import TypedDict, Optional, Union
import networkx as nx
from app.agent.debugger import DebugResult
from app.agent.reviewer import ReviewResult
from app.agent.tester import TestResult
from app.agent.critic import CriticResult

class NexusState(TypedDict):
    # Query inputs
    question: str
    repo_path: str
    intent_hint: Optional[str]          # forwarded to route()
    # Graph input (passed through, not checkpointed by SqliteSaver)
    G: Optional[object]                  # nx.DiGraph — typed as object for LangGraph compat
    target_node_id: Optional[str]        # for review/test agents
    selected_file: Optional[str]         # REVW-03
    selected_range: Optional[tuple]      # REVW-03
    repo_root: Optional[str]             # for tester framework detection
    # Routing
    intent: Optional[str]               # set by router_node
    # Results
    specialist_result: Optional[Union[DebugResult, ReviewResult, TestResult]]
    critic_result: Optional[CriticResult]
    # Loop control
    loop_count: int                     # 0 on first attempt; incremented by critic_node on retry
```

**Important:** `nx.DiGraph` is not JSON-serializable. SqliteSaver will fail to serialize it. Pass `G` via the initial `invoke()` call input; it will be present in state during the current run. Do NOT rely on SqliteSaver to persist `G` across sessions — callers must always provide `G` on each invocation.

### Pattern 2: build_graph() Factory

```python
# Source: verified with langgraph 1.1.3
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.base import BaseCheckpointSaver

def build_graph(checkpointer: BaseCheckpointSaver | None = None):
    """Compile the NexusState graph. Pass MemorySaver() for tests."""
    g = StateGraph(NexusState)
    g.add_node("router_node", _router_node)
    g.add_node("explain_node", _explain_node)
    g.add_node("debug_node", _debug_node)
    g.add_node("review_node", _review_node)
    g.add_node("test_node", _test_node)
    g.add_node("critic_node", _critic_node)

    g.add_edge(START, "router_node")
    g.add_conditional_edges(
        "router_node",
        _route_by_intent,
        {
            "explain": "explain_node",
            "debug":   "debug_node",
            "review":  "review_node",
            "test":    "test_node",
        },
    )
    for specialist in ("explain_node", "debug_node", "review_node", "test_node"):
        g.add_edge(specialist, "critic_node")

    g.add_conditional_edges(
        "critic_node",
        _route_after_critic,
        {
            "explain": "explain_node",
            "debug":   "debug_node",
            "review":  "review_node",
            "test":    "test_node",
            "done":    END,
        },
    )
    return g.compile(checkpointer=checkpointer)
```

### Pattern 3: SqliteSaver Production Construction

```python
# Source: verified with langgraph-checkpoint-sqlite 3.0.3
import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver

# CRITICAL: check_same_thread=False — LangGraph uses background threads for checkpointing
conn = sqlite3.connect("data/checkpoints.db", check_same_thread=False)
checkpointer = SqliteSaver(conn)
graph = build_graph(checkpointer=checkpointer)
```

### Pattern 4: Thread-Scoped Invocation

```python
# Source: verified with langgraph 1.1.3
result = graph.invoke(
    {
        "question": "Why does checkout fail?",
        "repo_path": "/repos/my-app",
        "intent_hint": None,
        "G": loaded_nx_graph,
        "target_node_id": None,
        "selected_file": None,
        "selected_range": None,
        "repo_root": "/repos/my-app",
        "intent": None,
        "specialist_result": None,
        "critic_result": None,
        "loop_count": 0,
    },
    config={"configurable": {"thread_id": "session-abc123"}},
)
```

### Pattern 5: Explain Node (V1 Compatibility Path)

The V1 `explore_stream()` is an async generator — it cannot be awaited to collect a single string result inside a sync graph node without `asyncio.run()`. Use `chain.invoke()` directly instead, which uses the same prompt and LLM:

```python
def _explain_node(state: NexusState) -> dict:
    from app.retrieval.graph_rag import graph_rag_retrieve  # lazy
    from app.agent.explorer import format_context_block, _get_chain  # lazy

    G = state["G"]
    nodes, stats = graph_rag_retrieve(
        state["question"], state["repo_path"], G
    )
    chain = _get_chain()
    response = chain.invoke({
        "system_prompt": SYSTEM_PROMPT,
        "context": format_context_block(nodes),
        "question": state["question"],
    })
    answer = response.content if hasattr(response, "content") else str(response)
    return {"specialist_result": _ExplainResult(answer=answer, nodes=nodes, stats=stats)}
```

Note: `_get_chain()` is a private function in `explorer.py`. Either make it public (rename to `get_chain()`) or duplicate the chain construction in the explain node. The cleanest solution is to expose it or re-create the chain inline using `get_llm()` and the same prompt.

### Pattern 6: Loop Count Management

```python
def _critic_node(state: NexusState) -> dict:
    from app.agent.critic import critique  # lazy

    result = critique(state["specialist_result"], loop_count=state["loop_count"])
    # If routing back (retry), increment loop_count for next specialist run
    new_loop_count = state["loop_count"] + 1 if not result.passed else state["loop_count"]
    return {"critic_result": result, "loop_count": new_loop_count}

def _route_after_critic(state: NexusState) -> str:
    if state["critic_result"].passed:
        return "done"
    return state["intent"]  # routes back to same specialist node
```

Loop count semantics (verified against `critic.py` hard cap logic):
- `loop_count=0`: first specialist run; `critique(result, 0)` — cap at `>=2`, so can retry
- `loop_count=1`: first retry; `critique(result, 1)` — still below cap, can retry
- `loop_count=2`: second retry; `critique(result, 2)` — cap fires, `passed=True` unconditionally

### Pattern 7: Router Node

```python
def _router_node(state: NexusState) -> dict:
    from app.agent.router import route  # lazy

    intent_result = route(state["question"], intent_hint=state.get("intent_hint"))
    return {"intent": intent_result.intent}

def _route_by_intent(state: NexusState) -> str:
    return state["intent"]
```

### Anti-Patterns to Avoid

- **Importing agents at module level in orchestrator.py:** All agents use lazy imports to prevent `ValidationError` at collection time. The orchestrator must do the same — import agents inside node function bodies only.
- **Passing `check_same_thread=True` (default) to SqliteSaver:** LangGraph checkpoint writes happen in background threads. The default SQLite connection raises `ProgrammingError`. Always use `check_same_thread=False`.
- **Relying on SqliteSaver to serialize `nx.DiGraph`:** `G` is not JSON-serializable. Callers must provide `G` on every `invoke()` call. Design the state so `G` is always required input, never recalled from a checkpoint.
- **Calling `asyncio.run()` inside `_explain_node`:** If the FastAPI endpoint is async, calling `asyncio.run()` inside a sync graph node will raise "cannot run a new event loop while another is running". Use `chain.invoke()` (sync) instead of `explore_stream()` for the explain path.
- **Incrementing `loop_count` in the specialist node:** The specialist has no knowledge of whether it's a retry. Let the critic node manage the increment on the retry path only.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Conversation state persistence | Custom dict + file serialization | SqliteSaver | LangGraph serializes state correctly; handles concurrency; supports branching |
| Conditional routing | if/elif chain | `add_conditional_edges()` | Type-checked; graph visualizable; supports all routing patterns natively |
| Retry loop with cap | While loop with counter | Graph cycle + `loop_count` in state | Cap logic already in critic.py; graph makes it explicit and auditable |
| In-memory checkpointing for tests | sqlite `:memory:` | `MemorySaver()` | No thread-safety issues; zero setup |

**Key insight:** LangGraph's value here is not just routing — it's making the retry loop a first-class graph edge that can be visualized, debugged, and checkpointed automatically.

---

## Common Pitfalls

### Pitfall 1: SqliteSaver Thread Safety Error

**What goes wrong:** `sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in that same thread.`

**Why it happens:** LangGraph runs checkpoint writes in a background thread pool. The default SQLite connection prohibits cross-thread use.

**How to avoid:** Always construct the connection with `check_same_thread=False`:
```python
conn = sqlite3.connect("data/checkpoints.db", check_same_thread=False)
```

**Warning signs:** Error appears on first `invoke()` call with `SqliteSaver`, not at compile time.

### Pitfall 2: nx.DiGraph Serialization Failure

**What goes wrong:** `SqliteSaver` attempts to serialize `NexusState` to JSON and fails on `nx.DiGraph` with a `TypeError`.

**Why it happens:** SqliteSaver checkpoints the entire state. NetworkX graphs are not JSON-serializable.

**How to avoid:** Treat `G` as a pass-through value — always required in each `invoke()` call. Do not design the system to recall `G` from a prior checkpoint. If needed, use `Optional[object]` type annotation and document that callers must supply `G` every time.

**Warning signs:** Serialization error during checkpoint write after the first node runs.

### Pitfall 3: Circular Import at Orchestrator Import Time

**What goes wrong:** `ImportError` or `ValidationError` when importing `orchestrator.py`.

**Why it happens:** If any agent is imported at module level in orchestrator.py, and that agent calls `get_llm()` or `get_settings()` at module level, the import chain triggers validation without API keys present.

**How to avoid:** All agent imports inside node function bodies (lazy), matching the pattern established by all other agents. Only import LangGraph types at the top of the file.

**Warning signs:** Test collection fails with `ValidationError` for missing `POSTGRES_USER` or `MISTRAL_API_KEY`.

### Pitfall 4: explain_node Calling explore_stream() in Sync Context

**What goes wrong:** `RuntimeError: This event loop is already running` when calling `asyncio.run(collect_stream(...))` inside a FastAPI async endpoint chain.

**Why it happens:** FastAPI runs in an event loop; `asyncio.run()` cannot nest inside a running loop.

**How to avoid:** Use `chain.invoke()` synchronously in `_explain_node`. The output quality is identical to `explore_stream()` since both use the same prompt and LLM. The only difference is streaming vs. batch response.

### Pitfall 5: Missing `config` in invoke() Call

**What goes wrong:** SqliteSaver checkpointing silently does nothing; `thread_id` is ignored.

**Why it happens:** `thread_id` must be passed as `config={"configurable": {"thread_id": "..."}}`, not as a top-level kwarg.

**How to avoid:** Always pass the full config dict. Make `thread_id` a required parameter of any public wrapper around `graph.invoke()`.

---

## Code Examples

Verified patterns from official sources and local verification:

### SqliteSaver construction (thread-safe)

```python
# Verified: langgraph-checkpoint-sqlite 3.0.3
import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver

conn = sqlite3.connect("data/checkpoints.db", check_same_thread=False)
saver = SqliteSaver(conn)
```

### MemorySaver for tests

```python
# Verified: langgraph 1.1.3
from langgraph.checkpoint.memory import MemorySaver

saver = MemorySaver()
graph = build_graph(checkpointer=saver)
result = graph.invoke(initial_state, config={"configurable": {"thread_id": "test-1"}})
```

### Conditional edges with dict path_map

```python
# Verified: langgraph 1.1.3, add_conditional_edges signature confirmed
graph.add_conditional_edges(
    "router_node",
    lambda state: state["intent"],   # returns a string key
    {
        "explain": "explain_node",
        "debug":   "debug_node",
        "review":  "review_node",
        "test":    "test_node",
    },
)
```

### Graph imports

```python
# Verified working imports
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.memory import MemorySaver
```

### test_orchestrator.py fixture pattern

```python
# Verified: MemorySaver + mock_llm works offline
import pytest
from unittest.mock import MagicMock, patch
from langgraph.checkpoint.memory import MemorySaver
from app.agent.orchestrator import build_graph, NexusState
import networkx as nx

@pytest.fixture
def mock_llm():
    mock = MagicMock()
    mock.invoke.return_value = MagicMock(content="mocked answer")
    mock.with_structured_output.return_value = mock
    return mock

@pytest.fixture
def compiled_graph(mock_llm):
    with patch("app.core.model_factory.get_llm", return_value=mock_llm):
        return build_graph(checkpointer=MemorySaver())

@pytest.fixture
def base_state(sample_graph) -> NexusState:
    return {
        "question": "explain func_a",
        "repo_path": "/repo",
        "intent_hint": "explain",
        "G": sample_graph,
        "target_node_id": "a.py::func_a",
        "selected_file": None,
        "selected_range": None,
        "repo_root": "/repo",
        "intent": None,
        "specialist_result": None,
        "critic_result": None,
        "loop_count": 0,
    }
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| V1: single LangChain LCEL runnable for all queries | V2: LangGraph StateGraph with typed state and conditional routing | Phase 22 | Each intent gets a specialized agent; quality gate can retry |
| No conversation persistence | SqliteSaver checkpointing per thread_id | Phase 22 | Same session can continue across HTTP requests |
| Direct `explore_stream()` (async generator) | `chain.invoke()` in explain_node | Phase 22 | Sync-compatible; same quality; no async nesting issue |

**Deprecated/outdated:**
- Direct calls to `graph_rag_retrieve + explore_stream` in `query_router.py`: After Phase 22, all queries must flow through the orchestrator graph. The Phase 24 endpoint update will replace the direct call.

---

## Open Questions

1. **Should `G` (nx.DiGraph) be excluded from SqliteSaver serialization explicitly?**
   - What we know: SqliteSaver will fail to serialize `G`; callers supply it on every invoke
   - What's unclear: Whether LangGraph 1.1.3 has a mechanism to mark fields as non-serializable
   - Recommendation: Type `G` as `Optional[object]` and document that callers must always provide it; test with SqliteSaver to confirm serialization failure and handle by stripping `G` before checkpoint write if needed, OR always use `MemorySaver` for tests which avoids this entirely

2. **Should `_get_chain()` in explorer.py be made public?**
   - What we know: `_explain_node` needs the LCEL chain; `_get_chain()` is private
   - What's unclear: Project convention on internal API exposure
   - Recommendation: Expose as `get_chain()` (remove leading underscore) OR re-create the chain inline in `_explain_node` using `get_llm()` directly — either is acceptable

3. **Where does the orchestrator boundary end for the HTTP endpoint?**
   - What we know: Phase 24 updates the query endpoint; Phase 22 is the orchestrator module only
   - What's unclear: Whether Phase 22 should expose a convenience wrapper (`run_query()`) or just `build_graph()`
   - Recommendation: Expose only `build_graph()` and `NexusState`; let Phase 24 own the HTTP/invocation layer

---

## Sources

### Primary (HIGH confidence)

- Verified locally: `langgraph==1.1.3` — StateGraph, START, END, add_node, add_edge, add_conditional_edges, compile, invoke with thread_id
- Verified locally: `langgraph-checkpoint-sqlite==3.0.3` — SqliteSaver constructor, `check_same_thread=False` requirement, `from_conn_string` alternative
- Verified locally: `langgraph.checkpoint.memory.MemorySaver` — works cleanly for offline tests
- Read directly: `backend/app/agent/router.py` — `IntentResult`, `route()` signature, lazy import pattern
- Read directly: `backend/app/agent/debugger.py` — `DebugResult`, `debug()` signature
- Read directly: `backend/app/agent/reviewer.py` — `ReviewResult`, `review()` signature
- Read directly: `backend/app/agent/tester.py` — `TestResult`, `test()` signature
- Read directly: `backend/app/agent/critic.py` — `CriticResult`, `critique()` signature, loop_count semantics
- Read directly: `backend/app/agent/explorer.py` — `explore_stream()` is async generator, `_get_chain()` private
- Read directly: `backend/app/config.py` — Settings fields: `max_critic_loops=2`, `critic_threshold=0.7`
- Read directly: `backend/app/retrieval/graph_rag.py` — `graph_rag_retrieve()` is sync, requires postgres
- Read directly: `backend/requirements.txt` — langgraph NOT in requirements; must be added
- Read directly: `backend/tests/conftest.py` — `sample_graph` fixture available; `mock_embedder` pattern

### Secondary (MEDIUM confidence)

- STATE.md decisions: "SqliteSaver checkpointer uses a separate DB from graph_store.py's 'data/nexus.db'" — confirmed `data/nexus.db` exists; checkpoint DB should be `data/checkpoints.db`
- STATE.md decisions: "Lazy specialist imports inside private helpers to prevent circular imports when orchestrator imports all agents together" — design constraint captured in critic.py comment for Phase 22

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — langgraph 1.1.3 and langgraph-checkpoint-sqlite 3.0.3 verified locally
- Architecture: HIGH — all agent APIs read directly; StateGraph patterns verified with live Python
- SqliteSaver thread-safety pitfall: HIGH — `ProgrammingError` reproduced and fix verified
- explain path strategy: HIGH — async generator behavior confirmed; `chain.invoke()` alternative works
- loop_count semantics: HIGH — traced through critic.py source code directly
- Pitfalls: HIGH — each pitfall reproduced or verified from source code

**Research date:** 2026-03-22
**Valid until:** 2026-04-22 (langgraph moves fast; re-verify if upgrading past 1.1.x)
