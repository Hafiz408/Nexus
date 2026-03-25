# Nexus — Graph-Grounded Code Intelligence

**Nexus** is an AI-powered code intelligence platform that helps developers understand, debug, and review code through semantic search, call-graph traversal, and multi-agent AI reasoning. It integrates a Python FastAPI backend with a VS Code extension for seamless in-editor experience.

## Features

### V1 — Graph-Grounded RAG
- **Semantic + graph-aware retrieval** — embed query, search pgvector (top-k), then expand via BFS in the call graph, rerank with PageRank + in-degree
- **Zero hallucination** — answers cite only retrieved nodes; fabricated file paths are filtered
- **Token streaming** — real-time feedback as the LLM generates the answer
- **File-level citations** — every retrieved node links to `file:line-range`; click to jump in editor
- **Incremental indexing** — file-save watcher re-indexes only changed files

### V2 — Intent-Routed Multi-Agent
| Intent | Specialist | What it does |
|--------|-----------|-------------|
| **Debug** | Debugger | BFS from entry nodes, anomaly scoring, suspect ranking with diagnosis |
| **Review** | Reviewer | 1-hop context assembly, structured findings (severity + category), GitHub PR posting |
| **Test** | Tester | Framework detection, ≥3 test functions, mock target enumeration, MCP file write |
| **Explain** | Explorer | Full graph-RAG (V1 path), same as V1 |
| **Auto** | Router | LLM intent classification; low confidence defaults to explain |

All V2 specialists feed into a **Critic** (deterministic quality gate: `0.4*G + 0.35*R + 0.25*A`). Scores below threshold trigger retries (max 2 loops).

---

## Quick Start

### Prerequisites
- Docker Compose v2+ | PostgreSQL 16+ with pgvector
- VS Code 1.74+ | Node.js 16+
- Python 3.10+ | Mistral or OpenAI API key

### 1. Start the Backend Stack

```bash
cd /Users/mohammedhafiz/Desktop/Personal/nexus
cp .env.example .env
# Edit .env with your API keys
docker compose up -d
```

Health check:
```bash
curl http://localhost:8000/health
# {"status":"ok","version":"1.0.0"}
```

### 2. Build & Install Extension

```bash
cd extension
npm install
npm run build
# In VS Code: Load unpacked extension from ./out/
```

### 3. Index Your Repo

Open VS Code command palette:
```
Ctrl+Shift+P → Nexus: Index Workspace
```

### 4. Query

Select intent pill (or "Auto") and type a question. SSE streams results in real-time.

---

## System Architecture

```
┌────────────────────────────────────────────────────────────┐
│             VS Code Extension (TypeScript)                 │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐   │
│  │ React Sidebar│  │ FileWatcher  │  │ HighlightSvc   │   │
│  │ (chat UI)    │  │ (incremental)│  │ (decorations)  │   │
│  └──────────────┘  └──────────────┘  └────────────────┘   │
└────────────┬─────────────────────────────────────────────────┘
             │ HTTP + SSE
             ▼
┌────────────────────────────────────────────────────────────┐
│             FastAPI Backend (Python 3.10+)                 │
│                                                             │
│  Ingestion    Retrieval       Multi-Agent System          │
│  ─────────    ─────────       ──────────────              │
│  · Walker     · pgvector      · Router (intent)           │
│  · AST parse  · BFS expand    · Specialists              │
│  · Embed      · Rerank        · Critic (quality)         │
│  · Graph      · Assemble      · Loop control             │
│  · FTS index                  · MCP tools                │
│                                                             │
│  ┌────────────────────────────────────────────────┐       │
│  │ API Routers (FastAPI)                          │       │
│  │ POST   /index         — trigger indexing       │       │
│  │ GET    /index/status  — poll progress          │       │
│  │ DELETE /index         — purge repo data        │       │
│  │ POST   /query         — SSE stream answers     │       │
│  │ GET    /health        — health check           │       │
│  └────────────────────────────────────────────────┘       │
└────────────┬─────────────────────────────────────────────────┘
             │
    ┌────────┴────────┐
    ▼                 ▼
PostgreSQL        SQLite
+ pgvector        · graph_nodes / graph_edges
(embeddings)      · code_fts (FTS5)
                  · checkpoints (LangGraph)
```

