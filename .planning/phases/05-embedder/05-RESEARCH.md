# Phase 5: Embedder - Research

**Researched:** 2026-03-18
**Domain:** OpenAI Embeddings + pgvector + SQLite FTS5 + NetworkX SQLite persistence
**Confidence:** HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| EMBED-01 | `embed_and_store(nodes, repo_path)` embeds all nodes and upserts into pgvector | OpenAI Python client `embeddings.create()` + psycopg2 `execute_values` upsert pattern |
| EMBED-02 | Creates `code_embeddings` table with `vector(1536)` and ivfflat index on startup | pgvector SQL DDL: `CREATE TABLE ... vector(1536)` + `CREATE INDEX USING ivfflat ... vector_cosine_ops` |
| EMBED-03 | Creates SQLite FTS5 `code_fts` virtual table for exact name search | `CREATE VIRTUAL TABLE code_fts USING fts5(...)` via `sqlite3` / `aiosqlite` |
| EMBED-04 | Embeds in batches of 100 using `openai.embeddings.create()` | Input accepts list of strings; batch of 100 well within 2048-item array limit |
| EMBED-05 | Upsert logic: `INSERT ... ON CONFLICT (id) DO UPDATE` — safe for incremental re-index | Standard pgvector upsert SQL pattern verified from official pgvector docs |
| EMBED-06 | Returns count of nodes stored | Trivial — len() of processed batch list |
| STORE-01 | `save_graph(G, repo_path)` persists NetworkX graph to SQLite (`graph_nodes` + `graph_edges` tables) | Manual table approach using `sqlite3` / `aiosqlite` with JSON-serialized node attributes |
| STORE-02 | `load_graph(repo_path)` reconstructs NetworkX DiGraph from SQLite on startup | SELECT all rows, re-add nodes/edges with `json.loads()` for attributes |
| STORE-03 | `delete_nodes_for_files(file_paths, repo_path)` removes nodes for incremental re-index | DELETE WHERE file_path IN (...) on `graph_nodes`; cascade via ON DELETE logic on `graph_edges` |
</phase_requirements>

---

## Summary

Phase 5 introduces three distinct storage backends in a single `embedder.py` module: (1) pgvector for dense vector similarity search, (2) SQLite FTS5 for exact/prefix name search, and (3) SQLite relational tables for NetworkX graph persistence. The OpenAI `text-embedding-3-small` model is specified by dimension (`vector(1536)`) which matches the requirement; the Python `openai` client already exists in the stack indirectly and must be added explicitly to `requirements.txt`.

The pgvector integration uses the existing `psycopg2-binary` + `pgvector` packages already in `requirements.txt`. Upsert is straightforward: `INSERT ... ON CONFLICT (id) DO UPDATE SET`. The IVFFlat index should use `vector_cosine_ops` (cosine similarity is standard for embedding search) and is best created after data is loaded — but the requirement says "on startup", so the correct pattern is `CREATE INDEX IF NOT EXISTS` which is a no-op if the index already exists (and PostgreSQL will silently skip creation on an empty table, though ivfflat requires data for optimal k-means clustering; `CREATE INDEX IF NOT EXISTS` without data works but produces a degenerate index — acceptable for V1 since data is loaded immediately after).

For graph persistence, no third-party library is needed. The idiomatic approach is two SQLite tables (`graph_nodes`, `graph_edges`) with node attributes JSON-serialized. The `aiosqlite` package is already in `requirements.txt` for async I/O. For synchronous paths called from non-async contexts (e.g., during startup), the standard `sqlite3` module is sufficient and avoids event loop complexity.

