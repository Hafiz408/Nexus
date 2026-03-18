# Nexus Backend

FastAPI backend for the Nexus codebase intelligence system. Implements the ingestion pipeline that parses a Python or TypeScript repo into a code graph stored in PostgreSQL (pgvector) and SQLite (FTS5 + graph).

## Setup

The backend runs inside Docker. For local development without Docker (e.g. running tests):

```bash
cd backend

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# Install dependencies
pip install -r requirements.txt

# Run tests (no external services needed for unit tests)
pytest tests/ -v
```

**With Docker (full stack):**

```bash
# From repo root
docker compose up -d

# Tail backend logs
docker compose logs -f backend
```

## Running tests

```bash
cd backend

# All tests
pytest tests/ -v

# Specific module
pytest tests/test_file_walker.py -v
pytest tests/test_ast_parser.py -v
pytest tests/test_graph_builder.py -v
pytest tests/test_pipeline.py -v
pytest tests/test_embedder.py -v  # Note: 3 tests require POSTGRES_DB env var
```

Tests use `tmp_path` fixtures — no external services required for ingestion unit tests. The embedder tests that hit pgvector require a running Postgres container and valid `OPENAI_API_KEY`.

## Module overview

### `app/config.py`

Typed settings class backed by pydantic-settings. Reads all config from `.env` via `SettingsConfigDict(env_file=".env")`. Retrieved via `get_settings()` (cached with `@lru_cache`).

### `app/db/database.py`

PostgreSQL connection management. `init_db()` runs `CREATE EXTENSION IF NOT EXISTS vector` on startup (called from lifespan). `get_db_connection()` returns a psycopg2 connection.

### `app/models/schemas.py`

Shared Pydantic models used across all ingestion modules:
- `CodeNode` — a parsed function, class, or method (node_id, name, file_path, language, node_type, signature, docstring, body_preview, embedding_text, complexity, line_start, line_end)
- `CodeEdge` — edge definition (source_id, target_name, edge_type)
- `IndexStatus` — ingestion progress (status, nodes_indexed, edges_indexed, files_processed, error)
- `IndexRequest` — POST /index body (repo_path, languages, changed_files)

### `app/ingestion/walker.py`

`walk_repo(repo_path, languages, max_file_size_kb=500)` → `list[FileEntry]`

Traverses a repo using `os.walk`, respects `.gitignore` at every directory level (via pathspec), skips noise directories (`.git`, `node_modules`, `__pycache__`, etc.), and detects language from file extension.

### `app/ingestion/ast_parser.py`

`parse_file(file_path, repo_root, language)` → `(list[CodeNode], list[tuple])`

Parses a single source file using tree-sitter. Extracts functions, classes, and methods with their signatures, docstrings, body previews, and complexity scores. Also emits raw CALLS and IMPORTS edge tuples for graph construction.

Supports Python and TypeScript (including `.tsx`, `.jsx`).

Node IDs use the format `"relative/path/to/file.py::function_name"`.

### `app/ingestion/graph_builder.py`

`build_graph(nodes, raw_edges)` → `nx.DiGraph`

Builds a directed graph from parsed nodes and raw edges. Resolves CALLS edges by matching `target_name` against the full node registry. Resolves IMPORTS edges by linking the importing file's nodes to all nodes in the imported file. Computes PageRank, in-degree, and out-degree as node attributes.

### `app/ingestion/graph_store.py`

SQLite persistence for the NetworkX graph (`data/nexus.db`):
- `save_graph(G, repo_path)` — persists nodes and edges
- `load_graph(repo_path)` → `nx.DiGraph` — reconstructs graph from SQLite
- `delete_nodes_for_files(file_paths, repo_path)` — removes nodes for incremental re-index
- `delete_graph_for_repo(repo_path)` — removes all data for a repo

### `app/ingestion/embedder.py`

Dual-storage embedding layer:
- `init_pgvector_table()` — creates `code_embeddings` table with `vector(1536)` and ivfflat index
- `embed_and_store(nodes, repo_path)` → `int` — batches nodes (100/batch), calls OpenAI `text-embedding-3-small`, upserts to pgvector via `ON CONFLICT DO UPDATE`, maintains FTS5 table for exact name search
- `delete_embeddings_for_repo(repo_path)` — removes all embeddings for a repo

### `app/ingestion/pipeline.py`

`run_ingestion(repo_path, languages, changed_files=None)` → `IndexStatus`

Orchestrates the full ingestion flow:
1. `walk_repo()` to get file list
2. `_parse_concurrent()` — fans out `parse_file()` via `asyncio.gather` + `Semaphore(10)`
3. `build_graph()` → PageRank-scored DiGraph
4. `save_graph()` → SQLite persistence
5. `embed_and_store()` → pgvector + FTS5

Status is stored in a module-level `_status` dict keyed by `repo_path`, accessible via `get_status(repo_path)`.

`changed_files` triggers incremental mode: deletes old graph nodes for those files, re-parses only changed files.

### `app/api/index_router.py`

FastAPI router with three endpoints:
- `POST /index` — starts ingestion as a `BackgroundTask`, returns `{"status": "pending"}` immediately
- `GET /index/status?repo_path=...` — returns `IndexStatus` or 404
- `DELETE /index?repo_path=...` — removes all pgvector, FTS5, and SQLite data for the repo

## Architecture

```
POST /index
    │
    └── BackgroundTasks.add_task(run_ingestion)
                │
                ├── walk_repo()           ← walker.py
                │
                ├── _parse_concurrent()   ← ast_parser.py (asyncio.gather, semaphore=10)
                │       └── parse_file()  ← returns (list[CodeNode], list[tuple edges])
                │
                ├── build_graph()         ← graph_builder.py
                │       └── nx.DiGraph with pagerank, in_degree, out_degree
                │
                ├── save_graph()          ← graph_store.py → data/nexus.db
                │
                └── embed_and_store()     ← embedder.py
                        ├── OpenAI text-embedding-3-small (100/batch)
                        ├── pgvector code_embeddings (upsert)
                        └── SQLite FTS5 code_fts (exact name search)
```

## Postgres connection

The `postgres` service is mapped to **host port 5433** (not 5432) to avoid conflicts with local Postgres instances.

Connect from host:
```bash
psql -h localhost -p 5433 -U $POSTGRES_USER -d $POSTGRES_DB
```

Connect from inside Docker network (backend container):
```
host: postgres, port: 5432
```
