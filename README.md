# Nexus

**AI-powered code intelligence for VS Code.** Index your repository, then ask questions, debug issues, get code reviews, and generate tests — all grounded in your actual call graph and code structure.

---

## Features

### V1 — Code Intelligence Chat
- **Semantic + graph-aware retrieval** — combines vector similarity search with BFS traversal of your call graph for grounded, citation-backed answers
- **File-level citations** — every answer links to exact `file:line` sources; click to jump there in the editor
- **Incremental indexing** — file-save watcher re-indexes only changed files (2 s debounce)
- **Zero hallucination policy** — answers cite only retrieved nodes; fabricated file paths are filtered out

### V2 — Multi-Agent Team
| Intent | What it does |
|--------|-------------|
| **Debug** | Traverses the call graph forward from the failing function, scores each node on 5 anomaly factors, returns a ranked suspect list with line numbers and a diagnosis |
| **Review** | Assembles 1-hop caller/callee context, generates structured findings with severity badges (critical / warning / info), and can post inline comments to a GitHub PR |
| **Test** | Detects your test framework (pytest / jest / vitest / junit), generates ≥ 3 test functions with correct mock targets, derives the test file path by convention |
| **Explain** | Full graph-RAG answer with citations (V1 path, unchanged) |
| **Auto** | Router agent classifies the query and picks the best intent automatically |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  VS Code Extension                                              │
│  ┌─────────────────┐   messages   ┌────────────────────────┐   │
│  │  Webview (React)│ ◄──────────► │  SidebarProvider       │   │
│  │  Intent pills   │              │  SseStream              │   │
│  │  Result panels  │              │  Highlighter            │   │
│  └─────────────────┘              └────────────┬───────────┘   │
└──────────────────────────────────────────────────┼─────────────┘
                                                   │ HTTP / SSE
                                                   ▼
┌─────────────────────────────────────────────────────────────────┐
│  FastAPI Backend                                                │
│                                                                 │
│  POST /index ──► Ingestion Pipeline                             │
│                  Walker → AST Parser → Graph Builder → Embedder │
│                                  │               │              │
│                           SQLite (graph)   pgvector + FTS5      │
│                                                                 │
│  POST /query ──► V1 path: Graph RAG → Explorer Agent → SSE      │
│              └─► V2 path: LangGraph Orchestrator → SSE          │
│                           Router → Specialist → Critic          │
│                                                │                │
│                                          MCP Tools              │
│                                   (GitHub PR / Filesystem)      │
└─────────────────────────────────────────────────────────────────┘
```

---

## Quickstart

### Prerequisites

| Tool | Version |
|------|---------|
| Docker & Docker Compose | 24+ |
| Node.js | 18+ |
| VS Code | 1.74+ |
| OpenAI or Mistral API key | — |

### 1. Start the backend

```bash
git clone <repo-url>
cd nexus
cp .env.example .env
# Edit .env — set OPENAI_API_KEY or MISTRAL_API_KEY
docker-compose up
```

Verify:

```bash
curl http://localhost:8000/health
# {"status":"ok","version":"1.0.0"}
```

### 2. Build and install the extension

```bash
cd extension
npm install
npm run build
```

In VS Code press **F5** to open an Extension Development Host, or install the `.vsix` directly via **Extensions → Install from VSIX…**

### 3. Index your repository

Open the **Nexus sidebar** (activity bar icon), click **Index Workspace**. Progress is shown inline. A typical 10k-file repo takes ~30 s.

### 4. Ask a question

Select an intent pill and type your query:

```
Auto    →  "What does the auth middleware do?"
Debug   →  "Why does graph_rag_retrieve return empty results for large repos?"
Review  →  "Review query_router.py for security issues"
Test    →  "Generate tests for the embedder"
```

---

## Environment Variables

See [`.env.example`](.env.example) for the full list. Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql://...` | PostgreSQL connection string |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `MISTRAL_API_KEY` | — | Mistral API key |
| `LLM_PROVIDER` | `openai` | `openai` or `mistral` |
| `EMBEDDING_PROVIDER` | `openai` | `openai` or `mistral` |
| `GITHUB_TOKEN` | — | Enables "Post to GitHub PR" in Review panel |
| `MAX_CRITIC_LOOPS` | `2` | Max retry loops before Critic forces pass |
| `CRITIC_THRESHOLD` | `0.7` | Minimum quality score (0.0–1.0) |
| `DEBUGGER_MAX_HOPS` | `4` | BFS depth for call-graph traversal |
| `REVIEWER_CONTEXT_HOPS` | `1` | Context hops around review target |

---

## Project Structure

```
nexus/
├── backend/          # FastAPI backend, ingestion pipeline, V2 agents
│   └── README.md     # Backend architecture, API reference, flow diagrams
├── extension/        # VS Code extension (React webview + host)
│   └── README.md     # Extension architecture, message flow, build guide
├── eval/             # RAGAS evaluation suite
│   └── README.md     # Evaluation methodology and baseline results
├── data/             # SQLite graph store + LangGraph checkpoints (bind-mounted)
├── docker-compose.yml
└── .env.example
```

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Backend framework | FastAPI + Uvicorn |
| Vector store | PostgreSQL + pgvector |
| Graph store | SQLite + NetworkX |
| Full-text search | SQLite FTS5 |
| Code parsing | tree-sitter (Python, TypeScript) |
| LLM orchestration | LangGraph + LangChain |
| LLM providers | OpenAI / Mistral (switchable) |
| Extension UI | React 18 + VS Code API |
| Build tooling | esbuild (dual-bundle: host + webview) |

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/index` | Start indexing a repo (non-blocking, background task) |
| `GET` | `/index/status?repo_path=...` | Poll indexing progress |
| `DELETE` | `/index?repo_path=...` | Remove all stored data for a repo |
| `POST` | `/query` | Stream a cited answer via SSE |
| `GET` | `/health` | Health check |

Full request/response schemas and SSE event sequences are documented in [`backend/README.md`](backend/README.md).

---

## Test Suite

```bash
source venv/bin/activate
python -m pytest backend/tests/ -v
# 190 passed in ~7 s — no live API calls required
```

All 190 tests use mock LLMs and mock graphs. The full suite runs offline.

---

## Milestone History

| Milestone | Phases | Status |
|-----------|--------|--------|
| V1.0 MVP | 1–15 | ✅ Shipped 2026-03-21 |
| V2.0 Multi-Agent Team | 16–26 | ✅ Complete 2026-03-22 |

---

## License

MIT