### Data Flow: Query → Answer

**V1 Path (Explain intent):**
```
Question
  ↓
Embed query (Mistral/OpenAI)
  ↓
Semantic search (pgvector, top-k=10)
  ↓
BFS expand (call graph, hop_depth=1)
  ↓
Rerank formula: semantic + 0.2*pagerank + 0.1*in_degree_norm
  ↓
Stream tokens (LLM with context block)
  ↓
SSE events: token, citations, done
```

**V2 Path (Intent-routed):**
```
Question + Intent Hint
  ↓
Router (classify intent)
  ↓
Specialist (Debug/Review/Test/Explorer)
  ↓
Critic (score = 0.4*G + 0.35*R + 0.25*A)
  ↓
If score < threshold AND loop_count < 2: retry specialist
Else: accept result
  ↓
MCP tools (optional: GitHub PR, write test file)
  ↓
SSE event: result + done
```

---

## Configuration

### Essential `.env` Variables

```bash
# PostgreSQL (docker-compose creates the DB)
postgres_user=nexus
postgres_password=nexus
postgres_db=nexus
postgres_host=postgres
postgres_port=5432

# Model providers
embedding_provider=mistral        # mistral | openai
llm_provider=mistral              # mistral | openai
mistral_api_key=sk-...            # Required if using Mistral
openai_api_key=sk-...             # Required if using OpenAI
model_name=mistral-small-latest   # or gpt-4o-mini, etc.
```

### Optional Variables

```bash
# LangSmith tracing (optional, for debugging)
langchain_tracing_v2=false
langchain_api_key=
langchain_project=nexus-v1

# V2 multi-agent tuning
max_critic_loops=2                # hard cap on retries
critic_threshold=0.7              # min score to pass
debugger_max_hops=4               # BFS depth for debugging
reviewer_context_hops=1           # 1-hop context for review

# GitHub integration
github_token=                      # empty string disables posting
```

### Extension Settings (`.vscode/settings.json`)

```json
{
  "nexus.backendUrl": "http://localhost:8000",
  "nexus.hopDepth": 1,
  "nexus.maxNodes": 10
}
```

---

## Project Structure

```
nexus/
├── README.md                      # This file
├── docker-compose.yml             # PostgreSQL + backend
├── .env.example
│
├── backend/
│   ├── README.md                  # Backend architecture
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── app/
│   │   ├── main.py                # FastAPI app, lifespan, routes
│   │   ├── config.py              # Settings (Pydantic)
│   │   ├── models/
│   │   │   └── schemas.py         # CodeNode, CodeEdge, QueryRequest, etc.
│   │   ├── api/
│   │   │   ├── index_router.py    # POST /index, GET /status, DELETE /index
│   │   │   └── query_router.py    # POST /query (V1 + V2 SSE)
│   │   ├── ingestion/
│   │   │   ├── README.md          # Ingestion pipeline architecture
│   │   │   ├── pipeline.py        # Orchestrator (concurrent parsing, deduping)
│   │   │   ├── ast_parser.py      # tree-sitter parsing (Python + TypeScript)
│   │   │   ├── graph_builder.py   # Edge resolution, PageRank, metrics
│   │   │   ├── embedder.py        # Dense + FTS indexing (batched upserts)
│   │   │   ├── graph_store.py     # SQLite persistence (nodes, edges)
│   │   │   ├── walker.py          # File discovery
│   │   │   └── fts_search.py      # (if exists)
│   │   ├── retrieval/
│   │   │   ├── README.md          # Graph RAG algorithm details
│   │   │   └── graph_rag.py       # 3-step: semantic → expand → rerank
│   │   ├── agent/
│   │   │   ├── README.md          # Multi-agent orchestration
│   │   │   ├── router.py          # Intent classification
│   │   │   ├── orchestrator.py    # LangGraph StateGraph
│   │   │   ├── critic.py          # Quality gate (deterministic)
│   │   │   ├── debugger.py        # Bug localization
│   │   │   ├── reviewer.py        # Code review (1-hop context)
│   │   │   ├── tester.py          # Test generation
│   │   │   ├── explorer.py        # V1 chain (token streaming)
│   │   │   └── prompts.py         # System prompts
│   │   ├── core/
│   │   │   └── model_factory.py   # Provider-agnostic LLM/embedding clients
│   │   ├── mcp/
│   │   │   ├── README.md          # MCP tool layer
│   │   │   └── tools.py           # GitHub PR posting, file writes
│   │   ├── db/
│   │   │   └── database.py        # PostgreSQL connection
│   │   └── __init__.py
│   ├── data/
│   │   ├── nexus.db               # SQLite: graph nodes, edges, FTS5
│   │   └── checkpoints.db         # LangGraph state (separate DB)
│   └── .env
│
└── extension/
    ├── README.md                  # Extension architecture
    ├── package.json
    ├── tsconfig.json
    ├── src/
    │   ├── extension.ts           # Activation, command registration
    │   ├── SidebarProvider.ts     # Webview provider, message handling
    │   ├── BackendClient.ts       # HTTP client
    │   ├── FileWatcher.ts         # Incremental re-index
    │   ├── HighlightService.ts    # Editor decorations
    │   ├── SseStream.ts           # SSE event handler
    │   ├── types.ts               # TypeScript interfaces
    │   └── webview/
    │       ├── App.tsx            # React UI (chat, results)
    │       └── ...
    └── media/
        └── nexus.svg              # Sidebar icon
```

