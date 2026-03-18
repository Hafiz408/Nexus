---
phase: 05-embedder
plan: "01"
subsystem: database
tags: [sqlite, networkx, digraph, persistence, graph-store]

# Dependency graph
requires:
  - phase: 04-graph-builder
    provides: build_graph() returning nx.DiGraph with node attrs from model_dump() + pagerank floats
provides:
  - save_graph(G, repo_path) — persists all nodes and edges to SQLite data/nexus.db
  - load_graph(repo_path) — reconstructs nx.DiGraph with all attributes
  - delete_nodes_for_files(file_paths, repo_path) — incremental delete by file_path + incident edges
affects: [05-embedder, 06-pipeline]

# Tech tracking
tech-stack:
  added: []
  patterns: [sqlite3-single-file-multi-repo, executemany-bulk-insert, sqlite3-row-factory]

key-files:
  created:
    - backend/app/ingestion/graph_store.py
  modified: []

key-decisions:
  - "data/nexus.db single file for all repos; repo_path TEXT column scopes all queries — matches RESEARCH.md recommendation (simpler than per-repo files)"
  - "file_path promoted to dedicated column in graph_nodes — enables O(n) delete without JSON parsing"
  - "json.dumps(attrs, default=str) safety net — handles pagerank floats and any future non-serialisable types"
  - "save_graph deletes then re-inserts (full replace) — idempotent; not incremental merge"
  - "sqlite3.Row factory on every connection — readable column access without index magic"

patterns-established:
  - "_get_conn(db_path) helper: creates schema with IF NOT EXISTS, returns conn with Row factory — reused by all three public functions"
  - "delete_nodes_for_files: SELECT affected node_ids first, then DELETE edges by node_id, then DELETE nodes by file_path — two-step avoids file_path join across two tables"

requirements-completed: [STORE-01, STORE-02, STORE-03]

# Metrics
duration: 2min
completed: 2026-03-18
---

# Phase 5 Plan 01: Graph Store Summary

**SQLite persistence layer for nx.DiGraph using single data/nexus.db file with repo_path-scoped graph_nodes and graph_edges tables, supporting full round-trip save/load and incremental file-based node deletion**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-18T12:38:21Z
- **Completed:** 2026-03-18T12:40:00Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- `save_graph` persists all nodes with promoted `file_path` column and all edges to SQLite; full replace per repo_path
- `load_graph` reconstructs nx.DiGraph with all node attributes (including pagerank floats) via json.loads
- `delete_nodes_for_files` removes nodes by file_path and all incident edges without JSON parsing
- 47 existing tests still pass (no regressions)

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement graph_store.py with save_graph, load_graph, delete_nodes_for_files** - `f90337f` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified
- `backend/app/ingestion/graph_store.py` - SQLite persistence layer: `_db_path`, `_get_conn`, `save_graph`, `load_graph`, `delete_nodes_for_files`

## Decisions Made
- Used `data/nexus.db` single file (not per-repo files) as specified by RESEARCH.md — simpler and consistent with bind-mount approach from Phase 1 infrastructure
- `file_path` column is a separate column (not extracted from JSON) — supports efficient WHERE clause in `delete_nodes_for_files` without LIKE/JSON parsing
- `json.dumps(default=str)` used as safety net — pagerank floats serialise fine but numpy types (if introduced later) would silently coerce to string rather than crash
- Full replace on `save_graph` (DELETE then INSERT) keeps implementation simple for V1; incremental merge is a Phase 6+ concern

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- `graph_store.py` is ready for Phase 5 Plans 02/03 (Embedder) which need `save_graph`/`load_graph` for round-trip fidelity tests
- `delete_nodes_for_files` is ready for Phase 6 Pipeline incremental re-index
- The `data/` directory is created by `os.makedirs` in the `sqlite3.connect` call path — no pre-flight needed

---
*Phase: 05-embedder*
*Completed: 2026-03-18*
