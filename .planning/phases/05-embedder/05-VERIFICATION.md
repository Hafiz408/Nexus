---
phase: 05-embedder
verified: 2026-03-18T13:00:00Z
status: passed
score: 12/12 must-haves verified
re_verification: false
---

# Phase 5: Embedder Verification Report

**Phase Goal:** CodeNode objects are embedded and stored so that semantic search and exact-name search are both available
**Verified:** 2026-03-18T13:00:00Z
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `save_graph(G, repo_path)` persists all nodes and edges to SQLite without error | VERIFIED | `graph_store.py` lines 52-109: DELETE + executemany INSERT, conn.commit(); test_save_and_load_graph_roundtrip PASSES |
| 2 | `load_graph(repo_path)` reconstructs a DiGraph with identical node attributes and edges | VERIFIED | `graph_store.py` lines 112-138: SELECT + G.add_node + G.add_edge with json.loads; roundtrip test asserts nodes, edges, and pagerank float |
| 3 | `delete_nodes_for_files(file_paths, repo_path)` removes only the nodes whose file_path matches, plus their incident edges | VERIFIED | `graph_store.py` lines 141-189: SELECT affected node_ids, DELETE edges by node_id, DELETE nodes by file_path; test_delete_nodes_for_files_removes_nodes_and_edges PASSES and verifies unrelated node survives |
| 4 | SQLite path is derived from a single `data/nexus.db` file with repo_path column scoping | VERIFIED | `_DB_FILE = "data/nexus.db"` at line 15; `_db_path()` returns it; PRIMARY KEY (node_id, repo_path) enforces isolation |
| 5 | `init_pgvector_table()` creates `code_embeddings` table with `vector(1536)` and ivfflat index idempotently | VERIFIED | `embedder.py` lines 20-48: CREATE TABLE IF NOT EXISTS with vector(1536); CREATE INDEX IF NOT EXISTS using ivfflat vector_cosine_ops lists=100 |
| 6 | `embed_and_store()` batches nodes into groups of 100, calls OpenAI, upserts to pgvector and FTS5, returns count | VERIFIED | `embedder.py` lines 74-163: EMBED_BATCH_SIZE=100, client.embeddings.create(), execute_values ON CONFLICT DO UPDATE, FTS5 DELETE+INSERT, return total_stored |
| 7 | Re-running `embed_and_store()` on same nodes upserts without duplicate FTS5 rows | VERIFIED | test_embed_and_store_upsert_no_duplicates calls embed_and_store twice and asserts COUNT(*) == len(sample_nodes) — PASSES |
| 8 | SQLite FTS5 `code_fts` table supports exact name MATCH queries | VERIFIED | `_init_fts_table()` creates `code_fts USING fts5(node_id UNINDEXED, name, file_path UNINDEXED)` without content=''; test_fts5_table_supports_name_match uses `WHERE name MATCH '"func_0"'` and asserts 1 row — PASSES |
| 9 | test_embedder.py verifies save_graph → load_graph round-trip | VERIFIED | 6 graph_store tests cover round-trip, empty load, overwrite deduplication, file-based delete, noop on empty list, repo isolation; all PASS |
| 10 | embed_and_store tests mock the OpenAI client so no real API call is made during testing | VERIFIED | All 4 embedder tests patch `app.ingestion.embedder.OpenAI`, `app.ingestion.embedder.register_vector`, `app.ingestion.embedder.execute_values` at correct module namespace |
| 11 | `init_pgvector_table()` is wired into `main.py` lifespan so the table is created on app startup | VERIFIED | `main.py` line 6: `from app.ingestion.embedder import init_pgvector_table`; line 12: `init_pgvector_table()` called inside lifespan after `init_db()` |
| 12 | All 47 existing tests plus new Phase 5 tests pass | VERIFIED | `pytest backend/tests/ -q` reports 57 passed (47 prior + 10 new), 0 failures |

