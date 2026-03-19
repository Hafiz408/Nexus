# Nexus

A VS Code extension backed by a FastAPI multi-agent backend that parses a codebase into a structural **code graph** and uses **graph-traversal RAG** to answer questions grounded in the actual code structure — not just text similarity.

V1 ships one complete, demoable feature: the **Explorer agent** — ask any question about how the codebase works, get a cited, grounded answer with file:line references and highlighted code in the editor.

## What it does

Open any Python or TypeScript repo in VS Code → Nexus indexes it → Ask "How does user authentication work?" → Get a streamed, cited answer with the relevant files highlighted in the editor.

**Indexing pipeline:**
1. **File walker** — traverses repo respecting `.gitignore`, skips noise dirs, detects language
2. **AST parser** — extracts functions, classes, and methods via tree-sitter with signatures, docstrings, and complexity
3. **Graph builder** — builds a NetworkX DiGraph with CALLS/IMPORTS edge resolution and PageRank scoring
4. **Embedder** — stores nodes in pgvector (semantic search) and SQLite FTS5 (exact name search)
5. **Pipeline** — orchestrates steps 1–4 concurrently, exposed over HTTP via FastAPI

**Query pipeline:**
1. **Graph RAG** — 3-step retrieval: semantic search → BFS graph expansion → PageRank reranking
2. **Explorer agent** — LangChain streaming agent generates grounded, cited answers with LangSmith tracing
3. **SSE endpoint** — `POST /query` streams `token → citations → done` events over HTTP

**VS Code extension:**
- Sidebar chat UI with real-time token streaming and citation chips
- Auto-indexes workspace on open; incremental re-index on file save (2s debounce)
- Clickable citations open the referenced file at the cited line with editor highlight decorations

## Quickstart

**Prerequisites:** Docker Desktop, Python 3.11+, Node.js 18+, an OpenAI API key

```bash
# 1. Clone and configure
cp .env.example .env
# Edit .env — add OPENAI_API_KEY at minimum

# 2. Start the backend stack
docker compose up -d

# 3. Verify backend is healthy
curl http://localhost:8000/health
# → {"status":"ok","version":"1.0.0"}

# 4. Index a repo
curl -s -X POST http://localhost:8000/index \
  -H "Content-Type: application/json" \
  -d '{"repo_path": "/path/to/your/repo", "languages": ["python"]}'
# → {"status":"pending","repo_path":"/path/to/your/repo"}

# 5. Poll indexing status
curl "http://localhost:8000/index/status?repo_path=/path/to/your/repo"
# → {"status":"complete","nodes_indexed":142,"edges_indexed":87,"files_processed":23}

# 6. Query via SSE (curl)
curl -s -N -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "How does authentication work?", "repo_path": "/path/to/your/repo"}'
# streams: event: token, event: citations, event: done
```

**VS Code extension:**
```bash
cd extension
npm install
npm run build
# Press F5 in VS Code to open the Extension Development Host
# Click the Nexus icon in the Activity Bar
```

## Repository structure

```
nexus/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app + lifespan + CORS + graph_cache
│   │   ├── config.py            # Settings (pydantic-settings, .env-driven)
│   │   ├── api/
│   │   │   ├── index_router.py  # POST /index, GET /index/status, DELETE /index
│   │   │   └── query_router.py  # POST /query — SSE streaming endpoint
│   │   ├── db/
│   │   │   └── database.py      # PostgreSQL connection + pgvector init
│   │   ├── ingestion/
│   │   │   ├── walker.py        # walk_repo() — repo traversal
│   │   │   ├── ast_parser.py    # parse_file() — tree-sitter AST extraction
│   │   │   ├── graph_builder.py # build_graph() — NetworkX DiGraph + PageRank
│   │   │   ├── graph_store.py   # save/load/delete graph in SQLite
│   │   │   ├── embedder.py      # embed_and_store() — pgvector + FTS5
│   │   │   └── pipeline.py      # run_ingestion() — full orchestration
│   │   ├── retrieval/
│   │   │   └── graph_rag.py     # graph_rag_retrieve() — 3-step graph RAG
│   │   ├── agent/
│   │   │   ├── prompts.py       # SYSTEM_PROMPT — anti-fabrication citation rules
│   │   │   └── explorer.py      # explore_stream() — LangChain streaming agent
│   │   └── models/
│   │       └── schemas.py       # CodeNode, CodeEdge, IndexStatus, IndexRequest, QueryRequest
│   ├── tests/                   # pytest test suite (89 tests)
│   ├── Dockerfile
│   └── requirements.txt
├── extension/
│   ├── src/
│   │   ├── extension.ts         # activate() — registers provider + FileWatcher
│   │   ├── SidebarProvider.ts   # WebviewView — bridges extension host ↔ React UI
│   │   ├── BackendClient.ts     # HTTP client for /index and /query
│   │   ├── SseStream.ts         # fetch + ReadableStream SSE consumer
│   │   ├── HighlightService.ts  # Editor decoration — findMatchHighlightBackground
│   │   ├── FileWatcher.ts       # Debounced incremental re-index on file save
│   │   ├── types.ts             # Shared discriminated union message types
│   │   └── webview/
│   │       ├── App.tsx          # React 18 chat UI — streaming, citations, status
│   │       ├── index.tsx        # createRoot entry point
│   │       └── index.css        # VS Code CSS variables only
│   ├── media/
│   │   └── nexus.svg            # Activity bar icon
│   ├── esbuild.js               # Dual-bundle build (node/cjs + browser/iife)
│   ├── package.json             # VS Code extension manifest
│   └── tsconfig*.json           # Separate tsconfigs for host and webview
├── eval/
│   ├── golden_qa.json           # 30 Q&A pairs for RAGAS evaluation
│   ├── run_ragas.py             # Dual-mode eval: graph RAG vs naive vector search
│   └── results/                 # Timestamped JSON results (git-tracked directory)
├── data/                        # SQLite persistence (bind-mounted into container)
├── docker-compose.yml
└── .env.example
```