**Primary recommendation:** Implement `embedder.py` with three sections: `init_pgvector_table()`, `init_fts_table()`, `embed_and_store()` (embedding + pgvector upsert + FTS upsert), and `graph_store.py` (or a `store_graph.py`) with `save_graph()`, `load_graph()`, `delete_nodes_for_files()`. Keep pgvector calls synchronous (psycopg2) and SQLite calls either sync (sqlite3) or async (aiosqlite) consistently — do not mix within one function.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `openai` | `>=1.0.0` | OpenAI Python client for embeddings | Official SDK; `openai.embeddings.create()` is the required API per EMBED-04 |
| `pgvector` | already installed | psycopg2 vector type adapter | Already in requirements.txt; `register_vector(conn)` needed before vector inserts |
| `psycopg2-binary` | already installed | PostgreSQL connection | Already in requirements.txt; synchronous, simple |
| `sqlite3` | stdlib | SQLite access for graph + FTS5 | No install needed; stdlib module in Python 3.11 |
| `aiosqlite` | already installed | Async SQLite for pipeline compatibility | Already in requirements.txt; used when called from async context |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `psycopg2.extras.execute_values` | stdlib of psycopg2 | Batch INSERT for pgvector | Use for batch-of-100 upsert to avoid N individual execute() calls |
| `numpy` | already installed | Convert list → numpy array for pgvector | pgvector-python prefers numpy arrays for vector values |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `sqlite3` for graph store | `aiosqlite` throughout | aiosqlite has async overhead not needed for graph store if called synchronously; use sqlite3 for save/load, aiosqlite only if called from async pipeline |
| `psycopg2` synchronous | `asyncpg` + pgvector async | asyncpg requires different driver; not in stack; not worth the change for V1 |
| ivfflat index | HNSW index | HNSW is generally faster for recall but requirement explicitly specifies ivfflat — do not swap |

**Installation (additions needed):**
```bash
pip install openai>=1.0.0
```
Add to `requirements.txt`: `openai>=1.0.0`

---

## Architecture Patterns

### Recommended Project Structure
```
backend/app/ingestion/
├── walker.py          # Phase 2 — already exists
├── ast_parser.py      # Phase 3 — already exists
├── graph_builder.py   # Phase 4 — already exists
├── embedder.py        # Phase 5 — NEW: embed_and_store() + table init
└── graph_store.py     # Phase 5 — NEW: save_graph(), load_graph(), delete_nodes_for_files()
```

Both `embedder.py` and `graph_store.py` are new modules under `app/ingestion/`. The SQLite file path should be derived from `repo_path` as `data/{repo_slug}.db` to match the Phase 1 data-persistence pattern.

### Pattern 1: pgvector Table Initialization (Idempotent)

**What:** CREATE TABLE and CREATE INDEX with IF NOT EXISTS guards, called at startup
**When to use:** In `embedder.py` module-level init function, called from `lifespan` in `main.py`

```python
# Source: pgvector/pgvector-python GitHub README + pgvector/pgvector GitHub README
from pgvector.psycopg2 import register_vector
import psycopg2

def init_pgvector_table(conn) -> None:
    register_vector(conn)
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS code_embeddings (
                id         TEXT PRIMARY KEY,       -- node_id ("rel_path::name")
                repo_path  TEXT NOT NULL,
                name       TEXT NOT NULL,
                file_path  TEXT NOT NULL,
                line_start INT,
                line_end   INT,
                embedding  vector(1536)
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS code_embeddings_embedding_idx
            ON code_embeddings
            USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100)
        """)
```

**Note on ivfflat + empty table:** pgvector allows `CREATE INDEX` on an empty table; k-means clustering trains on existing data, so an index created before any rows yields a degenerate (but functional) index. For V1 this is acceptable — the index is recreated with data on the first real ingestion run.

### Pattern 2: Batch Embedding with OpenAI

**What:** Split nodes into chunks of 100, call `openai.embeddings.create()` with list of texts
**When to use:** Inside `embed_and_store()`, the main entry point

```python
# Source: OpenAI API Reference - https://platform.openai.com/docs/api-reference/embeddings/create
from openai import OpenAI

client = OpenAI(api_key=settings.openai_api_key)

def _embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed up to 100 texts in a single API call."""
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=texts,
    )
    # response.data is a list of Embedding objects, sorted by index
    return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]
```

**Key API facts (HIGH confidence, verified from OpenAI docs):**
- `input` accepts a `str` or `list[str]` (or token arrays)
- Max array length: 2048 items
- Max tokens per input: 8192
- Default dimensions for `text-embedding-3-small`: 1536
- Returns: `CreateEmbeddingResponse` with `.data: list[Embedding]`, each has `.embedding: list[float]` and `.index: int`

### Pattern 3: pgvector Upsert with execute_values

**What:** Batch INSERT with ON CONFLICT DO UPDATE using psycopg2.extras.execute_values
**When to use:** After getting embedding vectors for a batch