**Score:** 12/12 truths verified

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/app/ingestion/graph_store.py` | `save_graph`, `load_graph`, `delete_nodes_for_files` | VERIFIED | 190 lines; all three functions substantive and tested |
| `backend/app/ingestion/embedder.py` | `init_pgvector_table`, `embed_and_store` | VERIFIED | 164 lines; EMBED_BATCH_SIZE=100 constant; lazy OpenAI init confirmed |
| `backend/requirements.txt` | `openai>=1.0.0` dependency | VERIFIED | Line 14: `openai>=1.0.0` present |
| `backend/tests/test_embedder.py` | Full test coverage, min 60 lines | VERIFIED | 250 lines; 10 test functions; 6 graph_store + 4 embedder tests |
| `backend/app/main.py` | `init_pgvector_table` called in lifespan | VERIFIED | 22 lines; import on line 6; call on line 12 inside lifespan after init_db() |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `graph_store.py:save_graph` | `graph_nodes` table | `executemany` INSERT OR REPLACE | WIRED | Lines 86-90: `conn.executemany("INSERT OR REPLACE INTO graph_nodes ...")` |
| `graph_store.py:load_graph` | `nx.DiGraph` | `json.loads` on `attrs_json` column | WIRED | Lines 125-135: `G.add_node(row["node_id"], **json.loads(row["attrs_json"]))` |
| `graph_store.py:delete_nodes_for_files` | `graph_nodes WHERE file_path IN` | parameterized DELETE query | WIRED | Lines 182-186: `DELETE FROM graph_nodes WHERE repo_path = ? AND file_path IN (...)` |
| `embedder.py:embed_and_store` | `openai client.embeddings.create()` | lazy init inside function body | WIRED | Lines 96, 113-116: client initialized at function call time, `client.embeddings.create(model="text-embedding-3-small", input=texts)` |
| `embedder.py:embed_and_store` | `code_embeddings` table via `execute_values` | `ON CONFLICT (id) DO UPDATE` | WIRED | Lines 128-144: `execute_values(cur, "INSERT INTO code_embeddings ... ON CONFLICT (id) DO UPDATE SET ...")` |
| `embedder.py:embed_and_store` | `code_fts` FTS5 table via `sqlite3` | DELETE + INSERT per batch | WIRED | Lines 147-155: `executemany("DELETE FROM code_fts WHERE node_id = ?", ...)` then `executemany("INSERT INTO code_fts ...")` |
| `test_embedder.py` | `embed_and_store` | `patch("app.ingestion.embedder.OpenAI")` | WIRED | Lines 199, 216, 237: correct module-namespace patch targets used |
| `main.py lifespan` | `init_pgvector_table()` | direct function call before yield | WIRED | Lines 11-13: `init_db()` then `init_pgvector_table()` then `yield` |

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| EMBED-01 | 05-02, 05-03 | `embed_and_store(nodes, repo_path)` embeds all nodes and upserts into pgvector | SATISFIED | `embedder.py:embed_and_store` calls OpenAI and execute_values upsert; test_embed_and_store_returns_count PASSES |
| EMBED-02 | 05-02, 05-03 | Creates `code_embeddings` table with vector(1536) and ivfflat index on startup | SATISFIED | `init_pgvector_table()` uses CREATE TABLE IF NOT EXISTS + CREATE INDEX IF NOT EXISTS; wired to lifespan |
| EMBED-03 | 05-02, 05-03 | Creates SQLite FTS5 `code_fts` virtual table for exact name search | SATISFIED | `_init_fts_table()` creates FTS5 table without content=''; test_fts5_table_supports_name_match PASSES |
| EMBED-04 | 05-02, 05-03 | Embeds in batches of 100 using `openai.embeddings.create()` | SATISFIED | `EMBED_BATCH_SIZE = 100`; `for i in range(0, len(nodes), EMBED_BATCH_SIZE)`; test_embed_batch_size_constant PASSES |
| EMBED-05 | 05-02, 05-03 | Upsert logic: `INSERT ... ON CONFLICT (id) DO UPDATE` — safe for incremental re-index | SATISFIED | Lines 131-144 of embedder.py; test_embed_and_store_upsert_no_duplicates verifies no FTS5 duplicates on second call |
| EMBED-06 | 05-02, 05-03 | Returns count of nodes stored | SATISFIED | `return total_stored` at line 163; test_embed_and_store_returns_count asserts `count == len(sample_nodes)` |
| STORE-01 | 05-01, 05-03 | `save_graph(G, repo_path)` persists NetworkX graph to SQLite | SATISFIED | `graph_store.py:save_graph` persists nodes+edges; test_save_and_load_graph_roundtrip PASSES |
| STORE-02 | 05-01, 05-03 | `load_graph(repo_path)` reconstructs NetworkX DiGraph from SQLite | SATISFIED | `graph_store.py:load_graph` rebuilds DiGraph; round-trip test validates node attrs and edges |
| STORE-03 | 05-01, 05-03 | `delete_nodes_for_files(file_paths, repo_path)` removes nodes for incremental re-index | SATISFIED | `graph_store.py:delete_nodes_for_files`; test_delete_nodes_for_files_removes_nodes_and_edges verifies node + incident edge removal; test_delete_nodes_for_files_empty_list_is_noop verifies no-op edge case |

All 9 phase requirements (EMBED-01 through EMBED-06, STORE-01 through STORE-03) are SATISFIED. No orphaned requirements found — all 9 IDs declared across the three plans are accounted for and map to REQUIREMENTS.md Phase 5 entries marked Complete.

---

## Anti-Patterns Found

None. No TODO/FIXME/placeholder comments, no empty return stubs, no console-log-only implementations found in any phase 5 file.

Note: grep hits on "placeholders" in `graph_store.py` are legitimate SQL parameterization variables, not stub markers.

---

## Human Verification Required

### 1. Live pgvector Integration

**Test:** With Docker running (`docker compose up -d`), call `init_pgvector_table()` then `embed_and_store()` with a real OpenAI API key and verify rows appear in the `code_embeddings` table via `psql`.
**Expected:** `code_embeddings` table exists, ivfflat index present, rows upserted without error on second call.
**Why human:** Requires live Postgres+pgvector container and valid OPENAI_API_KEY; cannot be verified without external services.

### 2. App Startup Lifespan Execution

**Test:** Start the FastAPI app with Docker running (`uvicorn app.main:app`), confirm startup logs show no errors from `init_pgvector_table()`.
**Expected:** App starts cleanly; `code_embeddings` table created (or IF NOT EXISTS no-op).
**Why human:** Requires live Postgres container; automated import-only checks cannot exercise the async lifespan.

---

## Commits Verified

All documented commits exist in git history:

| Commit | Description |
|--------|-------------|
| `f90337f` | feat(05-01): implement graph_store.py with save_graph, load_graph, delete_nodes_for_files |
| `c69d22c` | chore(05-02): add openai>=1.0.0 to requirements.txt |
| `4053abb` | feat(05-02): implement embedder.py with pgvector and FTS5 storage |
| `a102d25` | feat(05-03): add test_embedder.py covering graph_store and embedder |
| `1185c16` | feat(05-03): wire init_pgvector_table into FastAPI lifespan |

---

## Summary

Phase 5 goal is fully achieved. All artifacts exist, are substantive (no stubs), and are correctly wired. The two key bug-fixes made during plan 03 execution — removing `content=''` from the FTS5 table definition and correcting mock patch targets to the embedder module namespace — are present in the committed code and verified by passing tests. All 57 tests pass (47 prior + 10 new Phase 5 tests). All 9 requirement IDs declared in plan frontmatter are satisfied. Two items require human verification with live external services (Postgres/pgvector and OpenAI API key) but these do not block goal achievement for the automated portion of the phase.

---

_Verified: 2026-03-18T13:00:00Z_
_Verifier: Claude (gsd-verifier)_
