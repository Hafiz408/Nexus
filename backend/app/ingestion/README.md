# Ingestion Pipeline

The ingestion pipeline transforms raw source code into a queryable, graph-aware knowledge base. It parses Python and TypeScript files, extracts code structure (functions, classes, methods), embeds them semantically, and stores them in dual indexes (vector store + graph store).

## High-Level Flow

```
POST /index request
    ↓
run_ingestion() orchestrator
    ├─ walker.py: discover files (respect .gitignore)
    ├─ ast_parser.py: concurrent tree-sitter parsing
    │  └─ emit CodeNode(signature, docstring, body_preview, complexity)
    │  └─ emit raw edges (unresolved source_id, target_name, edge_type)
    ├─ graph_builder.py: resolve edges, build DiGraph, compute metrics
    │  └─ PageRank, in_degree, out_degree per node
    ├─ graph_store.py: persist DiGraph to SQLite
    │  └─ graph_nodes (node_id, repo_path, file_path, attrs_json)
    │  └─ graph_edges (source, target, repo_path, attrs_json)
    ├─ embedder.py: batch embed + store
    │  ├─ pgvector (dense vectors for semantic search)
    │  └─ FTS5 (name index for exact-match lookup)
    └─ return IndexStatus(status="complete", nodes_indexed, edges_indexed, files_processed)
```

## Incremental Re-Indexing

When files change (detected by the FileWatcher in the extension), the pipeline re-indexes only those files:

```
changed_files = ["/path/to/modified.py", ...]
    ↓
delete_nodes_for_files(changed_files, repo_path)
    ├─ SQLite: delete graph_nodes where file_path IN (changed_files)
    ├─ SQLite: delete incident graph_edges
    └─ SQLite: delete incident graph_edges (reverse direction)
    ↓
delete_embeddings_for_files(changed_files, repo_path)
    ├─ pgvector: delete code_embeddings where repo_path = ? AND file_path IN (...)
    └─ FTS5: delete code_fts where file_path IN (...)
    ↓
Parse changed files only (same as full pipeline)
    └─ ast_parser.py: 10 concurrent workers via Semaphore
    ↓
Build + save graph (replaces deleted nodes with new versions)
    └─ De-duplicate node_ids within the parse
    └─ De-duplicate raw edges
    ↓
Embed + upsert (ON CONFLICT DO UPDATE in pgvector)
    └─ FTS5: DELETE + INSERT (no ON CONFLICT in FTS5)
```

**Key Design:**
- No partial graph updates — always full re-write (idempotent)
- File-level deletion ensures stale nodes (removed/renamed functions) are fully purged
- Concurrent parsing with semaphore prevents resource exhaustion

---

## Module Breakdown

### `walker.py` — Repository Discovery

**Public API:**
```python
walk_repo(repo_path: str, languages: list[str]) -> list[dict]
```

**Algorithm:**
1. Recursively traverse repo_path depth-first
2. At each directory, parse `.gitignore` (via `pathspec` library)
3. Skip (hard-coded):
   - `.git/`, `node_modules/`, `__pycache__/`, `.pytest_cache/`, `.venv/`, `venv/`
   - Files > 500 KB (likely generated, binary)
4. Include files matching language extensions:
   - Python: `.py`
   - TypeScript: `.ts`, `.tsx`, `.js`, `.jsx`
5. Return `FileEntry(path, language, size_kb)` in discovery order

**Guarantees:**
- Respects `.gitignore` at every directory level
- Never lists the same file twice
- Always includes a `size_kb` field (used for logging, not filtering)

**Example:**
```python
files = walk_repo("/path/to/nexus", ["python", "typescript"])
# [
#   FileEntry(path="backend/app/main.py", language="python", size_kb=3),
#   FileEntry(path="backend/app/config.py", language="python", size_kb=2),
#   FileEntry(path="extension/src/extension.ts", language="typescript", size_kb=5),
# ]
```