## API reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/index` | Start indexing a repo (non-blocking, background task) |
| `GET` | `/index/status?repo_path=...` | Poll indexing progress |
| `DELETE` | `/index?repo_path=...` | Remove all stored data for a repo |
| `POST` | `/query` | Stream a cited answer via SSE |
| `GET` | `/health` | Health check |

**POST /index request body:**
```json
{
  "repo_path": "/absolute/path/to/repo",
  "languages": ["python", "typescript"],
  "changed_files": null
}
```

Set `changed_files` to a list of absolute file paths for incremental re-index (only re-parses listed files).

**POST /query request body:**
```json
{
  "question": "How does authentication work?",
  "repo_path": "/absolute/path/to/repo",
  "max_nodes": 10,
  "hop_depth": 1
}
```

**POST /query SSE event sequence:**
```
event: token
data: {"content": "The authentication..."}

event: token
data: {"content": " middleware is..."}

event: citations
data: [{"file_path": "app/auth.py", "name": "verify_token", "line_start": 42, "line_end": 58}]

event: done
data: {"nodes_retrieved": 8, "nodes_expanded": 23, "elapsed_ms": 1240}
```

On error: `event: error` with `data: {"detail": "..."}`.

## Running the RAGAS evaluation

Requires a running backend with an indexed repo and a valid `OPENAI_API_KEY`.

```bash
# Index the FastAPI source repo first
curl -X POST http://localhost:8000/index \
  -d '{"repo_path": "/path/to/fastapi", "languages": ["python"]}'

# Run the comparative evaluation
cd eval
python run_ragas.py --repo-path /path/to/fastapi

# Results written to eval/results/ragas_comparison_{timestamp}.json
```

Evaluates three metrics (Faithfulness, ResponseRelevancy, ContextPrecision) across 30 golden Q&A pairs for both graph-traversal RAG and naive vector-only retrieval.

## Development

See [backend/README.md](backend/README.md) for backend setup, running tests, and environment configuration.

**Run backend tests:**
```bash
cd backend
pytest tests/ -v
# 89 unit tests pass without external services
# 4 embedder tests require a running Postgres container
```

**Build the extension:**
```bash
cd extension
npm install
npm run build        # dual esbuild: out/extension.js + out/webview/index.js
npm run typecheck    # tsc --noEmit for both host and webview tsconfigs
```

## Environment variables

Copy `.env.example` to `.env` and fill in:

| Variable | Required | Description |
|----------|----------|-------------|
| `POSTGRES_USER` | Yes | PostgreSQL username |
| `POSTGRES_PASSWORD` | Yes | PostgreSQL password |
| `POSTGRES_DB` | Yes | PostgreSQL database name |
| `POSTGRES_HOST` | Yes | PostgreSQL host (`postgres` inside Docker) |
| `POSTGRES_PORT` | Yes | PostgreSQL port (`5432` inside Docker) |
| `OPENAI_API_KEY` | Yes | OpenAI API key for embeddings and LLM |
| `LANGCHAIN_API_KEY` | No | LangSmith API key for tracing |
| `LANGCHAIN_TRACING_V2` | No | Set `true` to enable LangSmith traces |
| `LANGCHAIN_PROJECT` | No | LangSmith project name |

## Build status

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Infrastructure (Docker + pgvector) | ✓ Complete |
| 2 | File Walker | ✓ Complete |
| 3 | AST Parser | ✓ Complete |
| 4 | Graph Builder | ✓ Complete |
| 5 | Embedder (pgvector + FTS5) | ✓ Complete |
| 6 | Pipeline (orchestration) | ✓ Complete |
| 7 | Index Endpoint (HTTP API) | ✓ Complete |
| 7.1 | Tech Debt Cleanup | ✓ Complete |
| 8 | Graph RAG retrieval | ✓ Complete |
| 9 | Explorer Agent (LangChain streaming) | ✓ Complete |
| 10 | Query Endpoint (SSE) | ✓ Complete |
| 11 | VS Code Extension | ✓ Complete |
| 12 | Highlighter (editor decorations) | ✓ Complete |
| 13 | File Watcher (incremental re-index) | ✓ Complete |
| 14 | RAGAS Evaluation | ✓ Complete |