---

## Key Design Decisions

### 1. Provider-Agnostic Model Factory

All LLM and embedding calls go through `model_factory.py`. Providers are registered:

```python
_EMBEDDING_CLIENTS = {
    "mistral": MistralEmbeddingClient,
    "openai": OpenAIEmbeddingClient,
}

def get_embedding_client() -> EmbeddingClient:
    provider = settings.embedding_provider  # from .env
    return _EMBEDDING_CLIENTS[provider](api_key)
```

**Adding a new provider:**
1. Subclass `EmbeddingClient`
2. Register in `_EMBEDDING_CLIENTS`
3. Add case to `get_llm()`
4. Add `<provider>_api_key` to `Settings`
5. Update `.env`

⚠️ **Note:** Switching embedding providers requires a full re-index (dimensions differ: Mistral=1024, OpenAI=1536).

### 2. Lazy Imports for API Key Validation

All agent modules import LLM clients inside function bodies, not at module level. This allows pytest to collect tests without requiring API keys:

```python
def route(question: str) -> IntentResult:
    from app.core.model_factory import get_llm  # Inside function
    llm = get_llm()
    ...
```

### 3. Graph-First Representation

Call and import edges are first-class. Retrieval uses:
- **Semantic search** (pgvector cosine similarity)
- **BFS expansion** (NetworkX ego_graph, undirected)
- **Weighted reranking** (semantic + PageRank + in-degree)

Result: grounded reasoning, fewer hallucinations.

### 4. SSE Streaming

Both V1 and V2 use Server-Sent Events:
- **V1:** Streams tokens as they arrive from LLM
- **V2:** Waits for full result, streams single `result` event

This provides immediate feedback and works within async FastAPI constraints.

### 5. Deterministic Quality Gate (No LLM)

The Critic applies a fixed formula, no LLM call:

```
score = 0.4 * groundedness + 0.35 * relevance + 0.25 * actionability
```

Keeps loops deterministic and cost-effective.

### 6. Hard Cap on Retries

Multi-agent loops always terminate:

```python
if loop_count >= max_critic_loops:  # default 2
    return CriticResult(passed=True, ...)  # Force accept
```

### 7. Separate Checkpoint Database

LangGraph checkpoints persist to `data/checkpoints.db` (separate from `data/nexus.db`). NetworkX DiGraphs are not JSON-serializable, so they are passed fresh on each invoke and never checkpointed.

### 8. Per-Request Thread IDs

Each query gets a unique thread ID to prevent state bleed:

```python
thread_id = f"{repo_path}::{uuid4()}"
graph.invoke(state, {"configurable": {"thread_id": thread_id}})
```

---

## End-to-End Flows

### V1 Query Execution

1. Extension sends `POST /query` with `intent_hint=null` or `"auto"`
2. Backend routes to V1 path
3. `graph_rag_retrieve()`:
   - Embed query → pgvector cosine search → top-k seeds
   - BFS expand from seeds (hop_depth, both directions)
   - Rerank: `semantic + 0.2*pagerank + 0.1*in_degree_norm`