```python
# Source: pgvector/pgvector-python README + psycopg2 docs
from psycopg2.extras import execute_values
import numpy as np

def _upsert_embeddings(conn, rows: list[tuple]) -> None:
    """
    rows: list of (id, repo_path, name, file_path, line_start, line_end, embedding_list)
    """
    with conn.cursor() as cur:
        execute_values(cur, """
            INSERT INTO code_embeddings
                (id, repo_path, name, file_path, line_start, line_end, embedding)
            VALUES %s
            ON CONFLICT (id) DO UPDATE SET
                repo_path  = EXCLUDED.repo_path,
                name       = EXCLUDED.name,
                file_path  = EXCLUDED.file_path,
                line_start = EXCLUDED.line_start,
                line_end   = EXCLUDED.line_end,
                embedding  = EXCLUDED.embedding
        """, rows)
```

**Note:** pgvector-python automatically handles `list[float]` → `vector` conversion once `register_vector(conn)` has been called. Numpy arrays also work.

### Pattern 4: SQLite FTS5 Table for Exact Name Search

**What:** CREATE VIRTUAL TABLE with FTS5, insert node names/ids, query with MATCH
**When to use:** In `embedder.py` init function + inside `embed_and_store()` for FTS upsert

```python
# Source: https://www.sqlite.org/fts5.html
import sqlite3

def init_fts_table(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS code_fts
        USING fts5(
            node_id UNINDEXED,
            name,
            file_path UNINDEXED,
            content=''
        )
    """)
    conn.commit()
    conn.close()
```

**FTS5 upsert pattern:** FTS5 virtual tables do not support `ON CONFLICT`. The correct approach is DELETE then INSERT:

```python
def _upsert_fts(conn: sqlite3.Connection, nodes: list) -> None:
    """FTS5 has no ON CONFLICT — delete existing rowids then re-insert."""
    for node in nodes:
        conn.execute(
            "DELETE FROM code_fts WHERE node_id = ?",
            (node.node_id,)
        )
    conn.executemany(
        "INSERT INTO code_fts(node_id, name, file_path) VALUES (?, ?, ?)",
        [(n.node_id, n.name, n.file_path) for n in nodes]
    )
    conn.commit()
```

**Querying FTS5 for exact name:**
```python
# Source: https://www.sqlite.org/fts5.html
# Phrase query with double-quotes forces exact token match
rows = conn.execute(
    'SELECT node_id FROM code_fts WHERE name MATCH ?',
    (f'"{name}"',)
).fetchall()
```

### Pattern 5: NetworkX Graph Persistence to SQLite

**What:** Two SQLite tables — `graph_nodes` (id + JSON attrs) and `graph_edges` (source + target + JSON attrs)
**When to use:** `save_graph()` / `load_graph()` in `graph_store.py`

```python
# Source: NetworkX docs (node_link_data pattern) adapted for SQLite tables
import json
import sqlite3
import networkx as nx

GRAPH_DB_PATH = "data/graph.db"  # or keyed by repo_path

def _get_graph_conn(repo_path: str) -> sqlite3.Connection:
    db_path = _graph_db_path(repo_path)
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS graph_nodes (
            node_id    TEXT PRIMARY KEY,
            attrs_json TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS graph_edges (
            source     TEXT NOT NULL,
            target     TEXT NOT NULL,
            attrs_json TEXT NOT NULL,
            PRIMARY KEY (source, target)
        )
    """)
    conn.commit()
    return conn

def save_graph(G: nx.DiGraph, repo_path: str) -> None:
    conn = _get_graph_conn(repo_path)
    # Clear and re-insert (full overwrite — simpler than diff for V1)
    conn.execute("DELETE FROM graph_nodes")
    conn.execute("DELETE FROM graph_edges")
    conn.executemany(
        "INSERT INTO graph_nodes (node_id, attrs_json) VALUES (?, ?)",
        [(n, json.dumps(attrs)) for n, attrs in G.nodes(data=True)]
    )
    conn.executemany(
        "INSERT INTO graph_edges (source, target, attrs_json) VALUES (?, ?, ?)",
        [(u, v, json.dumps(attrs)) for u, v, attrs in G.edges(data=True)]
    )
    conn.commit()
    conn.close()

def load_graph(repo_path: str) -> nx.DiGraph:
    conn = _get_graph_conn(repo_path)
    G = nx.DiGraph()
    for row in conn.execute("SELECT node_id, attrs_json FROM graph_nodes"):
        G.add_node(row[0], **json.loads(row[1]))
    for row in conn.execute("SELECT source, target, attrs_json FROM graph_edges"):
        G.add_edge(row[0], row[1], **json.loads(row[2]))
    conn.close()
    return G
```

