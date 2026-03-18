---
phase: 05-embedder
plan: "02"
subsystem: embedder
tags: [openai, pgvector, fts5, sqlite, embeddings, upsert]
dependency_graph:
  requires:
    - backend/app/db/database.py
    - backend/app/models/schemas.py
    - backend/app/config.py
  provides:
    - backend/app/ingestion/embedder.py
  affects:
    - Phase 06 - Ingestion Pipeline (calls embed_and_store after build_graph)
    - Phase 08 - Graph RAG (uses pgvector cosine search and FTS5 exact-match)
tech_stack:
  added: [openai>=1.0.0]
  patterns:
    - lazy OpenAI client init inside function body (not module level)
    - pgvector ON CONFLICT (id) DO UPDATE upsert
    - FTS5 DELETE + INSERT upsert (no ON CONFLICT in FTS5)
    - register_vector(conn) per-connection (not global)
    - batch-100 embedding API calls
key_files:
  created:
    - backend/app/ingestion/embedder.py
  modified:
    - backend/requirements.txt
decisions:
  - Lazy OpenAI client init inside embed_and_store() body — prevents ValidationError on import when OPENAI_API_KEY absent; client = OpenAI(api_key=get_settings().openai_api_key) only called at function invocation time
  - FTS5 upsert via DELETE + INSERT per batch — FTS5 virtual tables have no ON CONFLICT support; always delete first then re-insert for idempotent behavior
  - register_vector(conn) called per-connection in both init_pgvector_table and embed_and_store — pgvector requires per-connection type registration; never global
  - conn.autocommit = True from get_db_connection() means no explicit commit needed for pgvector DDL operations
  - text-embedding-3-small model selected — matches EMBED-04 requirement; 1536-dimensional output matches vector(1536) column definition
metrics:
  duration_seconds: 163
  completed_date: "2026-03-18"
  tasks_completed: 2
  files_created: 1
  files_modified: 1
---

# Phase 05 Plan 02: Embedder Summary

**One-liner:** OpenAI text-embedding-3-small batch embedder with pgvector ON CONFLICT upsert and SQLite FTS5 DELETE+INSERT for exact-name lookup.

## What Was Built

`backend/app/ingestion/embedder.py` — the bridge between parsed code (Phase 3-4) and queryable storage (Phase 8 Graph RAG).

### Public API

**`init_pgvector_table() -> None`**
Creates `code_embeddings` table with `vector(1536)` primary column and `ivfflat` cosine index (lists=100) idempotently. Uses `conn.autocommit = True` from `get_db_connection()` — no explicit commit needed. Calls `register_vector(conn)` per-connection as required by pgvector.

**`embed_and_store(nodes: list[CodeNode], repo_path: str) -> int`**
Processes nodes in batches of 100 (EMBED_BATCH_SIZE). For each batch:
1. Calls OpenAI `text-embedding-3-small` API with `embedding_text` fields
2. Sorts response by index to preserve order
3. Upserts to pgvector via `execute_values` with `ON CONFLICT (id) DO UPDATE`
4. Upserts to SQLite FTS5 via `DELETE WHERE node_id = ? + INSERT`
Returns total node count stored.

### Internal Helpers

- `_sqlite_db_path() -> str` — returns `"data/nexus.db"` (same file as graph_store.py)
- `_init_fts_table(db_path: str) -> None` — creates `code_fts` FTS5 virtual table idempotently; `node_id UNINDEXED`, `name` searchable, `file_path UNINDEXED`

### Key Design: Lazy Client Init

OpenAI client initialized inside `embed_and_store()` body, not at module level:
```python
client = OpenAI(api_key=get_settings().openai_api_key)
```
This prevents `ValidationError` during test imports when `OPENAI_API_KEY` is absent.

## Test Results

- 47/47 existing project tests pass (no regressions)
  - 12 test_file_walker.py
  - 17 test_ast_parser.py
  - 18 test_graph_builder.py
- Import verification: `from app.ingestion.embedder import init_pgvector_table, embed_and_store, EMBED_BATCH_SIZE` prints `imports OK, batch size: 100` without OPENAI_API_KEY set

## Deviations from Plan

None — plan executed exactly as written.

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| Task 1 | c69d22c | chore(05-02): add openai>=1.0.0 to requirements.txt |
| Task 2 | 4053abb | feat(05-02): implement embedder.py with pgvector and FTS5 storage |

## Self-Check: PASSED

- FOUND: backend/app/ingestion/embedder.py
- FOUND: backend/requirements.txt (contains openai>=1.0.0)
- FOUND: commit c69d22c
- FOUND: commit 4053abb
