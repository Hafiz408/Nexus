# Ingestion

Transforms raw source code into a queryable knowledge base: **discover → parse → graph → embed**.

## Flow

```
POST /index
    │
    ├─ walker       discover .py / .ts / .tsx files (respects .gitignore)
    │
    ├─ ast_parser   tree-sitter: extract functions, classes, methods
    │               emit CodeNode + raw CALLS/IMPORTS edge tuples
    │               (10 concurrent workers)
    │
    ├─ graph_builder resolve edges by name/path → NetworkX DiGraph
    │               compute PageRank, in-degree, out-degree
    │
    ├─ graph_store  persist DiGraph → SQLite (graph_nodes, graph_edges)
    │
    └─ embedder     batch embed (100/batch) → pgvector + FTS5 dual write
```

**Incremental mode:** On file save, the FileWatcher triggers re-index for changed files only. Stale nodes are purged at file-path granularity before re-parsing.

## Components

| File | Role |
|---|---|
| `walker.py` | Depth-first traversal, gitignore-aware, skips `node_modules` / `venv` / files > 500 KB |
| `ast_parser.py` | tree-sitter for Python + TypeScript; extracts signature, docstring, body preview, complexity |
| `graph_builder.py` | Resolves raw edge tuples by name/module registry; builds DiGraph; runs PageRank |
| `graph_store.py` | SQLite persistence with file-level deletion for incremental updates |
| `embedder.py` | Batched upsert to pgvector (`ON CONFLICT DO UPDATE`) + FTS5 name index |
| `pipeline.py` | Orchestrator — concurrent parse, dedup, build, persist, status tracking |

## Storage Layout

```
SQLite (data/nexus.db)
  graph_nodes   node_id · repo_path · file_path · attrs_json
  graph_edges   source · target · repo_path · edge_type
  code_fts      FTS5 virtual table on node names

PostgreSQL
  code_embeddings   id · repo_path · file_path · embedding vector(1024|1536)
```