**Serialization note:** Node attributes include `pagerank` (float), `in_degree` (int), `out_degree` (int), and the full `CodeNode` fields stored as individual attributes. `json.dumps` handles all of these. If `CodeNode` objects are stored as values (not primitive fields), use `node.model_dump()` before storing.

### Pattern 6: delete_nodes_for_files (STORE-03)

```python
def delete_nodes_for_files(file_paths: list[str], repo_path: str) -> None:
    conn = _get_graph_conn(repo_path)
    # Node IDs contain file path as prefix: "rel/path/file.py::name"
    # Also delete edges involving those nodes
    placeholders = ",".join("?" * len(file_paths))
    # Get node_ids to delete
    node_ids = [
        row[0] for row in conn.execute(
            f"SELECT node_id FROM graph_nodes WHERE attrs_json LIKE ?",
            # Better: store file_path as a column for efficient deletion
        )
    ]
```

**Important:** Storing `file_path` as a separate column in `graph_nodes` (in addition to `attrs_json`) enables efficient `WHERE file_path IN (...)` deletion without JSON parsing. Recommended table schema:

```sql
CREATE TABLE IF NOT EXISTS graph_nodes (
    node_id   TEXT PRIMARY KEY,
    file_path TEXT NOT NULL,     -- for fast deletion by file
    attrs_json TEXT NOT NULL
)
```

### Anti-Patterns to Avoid

- **Creating ivfflat index before any data exists:** Technically works but wastes a DDL operation and produces a poor index. Use `CREATE INDEX IF NOT EXISTS` which is idempotent — the requirement says "on startup" which means the guard is sufficient.
- **Using FTS5 `ON CONFLICT`:** FTS5 virtual tables don't support it. Use DELETE + INSERT.
- **Using `nx.node_link_data()` for SQLite storage:** This returns a JSON blob — fine for file-based persistence but loses the ability to do efficient `DELETE WHERE file_path = ?` for STORE-03. Use explicit tables.
- **Mixing async and sync psycopg2:** psycopg2 is synchronous only. Do not `await` psycopg2 calls. If called from async context, use `asyncio.to_thread()`.
- **Calling `register_vector(conn)` once globally:** `register_vector` must be called per-connection, not per-application. Call it immediately after getting a connection.
- **Storing raw `numpy.ndarray` in `attrs_json`:** `json.dumps` will fail on numpy types. Convert to `float(x)` or call `node.model_dump()` (pydantic) which returns plain Python types.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Vector type serialization | Custom `list → bytea` encoding | `pgvector-python` `register_vector(conn)` | Handles all psycopg2 ↔ postgres vector type adaptation |
| Embedding batching logic | Custom rate-limit + retry loop | OpenAI SDK built-in retry + batch input | SDK handles retries; batch of 100 is within API limits |
| Full-text search index | Custom inverted index in Python | SQLite FTS5 (stdlib via sqlite3) | FTS5 is built into Python's sqlite3; handles tokenization, ranking |
| Graph serialization format | Custom binary format | JSON + two SQLite tables | Simple, debuggable, reconstructable; no external deps |

**Key insight:** All required persistence mechanisms have either stdlib (sqlite3/FTS5) or already-installed (pgvector, psycopg2) solutions. No new complex libraries needed beyond adding `openai` to requirements.

---

## Common Pitfalls

### Pitfall 1: ivfflat Index on Empty Table

**What goes wrong:** `CREATE INDEX USING ivfflat` on an empty table creates a degenerate index (k-means with 0 rows). The index remains but may warn in pgvector logs. Queries still work (fall back to sequential scan) but ANN recall is undefined.
**Why it happens:** `init_pgvector_table()` is called at app startup before any nodes are embedded.
**How to avoid:** Use `CREATE INDEX IF NOT EXISTS` — it is idempotent. For V1, this is acceptable. In production, build the index after bulk load.
**Warning signs:** pgvector log warning: "ivfflat index created with 0 rows".

### Pitfall 2: register_vector Not Called Per Connection

**What goes wrong:** `psycopg2.extras.execute_values` raises `ProgrammingError: can't adapt type 'list'` when inserting vector columns.
**Why it happens:** pgvector type adapter must be registered on each connection object. It is not global.
**How to avoid:** Always call `register_vector(conn)` immediately after `psycopg2.connect(...)`.
**Warning signs:** `ProgrammingError` on INSERT with vector value.

### Pitfall 3: FTS5 Content Mismatch on Re-index