---

### `ast_parser.py` — Code Structure Extraction

**Public API:**
```python
parse_file(file_path: str, repo_root: str, language: str) -> tuple[list[CodeNode], list[tuple]]
```

Returns `(CodeNode list, raw_edge_tuples)` where:
- **CodeNode** — function, class, or method with full metadata
- **raw_edge_tuples** — `(source_node_id, target_name, edge_type)` — edges are unresolved

**Internals (Python):**

1. **Tree-sitter parsing:**
   ```python
   PY_DEFS_QUERY = Query(PY_LANGUAGE, """
     (function_definition name: (identifier) @func.name) @func.def
     (class_definition name: (identifier) @class.name) @class.def
   """)
   ```

2. **CodeNode construction:**
   - Extract signature (declaration before body)
   - Extract docstring (first statement in function/class body)
   - Extract body_preview (first 1000 chars + `[...]` + last 3000 chars for long functions)
   - Compute cyclomatic complexity (keyword count proxy: `if|for|while|try|elif|and|or`)
   - Build `embedding_text = f"{signature}\n{docstring}\n{body_preview}"`

3. **Edge emission:**
   - **CALLS edges:** for each call target in the function body
   - **IMPORTS edges:** module-level imports (synthetic source_id = `rel_path::__module__`)

4. **Method vs. Function distinction:**
   - Track class line ranges
   - If function start/end falls within a class range → type="method"
   - Else → type="function"

**Internals (TypeScript):**

1. **Dialect selection:**
   - `.tsx` files → `language_tsx()`
   - `.ts|.js|.jsx` files → `language_typescript()`

2. **Extracted node types:**
   - `function_declaration` → type="function"
   - `class_declaration` → type="class"
   - `method_definition` → type="method"
   - `arrow_function` (lexical_declaration) → type="function"

3. **No docstrings** — TypeScript docstrings are comments, not expressions; currently extracted via signature only

**Concurrency:**
```python
async def _parse_concurrent(files: list, repo_path: str):
    sem = Semaphore(PARSE_CONCURRENCY)  # default 10
    tasks = [_one(entry) for entry in files]  # async to_thread(parse_file, ...)
    results = await asyncio.gather(*tasks, return_exceptions=True)
    # Warnings logged for failed files; results collected anyway
```

**Body Preview Strategy:**

For factory functions and other code patterns that return large data structures (e.g., `Team(members=[...])` at the end of a 5000-char body), the preview captures:
- First 1000 characters (setup/imports)
- `[...]` separator
- Last 3000 characters (return statement, final code)

This ensures the LLM sees both the initialization AND the key return/construction statement.

**Example:**
```
node_id = "backend/app/agent/orchestrator.py::build_graph"
name = "build_graph"
type = "function"
file_path = "/abs/path/backend/app/agent/orchestrator.py"
line_start = 226
line_end = 292
signature = "def build_graph(checkpointer: BaseCheckpointSaver | None = None):"
docstring = "Compile and return the NexusState graph. ..."
body_preview = "g = StateGraph(NexusState)\n    g.add_node(...)\n[...]\n    return g.compile(...)"
complexity = 8  # multiple if/for keywords
embedding_text = "def build_graph(...)\nCompile and return...\ng = StateGraph(...)\n[...]\n    return..."
```

---

### `graph_builder.py` — Graph Construction & Metrics

**Public API:**
```python
build_graph(nodes: list[CodeNode], raw_edges: list[tuple]) -> nx.DiGraph
```

**Algorithm:**

1. **Add all nodes (pass 1):**
   - Create registries: `name → [node_ids]` and `file_key → [node_ids]`
   - Add all CodeNode attributes to the graph using `model_dump()`

