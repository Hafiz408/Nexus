# Nexus

A VS Code extension backed by a FastAPI multi-agent backend that parses a codebase into a structural **code graph** and uses **graph-traversal RAG** to answer questions grounded in the actual code structure — not just text similarity.

V1 ships one complete, demoable feature: the **Explorer agent** — ask any question about how the codebase works, get a cited, grounded answer with file:line references and highlighted code in the editor.

## What it does

Open any Python or TypeScript repo in VS Code → Nexus indexes it → Ask "How does user authentication work?" → Get a streamed, cited answer with the relevant files highlighted in the editor.

The indexing pipeline:
1. **File walker** — traverses repo respecting `.gitignore`, skips noise dirs, detects language
2. **AST parser** — extracts functions, classes, and methods via tree-sitter with signatures, docstrings, and complexity
3. **Graph builder** — builds a NetworkX DiGraph with CALLS/IMPORTS edge resolution and PageRank scoring
4. **Embedder** — stores nodes in pgvector (semantic search) and SQLite FTS5 (exact name search)
5. **Pipeline** — orchestrates steps 1–4 concurrently, exposed over HTTP via FastAPI

## Quickstart

**Prerequisites:** Docker Desktop, Python 3.11+, an OpenAI API key

```bash
# 1. Clone and configure
cp .env.example .env
# Edit .env — add your OPENAI_API_KEY at minimum

# 2. Start the stack
docker compose up -d

# 3. Verify
curl http://localhost:8000/health
# → {"status":"ok","version":"1.0.0"}

# 4. Index a repo
curl -s -X POST http://localhost:8000/index \
  -H "Content-Type: application/json" \
  -d '{"repo_path": "/path/to/your/repo", "languages": ["python"]}'
# → {"status":"pending","repo_path":"/path/to/your/repo"}

# 5. Poll status
curl "http://localhost:8000/index/status?repo_path=/path/to/your/repo"
# → {"status":"complete","nodes_indexed":142,"edges_indexed":87,"files_processed":23}
```

## Repository structure

```
nexus/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app + lifespan + CORS
│   │   ├── config.py            # Settings (pydantic-settings, .env-driven)
│   │   ├── api/
│   │   │   └── index_router.py  # POST /index, GET /index/status, DELETE /index
│   │   ├── db/
│   │   │   └── database.py      # PostgreSQL connection + pgvector init
│   │   ├── ingestion/
│   │   │   ├── walker.py        # walk_repo() — repo traversal
│   │   │   ├── ast_parser.py    # parse_file() — tree-sitter AST extraction
│   │   │   ├── graph_builder.py # build_graph() — NetworkX DiGraph
│   │   │   ├── graph_store.py   # save/load/delete graph in SQLite
│   │   │   ├── embedder.py      # embed_and_store() — pgvector + FTS5
│   │   │   └── pipeline.py      # run_ingestion() — full orchestration
│   │   └── models/
│   │       └── schemas.py       # CodeNode, CodeEdge, IndexStatus, IndexRequest
│   ├── tests/                   # pytest test suite
│   ├── Dockerfile
│   └── requirements.txt
├── data/                        # SQLite persistence (bind-mounted into container)
├── docker-compose.yml
└── .env.example
```

## API reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/index` | Start indexing a repo (non-blocking) |
| `GET` | `/index/status?repo_path=...` | Poll indexing progress |
| `DELETE` | `/index?repo_path=...` | Remove all stored data for a repo |
| `GET` | `/health` | Health check |

**POST /index request body:**
```json
{
  "repo_path": "/absolute/path/to/repo",
  "languages": ["python", "typescript"],
  "changed_files": null
}
```

Set `changed_files` to a list of absolute file paths to trigger incremental re-index (only re-parses listed files).

## Development

See [backend/README.md](backend/README.md) for backend setup, running tests, and environment configuration.

## Environment variables

Copy `.env.example` to `.env` and fill in:

| Variable | Required | Description |
|----------|----------|-------------|
| `POSTGRES_USER` | Yes | PostgreSQL username |
| `POSTGRES_PASSWORD` | Yes | PostgreSQL password |
| `POSTGRES_DB` | Yes | PostgreSQL database name |
| `POSTGRES_HOST` | Yes | PostgreSQL host (use `postgres` inside Docker) |
| `POSTGRES_PORT` | Yes | PostgreSQL port (use `5432` inside Docker) |
| `OPENAI_API_KEY` | Yes | OpenAI API key for embeddings |
| `LANGCHAIN_API_KEY` | No | LangSmith API key (Phase 9+) |
| `LANGCHAIN_TRACING_V2` | No | Enable LangSmith tracing (Phase 9+) |
| `LANGCHAIN_PROJECT` | No | LangSmith project name (Phase 9+) |

## Build status

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Infrastructure (Docker + pgvector) | Complete |
| 2 | File Walker | Complete |
| 3 | AST Parser | Complete |
| 4 | Graph Builder | Complete |
| 5 | Embedder (pgvector + FTS5) | Complete |
| 6 | Pipeline (orchestration) | Complete |
| 7 | Index Endpoint (HTTP API) | Complete |
| 8 | Graph RAG retrieval | Planned |
| 9 | Explorer Agent (LangChain) | Planned |
| 10 | Query Endpoint (SSE) | Planned |
| 11 | VS Code Extension | Planned |
| 12 | Highlighter | Planned |
| 13 | File Watcher | Planned |
| 14 | RAGAS Evaluation | Planned |
