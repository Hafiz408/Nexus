---
phase: 04-graph-builder
plan: "01"
subsystem: graph-builder
tags: [networkx, pagerank, edge-resolution, tdd, graph-rag]
dependency_graph:
  requires: [backend/app/models/schemas.py, backend/app/ingestion/ast_parser.py]
  provides: [backend/app/ingestion/graph_builder.py]
  affects: [Phase 05 - Embedder, Phase 06 - Graph RAG retrieval]
tech_stack:
  added: [networkx>=3.4, scipy>=1.10.0]
  patterns: [3-pass graph construction, synthetic __module__ source_id fan-out, PageRank via nx.pagerank]
key_files:
  created:
    - backend/app/ingestion/graph_builder.py
    - backend/tests/test_graph_builder.py
  modified:
    - backend/tests/conftest.py
    - backend/requirements.txt
decisions:
  - scipy added alongside networkx — nx.pagerank() delegates to _pagerank_scipy() in networkx 3.6; no scipy = ModuleNotFoundError at runtime
  - 3-pass construction order enforced — Pass 1 (nodes) must complete before Pass 2 (edges) to prevent bare attribute-less nodes from G.add_edge auto-creation
  - synthetic ::__module__ source_id fan-out — when source_id ends with ::__module__, edges are emitted from all real nodes in the importing file to all real nodes in the target file (Option A from RESEARCH.md)
  - node.model_dump() used (not node.dict()) — Pydantic v2 API; dict() deprecated
  - warnings.warn with UserWarning (stacklevel=2) — required for pytest.warns(UserWarning) to capture correctly
metrics:
  duration_seconds: 165
  completed_date: "2026-03-18"
  tasks_completed: 2
  files_created: 3
  files_modified: 2
---

# Phase 04 Plan 01: Graph Builder Summary

**One-liner:** NetworkX DiGraph construction with 3-pass build_graph() — CALLS/IMPORTS edge resolution, synthetic __module__ fan-out, and PageRank scoring via scipy.

## What Was Built

`build_graph(nodes, raw_edges) -> nx.DiGraph` — the connective tissue between the AST parser (Phase 3) and the Graph RAG retrieval (Phases 5-8). Takes CodeNode objects and raw edge tuples, constructs a fully attributed DiGraph with PageRank scores.

### Implementation: 3-Pass Construction

**Pass 1 — Add nodes:** All CodeNode attributes stored on graph nodes via `node.model_dump()`. Two registries built: `name_to_ids` (for CALLS resolution) and `file_to_ids` (for IMPORTS resolution).

**Pass 2 — Resolve edges:**
- CALLS: exact name match on `target_name` against `name_to_ids`; unresolvable targets dropped with `warnings.warn(UserWarning)`
- IMPORTS: when `source_id` ends with `::__module__`, fan out edges from all nodes in importing file to all nodes in target file; relative/empty imports dropped with warning

**Pass 3 — Compute metrics:** `nx.pagerank(G, alpha=0.85)`, `G.in_degree()`, `G.out_degree()` stored as node attributes. Guarded with `if G.number_of_nodes() == 0: return` to prevent crash on empty graphs.

### Test Suite

18 tests in `test_graph_builder.py` covering:
- GRAPH-01: DiGraph returned with all node attributes preserved
- GRAPH-02: CALLS edge resolution (resolvable + unresolvable with UserWarning)
- GRAPH-03: IMPORTS edge resolution (__module__ fan-out, relative/empty import skipping)
- GRAPH-04: pagerank (float), in_degree (int), out_degree (int) on every node
- Edge cases: empty graph, duplicate edges (DiGraph deduplication), empty target imports

## Test Results

- 18/18 graph builder tests pass (GREEN)
- 47/47 total project tests pass (no regressions)
  - 12 test_file_walker.py
  - 17 test_ast_parser.py
  - 18 test_graph_builder.py

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] scipy missing for nx.pagerank()**
- **Found during:** Task 2 (GREEN — first test run)
- **Issue:** networkx 3.6.1 delegates `nx.pagerank()` to `_pagerank_scipy()` which requires scipy. scipy was not in requirements.txt and not installed, causing `ModuleNotFoundError: No module named 'scipy'` on every test calling `build_graph()` with non-empty graphs.
- **Fix:** Installed scipy and added `scipy>=1.10.0` to `backend/requirements.txt`
- **Files modified:** backend/requirements.txt
- **Commit:** cd9fefe (included with Task 2 commit)

**2. [Minor] Test count discrepancy — plan says 19 tests, implementation has 18**
- **Found during:** Task 1 (RED)
- **Issue:** Plan text references "19 test cases" in multiple places, but the `<behavior>` section and test code in the plan contains exactly 18 test functions. Counted from the plan's test code block: 18 `def test_` functions.
- **Fix:** Implemented all 18 test functions as specified in the plan's code. No test was missing relative to the specified behavior cases.
- **Impact:** None — all specified behaviors are covered.

## Self-Check: PASSED

- FOUND: backend/app/ingestion/graph_builder.py
- FOUND: backend/tests/test_graph_builder.py
- FOUND: backend/tests/conftest.py (with sample_nodes, sample_raw_edges fixtures)
- FOUND: commit 48d5b78 (test RED phase)
- FOUND: commit cd9fefe (feat GREEN phase)