2. **Resolve edges (pass 2):**
   - **CALLS edges:** resolve `target_name` via name registry
     - Take first match (name collision handling, known V1 limitation)
     - Add edge with `type="CALLS"` attribute
   - **IMPORTS edges:** handle synthetic `__module__` source IDs
     - If source_id ends with `::__module__`, extract file prefix
     - Resolve target module path: `auth.utils` → `auth/utils.py` (also try `__init__.py`)
     - Emit edges from all nodes in importing file to all nodes in imported file
   - Unresolvable edges logged as warnings, dropped

3. **Compute metrics (pass 3):**
   - **PageRank:** `nx.pagerank(G)` — importance score per node
   - **In-degree:** number of predecessors (callers)
   - **Out-degree:** number of successors (callees)
   - Store as node attributes

**IMPORTS Edge Design (Option A from Research):**

Raw IMPORTS edges use synthetic source_id `rel_path::__module__` (not a real node). This function expands them:

```
raw edge: (file.py::__module__, requests, IMPORTS)
  ↓
resolve target: "requests" → no matching file in repo (external lib)
  ↓
warning: unresolvable IMPORTS edge, skip
```

```
raw edge: (auth/middleware.py::__module__, auth.utils, IMPORTS)
  ↓
resolve target: "auth.utils" → "auth/utils.py" in file_to_ids registry
  ↓
emit edges: auth/middleware.py::* → auth/utils.py::* (all pairwise)
```

**Handles:**
- Relative imports (prefix with `.`) — skipped
- Empty module names — skipped
- Unresolvable module paths — logged, skipped

**Example Graph State:**
```
Nodes (sample):
  backend/app/agent/router.py::route: {
    node_id: "backend/app/agent/router.py::route",
    name: "route",
    type: "function",
    file_path: "/abs/path/backend/app/agent/router.py",
    line_start: 71,
    line_end: 111,
    signature: "def route(question: str, intent_hint: str | None = None) -> IntentResult:",
    pagerank: 0.0045,
    in_degree: 15,
    out_degree: 2,
    ...
  }

Edges:
  router.py::route → orchestrator.py::_router_node [type=CALLS]
  router.py::route → model_factory.py::get_llm [type=CALLS]
  router.py::route → router.py::ROUTER_PROMPT [type=IMPORTS]
```

---

### `embedder.py` — Dense & Full-Text Indexing

**Public API:**
```python
embed_and_store(nodes: list[CodeNode], repo_path: str) -> int
    # Returns count of successfully stored nodes

delete_embeddings_for_repo(repo_path: str) -> None
    # Purge all embeddings for entire repo

delete_embeddings_for_files(file_paths: list[str], repo_path: str) -> None
    # Purge embeddings for specific files (incremental re-index)
```

**pgvector Schema:**
```sql
CREATE TABLE code_embeddings (
    id TEXT PRIMARY KEY,
    repo_path TEXT NOT NULL,
    name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    line_start INT,
    line_end INT,
    embedding vector(1536)  -- or vector(1024) for Mistral
)
```

**FTS5 Schema:**
```sql
CREATE VIRTUAL TABLE code_fts USING fts5(
    node_id UNINDEXED,   -- stored but not indexed
    name,                -- primary search field
    file_path UNINDEXED
)
```

**Batch Processing:**
```python
EMBED_BATCH_SIZE = 100

for i in range(0, len(nodes), EMBED_BATCH_SIZE):
    batch = nodes[i : i + EMBED_BATCH_SIZE]
    # Deduplicate within batch (handle concurrent parse dupes)
    batch_map = {n.node_id: n for n in batch}
    batch = list(batch_map.values())

    # Embed texts
    texts = [n.embedding_text for n in batch]
    embeddings = embedder.embed(texts)  # to pgvector provider

    # Upsert to pgvector
    execute_values(
        cur,
        """INSERT INTO code_embeddings (...) VALUES %s
           ON CONFLICT (id) DO UPDATE SET ...""",
        rows,
    )

    # Upsert to FTS5 (DELETE + INSERT — no ON CONFLICT)
    sqlite_conn.executemany("DELETE FROM code_fts WHERE node_id = ?", ...)
    sqlite_conn.executemany("INSERT INTO code_fts VALUES (...)", ...)
    sqlite_conn.commit()
```