**What goes wrong:** Re-running `embed_and_store()` inserts duplicate FTS5 rows because FTS5 has no `ON CONFLICT`.
**Why it happens:** FTS5 virtual tables are not standard relational tables — they don't support UNIQUE constraints or `ON CONFLICT`.
**How to avoid:** Always DELETE existing rows by `node_id` before INSERT. Since `node_id` is in an UNINDEXED column, this requires a full-table scan on large datasets — acceptable for V1.
**Warning signs:** `SELECT COUNT(*) FROM code_fts` grows unboundedly on re-index.

### Pitfall 4: JSON Serialization of CodeNode Attributes

**What goes wrong:** `json.dumps(attrs)` fails with `TypeError: Object of type CodeNode is not JSON serializable`.
**Why it happens:** NetworkX stores whatever you add as node attributes. If you stored a `CodeNode` Pydantic model object directly, `json.dumps` can't serialize it.
**How to avoid:** When building the graph (Phase 4), ensure node attributes are stored as plain dicts/primitives, or call `node.model_dump()` before `json.dumps`.
**Warning signs:** `TypeError` in `save_graph()`.

### Pitfall 5: OpenAI Client Initialization at Module Level

**What goes wrong:** `openai.OpenAI(api_key=settings.openai_api_key)` at module level fails if `.env` is not loaded yet (e.g., during import in tests).
**Why it happens:** `get_settings()` calls `Settings()` which reads `.env`; if `OPENAI_API_KEY` is missing, pydantic raises `ValidationError`.
**How to avoid:** Initialize `OpenAI()` client lazily (inside the function body or with `lru_cache`) rather than at module import time. For testing, mock the client.
**Warning signs:** `ValidationError` on module import in test suite.

### Pitfall 6: SQLite Path Collision Across Repos

**What goes wrong:** Two different `repo_path` values resolve to the same SQLite file.
**Why it happens:** If using a hardcoded `data/graph.db`, all repos share the same file.
**How to avoid:** Derive a safe filename from `repo_path`:
```python
import hashlib
def _graph_db_path(repo_path: str) -> str:
    slug = hashlib.md5(repo_path.encode()).hexdigest()[:8]
    return f"data/graph_{slug}.db"
```
Or use a single SQLite file with `repo_path` as a partition column (simpler for V1).
**Warning signs:** `load_graph()` returns nodes from a different repo.

---

## Code Examples

### Full embed_and_store() Skeleton

```python
# embedder.py
import math
from openai import OpenAI
from psycopg2.extras import execute_values
from pgvector.psycopg2 import register_vector

from app.config import get_settings
from app.db.database import get_db_connection
from app.models.schemas import CodeNode

EMBED_BATCH_SIZE = 100
EMBED_MODEL = "text-embedding-3-small"


def embed_and_store(nodes: list[CodeNode], repo_path: str) -> int:
    """Embed nodes and upsert into pgvector + FTS5. Returns count stored."""
    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)
    conn = get_db_connection()
    register_vector(conn)

    db_path = _sqlite_db_path(repo_path)
    _init_fts_table(db_path)

    total_stored = 0
    for i in range(0, len(nodes), EMBED_BATCH_SIZE):
        batch = nodes[i : i + EMBED_BATCH_SIZE]
        texts = [n.embedding_text for n in batch]

        response = client.embeddings.create(model=EMBED_MODEL, input=texts)
        embeddings = [item.embedding for item in sorted(response.data, key=lambda x: x.index)]

        rows = [
            (n.node_id, repo_path, n.name, n.file_path, n.line_start, n.line_end, emb)
            for n, emb in zip(batch, embeddings)
        ]
        with conn.cursor() as cur:
            execute_values(cur, """
                INSERT INTO code_embeddings
                    (id, repo_path, name, file_path, line_start, line_end, embedding)
                VALUES %s
                ON CONFLICT (id) DO UPDATE SET
                    repo_path  = EXCLUDED.repo_path,
                    name       = EXCLUDED.name,
                    file_path  = EXCLUDED.file_path,
                    line_start = EXCLUDED.line_start,
                    line_end   = EXCLUDED.line_end,
                    embedding  = EXCLUDED.embedding
            """, rows)

        _upsert_fts(db_path, batch)
        total_stored += len(batch)

    conn.close()
    return total_stored
```

### init_pgvector_table() Called at App Startup