4. `explore_stream()` chains SYSTEM_PROMPT + context + question
5. SSE yields: `token` events, then `citations`, then `done`
6. Extension highlights citations in editor

### V2 Query Execution (Debug Example)

1. Extension sends `POST /query` with `intent_hint="debug"`, `target_node_id="..."`, `question="..."`
2. Backend routes to V2 path
3. LangGraph orchestrator invokes:
   - **router_node:** Skips LLM (hint is valid), returns `intent="debug"`
   - **debug_node:**
     - Find entry nodes from question
     - BFS forward along CALLS edges (max_hops=4)
     - Score each with 5-factor anomaly formula
     - LLM call for grounded diagnosis
     - Return `DebugResult(suspects, traversal_path, impact_radius, diagnosis)`
   - **critic_node:**
     - Extract cited nodes vs retrieved nodes → groundedness
     - Check suspects + diagnosis presence → relevance
     - Count suspects → actionability
     - Score = weighted combo, threshold check
     - If passed: route to done; else: route back to debug_node
4. SSE yields single event: `result` + `done`
5. Extension displays findings, offers "Post to PR" if GitHub token present

---

## Monitoring & Debugging

### Backend Logs

```bash
docker logs -f nexus_backend
```

Watch for parse errors, embedding failures, LLM rate limits, PostgreSQL issues.

### Indexing Status

```bash
curl http://localhost:8000/index/status?repo_path=/path/to/repo
```

Response:
```json
{
  "status": "running",
  "nodes_indexed": 2500,
  "edges_indexed": 4200,
  "files_processed": 150,
  "error": null
}
```

### LangSmith Tracing

Enable in `.env`:
```bash
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=ls_...
```

Visit https://smith.langchain.com to inspect calls, latencies, token usage.

---

## Performance Notes

- **Indexing:** ~100 LOC/sec (concurrent parsing, semaphore=10)
- **Retrieval:** pgvector IVFFlat scales to 100k+ nodes, <100ms queries
- **Agent loops:** 5–15s per loop (depends on LLM latency)
- **Memory:** ~500MB baseline + 1MB per 1k nodes
- **Docker startup:** ~15s (PostgreSQL health checks)

---

## Extending Nexus

### Add a New Specialist Agent

1. Create `backend/app/agent/mynewagent.py`
2. Define `MyResult` (Pydantic) and `mynewagent(question, G, ...) -> MyResult`
3. Use lazy imports: `from app.core.model_factory import get_llm`
4. Add `_mynewagent_node()` to `orchestrator.py`
5. Extend StateGraph with conditional edge
6. Update Router prompt

### Add Embedding Provider

1. Subclass `EmbeddingClient` in `model_factory.py`
2. Implement `embed()` and `dimensions`
3. Register in `_EMBEDDING_CLIENTS`
4. Add `<provider>_api_key` to `Settings`
5. **Re-index** (dimension change requires full re-index)

### Add MCP Tool

1. Create function in `backend/app/mcp/tools.py`
2. Import and call from agent result handler in `query_router.py`
3. Return `{"success": bool, ...}`

---

## Troubleshooting

**Docker won't start:**
```bash
docker compose down -v && docker compose up
```

**Index stuck:**
```bash
curl -X DELETE http://localhost:8000/index?repo_path=/path/to/repo
```

**Backend can't connect:**
- Check `.env` (postgres_host, postgres_password)
- Check `docker logs nexus_postgres`

**LLM returns empty:**
- Verify API key in `.env`
- Check `docker logs nexus_backend` for ValidationError
- Test: `curl -X POST http://localhost:8000/query -H "Content-Type: application/json" -d '{"question":"test","repo_path":"/path"}'`

**Slow retrieval:**
- Increase `hop_depth` (default 1)
- Check `expanded_count` in SSE `done` event
- Monitor pgvector: `docker exec nexus_postgres psql -U nexus -d nexus -c "SELECT COUNT(*) FROM code_embeddings;"`

---

## License & Contributing

See `CONTRIBUTING.md` for guidelines. Licensed under MIT.