**Error Handling:**
- Embedding batch fails → warning logged, batch skipped, total_stored unchanged
- pgvector upsert fails → warning logged, batch skipped
- FTS5 upsert fails → warning logged, pgvector was stored (inconsistency accepted)

**Provider Abstraction:**
```python
embedder = get_embedding_client()  # Mistral or OpenAI (lazy init)
embeddings = embedder.embed(texts)  # list[list[float]]
```

---

### `graph_store.py` — SQLite Persistence

**Public API:**
```python
save_graph(G: nx.DiGraph, repo_path: str) -> None
    # Full replace (idempotent) — deletes old data for repo_path

load_graph(repo_path: str) -> nx.DiGraph
    # Reconstruct from SQLite

delete_graph_for_repo(repo_path: str) -> None
    # Purge all nodes and edges for repo

delete_nodes_for_files(file_paths: list[str], repo_path: str) -> None
    # Delete nodes by file_path + incident edges (incremental re-index)
```

**Schema:**
```sql
CREATE TABLE graph_nodes (
    node_id TEXT NOT NULL,
    repo_path TEXT NOT NULL,
    file_path TEXT NOT NULL,
    attrs_json TEXT NOT NULL,
    PRIMARY KEY (node_id, repo_path)
)

CREATE TABLE graph_edges (
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    repo_path TEXT NOT NULL,
    attrs_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (source, target, repo_path)
)
```

**Design Notes:**
- `file_path` is **promoted from attrs_json to its own column** so `delete_nodes_for_files()` can use WHERE without JSON parsing
- `attrs_json` contains **all CodeNode fields** (signature, docstring, body_preview, embedding_text, pagerank, in_degree, out_degree)
- `save_graph()` does **full replace** — deletes old rows first, then inserts all new rows (idempotent, safe for interruption)
- JSON serialization uses `default=str` as safety net for non-serializable types (rarely needed)

**Incremental Deletion (for file watcher):**

```python
def delete_nodes_for_files(file_paths, repo_path):
    # Step 1: Find node_ids for files being deleted
    node_ids = conn.execute(
        f"SELECT node_id FROM graph_nodes WHERE repo_path = ? AND file_path IN (...)",
        [repo_path, *file_paths],
    ).fetchall()

    # Step 2: Delete incident edges (source or target in node_ids)
    conn.execute(
        f"DELETE FROM graph_edges WHERE repo_path = ? AND (source IN (...) OR target IN (...))",
        [repo_path, *node_ids, *node_ids],
    )

    # Step 3: Delete nodes by file_path (consistent with spec)
    conn.execute(
        f"DELETE FROM graph_nodes WHERE repo_path = ? AND file_path IN (...)",
        [repo_path, *file_paths],
    )
    conn.commit()
```

---

### `pipeline.py` — Orchestration

**Public API:**
```python
async def run_ingestion(
    repo_path: str,
    languages: list[str],
    changed_files: list[str] | None = None,
) -> IndexStatus
```

**Orchestration:**

1. **Determine parsing scope:**
   - Full: `walk_repo(repo_path, languages)`
   - Incremental: filter `changed_files` by language extension

2. **Concurrent parsing (10 workers):**
   ```python
   all_nodes, all_edges = await _parse_concurrent(files_to_parse, repo_path)
   ```

3. **Validation:**
   - Drop nodes with empty `node_id` (faulty parser output)
   - Deduplicate node_ids by keeping last-seen (re-exports, __init__.py)

4. **Graph construction:**
   ```python
   G = build_graph(all_nodes, all_edges)
   ```

5. **Persistence:**
   ```python
   await asyncio.to_thread(save_graph, G, repo_path)
   nodes_stored = await asyncio.to_thread(embed_and_store, all_nodes, repo_path)
   ```