```python
# In embedder.py — called from main.py lifespan
def init_pgvector_table() -> None:
    conn = get_db_connection()
    register_vector(conn)
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS code_embeddings (
                id         TEXT PRIMARY KEY,
                repo_path  TEXT NOT NULL,
                name       TEXT NOT NULL,
                file_path  TEXT NOT NULL,
                line_start INT,
                line_end   INT,
                embedding  vector(1536)
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_code_embeddings_ivfflat
            ON code_embeddings
            USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100)
        """)
    conn.close()
```

### FTS5 Query Example (used by Phase 8 RAG)

```python
import sqlite3

def fts_search(name: str, repo_path: str) -> list[str]:
    """Return node_ids matching exact name token via FTS5."""
    conn = sqlite3.connect(_sqlite_db_path(repo_path))
    rows = conn.execute(
        'SELECT node_id FROM code_fts WHERE name MATCH ?',
        (f'"{name}"',)  # Double-quotes = exact phrase in FTS5 query syntax
    ).fetchall()
    conn.close()
    return [row[0] for row in rows]
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `openai.Embedding.create()` (v0.x API) | `client.embeddings.create()` (v1.x) | openai-python v1.0.0 (Nov 2023) | Old API raises `AttributeError`; must use v1+ client |
| `text-embedding-ada-002` (1536 dims) | `text-embedding-3-small` (1536 dims) | Jan 2024 | 3-small is cheaper and more capable; both use 1536 dims so no schema change needed |
| `acreate()` async method (v0.x) | `AsyncOpenAI().embeddings.create()` | openai-python v1.0.0 | Use `AsyncOpenAI` class for async; requirement EMBED-04 specifies sync `openai.embeddings.create()` so use sync `OpenAI` client |

**Deprecated/outdated:**
- `openai.Embedding.create(engine="text-embedding-ada-002", ...)` — v0.x API, completely removed in v1.0
- `from pgvector.psycopg2 import register_vector` as a one-time global call — must be per-connection

---

## Open Questions

1. **Single SQLite file vs. per-repo SQLite files**
   - What we know: STORE-01/02/03 reference `repo_path` as a parameter, implying isolation per repo
   - What's unclear: Whether to use one file with a `repo_path` column or separate files per repo
   - Recommendation: Use a single `data/nexus.db` with a `repo_path` TEXT column in all tables — simpler, easier to inspect, and Phase 6's `delete_nodes_for_files` just adds `WHERE repo_path = ?`

2. **Whether `graph_store.py` is a separate file or combined with `embedder.py`**
   - What we know: Requirements list EMBED-* and STORE-* separately; Phase 6 pipeline calls both
   - What's unclear: Organizational preference
   - Recommendation: Keep as two separate files — `embedder.py` for pgvector/FTS5, `graph_store.py` for NetworkX persistence — clean separation of concerns

3. **openai package version constraint**
   - What we know: `openai>=1.0.0` is the v1 client API (required since old API is removed)
   - What's unclear: Whether any tree-sitter or other pinned dep conflicts with recent openai versions
   - Recommendation: Add `openai>=1.0.0` to requirements.txt; test with `pip install -r requirements.txt` in Docker

---

## Sources

### Primary (HIGH confidence)
- `https://github.com/pgvector/pgvector-python` — psycopg2 registration, vector type, upsert patterns
- `https://github.com/pgvector/pgvector` — CREATE TABLE syntax, ivfflat index, ON CONFLICT recommendation
- `https://www.sqlite.org/fts5.html` — FTS5 CREATE VIRTUAL TABLE, MATCH syntax, rowid, UNINDEXED columns
- `https://networkx.org/documentation/stable/reference/readwrite/json_graph.html` — node_link_data API
- OpenAI API Reference (embeddings/create) — model name, dimensions, input array format, response structure

### Secondary (MEDIUM confidence)
- `https://platform.openai.com/docs/guides/embeddings` — text-embedding-3-small default 1536 dims
- pgvector ivfflat documentation (multiple sources: Supabase, AWS) — `lists = rows/1000` guidance, create-after-data recommendation
- OpenAI community docs — max array length 2048, max tokens 8192 per input

### Tertiary (LOW confidence)
- Medium/community posts on async OpenAI embeddings — pattern verified against official SDK docs

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — pgvector, openai SDK, sqlite3/FTS5 all verified from official sources
- Architecture: HIGH — patterns derived directly from official pgvector and SQLite FTS5 docs
- Pitfalls: HIGH — register_vector and FTS5 no-ON-CONFLICT verified from official sources; others from direct analysis of project codebase context

**Research date:** 2026-03-18
**Valid until:** 2026-04-17 (30 days — stable libraries)