6. **Status tracking:**
   ```python
   _status[repo_path] = IndexStatus(
       status="complete",
       nodes_indexed=nodes_stored,
       edges_indexed=G.number_of_edges(),
       files_processed=len(files_to_parse),
   )
   ```

**Status API:**
```python
get_status(repo_path: str) -> IndexStatus | None
clear_status(repo_path: str) -> None
```

---

## Configuration & Tuning

**Environment Variables:**
- `EMBEDDING_PROVIDER` — mistral | openai (determines dimensions)
- `mistral_api_key` / `openai_api_key` — required for embedding
- `postgres_host`, `postgres_port`, etc. — database connection

**Tuning Knobs (in code):**
- `PARSE_CONCURRENCY = 10` — concurrent tree-sitter workers
- `EMBED_BATCH_SIZE = 100` — batch size for pgvector upserts
- Walker skip list (`.git`, `node_modules`, etc.) — hardcoded

---

## Performance Characteristics

| Operation | Typical Time (10k LOC repo) |
|-----------|---------------------------|
| Walk repo | ~100ms |
| Parse AST (10 workers) | ~2s |
| Build graph + PageRank | ~500ms |
| Embed + upsert (100 batches) | ~5s (depends on provider latency) |
| **Total indexing time** | **~8–10s** |

**Bottleneck:** Embedding API latency (100ms–500ms per batch of 100 nodes).

---

## Error Handling & Recovery

| Scenario | Behavior |
|----------|----------|
| File > 500 KB | Skipped by walker (logged as warning) |
| Parse error | Warning logged, file skipped, continue |
| Embedding batch fails | Warning logged, batch skipped, continue |
| pgvector upsert fails | Warning logged, batch skipped |
| FTS5 upsert fails | Warning logged, pgvector still stored (inconsistency) |
| Zero nodes extracted | Warning logged, status="complete" (may be empty repo) |
| Unresolvable edge | Warning logged, edge dropped |

**Recovery:**
- Retry indexing: `POST /index` again (full replace is idempotent)
- Clear data: `DELETE /index?repo_path=...`, then re-index
- Inspect logs: `docker logs nexus_backend | grep "ingestion"`

---

## Testing

All ingestion components are heavily tested:

| Test File | Focus |
|-----------|-------|
| `test_file_walker.py` | .gitignore, language detection, size limits |
| `test_ast_parser.py` | Python/TypeScript parsing, edge emission, body preview |
| `test_graph_builder.py` | Edge resolution, IMPORTS handling, PageRank |
| `test_embedder.py` | Batch processing, upsert, multi-repo isolation |
| `test_graph_store.py` | SQLite persistence, incremental deletion |
| `test_pipeline.py` | Full integration, incremental re-index, error cases |

Run all:
```bash
python -m pytest backend/tests/test_ingestion*.py -v
```

---

## Limitations & Known Issues

1. **Name collision (V1 design):** CALLS edges resolve to first function with matching name. If two functions have the same name in different files, one is chosen arbitrarily. Mitigation: use module-qualified names in prompts.

2. **No cross-repo linking:** Imports to external packages (e.g., `requests`) are skipped. Mitigation: internal module imports are fully resolved.

3. **TypeScript docstrings not extracted:** Comments are not parsed. Mitigation: use JSDoc format; explorer.py extracts signatures only.

4. **FTS5 search:** SQLite FTS5 is exact-match (phrase search). Typos in node names won't be found. Mitigation: pgvector semantic search is used for free-text queries.

---

## Future Work (Phase 27+)

- [ ] Handle name collisions via module-qualified CALLS edges
- [ ] Extract TypeScript JSDoc comments
- [ ] Support Java, Go, Rust (via tree-sitter)
- [ ] Parallel embedding batches across provider replicas
- [ ] Incremental PageRank updates (instead of full recompute)
