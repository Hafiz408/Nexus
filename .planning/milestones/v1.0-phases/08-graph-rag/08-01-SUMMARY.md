---
phase: 08-graph-rag
plan: 01
subsystem: retrieval
tags: [networkx, pgvector, openai, graph-rag, bfs, reranking, cosine-similarity]

# Dependency graph
requires:
  - phase: 05-embedder
    provides: "pgvector code_embeddings table with cosine search via <=> operator; register_vector per-connection pattern"
  - phase: 04-graph-builder
    provides: "nx.DiGraph with full model_dump node attrs including pagerank, in_degree, out_degree"
  - phase: 03-ast-parser
    provides: "CodeNode schema with all required fields"
provides:
  - "backend/app/retrieval/__init__.py — Python package init"
  - "backend/app/retrieval/graph_rag.py — four public retrieval functions: semantic_search, expand_via_graph, rerank_and_assemble, graph_rag_retrieve"
affects: [09-explorer-agent, phase-9-qa, testing]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Graph RAG 3-step pipeline: vector search -> BFS expansion -> score reranking"
    - "nx.ego_graph(undirected=True) for bidirectional BFS on DiGraph"
    - "nx.subgraph_view() zero-copy edge-type filtering"
    - "Lazy OpenAI client init inside function body (not module level)"
    - "CodeNode hydration from G.nodes[node_id] attrs, not pgvector rows"

key-files:
  created:
    - backend/app/retrieval/__init__.py
    - backend/app/retrieval/graph_rag.py
  modified: []

key-decisions:
  - "semantic_search returns (node_id, score) pairs not CodeNode objects — code_embeddings table lacks signature/docstring/body_preview fields; full CodeNode hydration happens in graph_rag_retrieve via G.nodes"
  - "nx.ego_graph(undirected=True) used for bidirectional BFS — covers both predecessors (callers) and successors (callees) in one call; nx.bfs_tree only follows outgoing edges"
  - "nx.subgraph_view() zero-copy view for edge_types filtering — avoids copying the full graph when restricting traversal to specific edge types"
  - "Lazy OpenAI client init: client = OpenAI() inside semantic_search body, not at module level — prevents ValidationError on import when OPENAI_API_KEY absent (matches embedder.py pattern)"
  - "max_in_degree guard: max(in_degrees) if in_degrees else 1 — prevents ZeroDivisionError when all expanded nodes have in_degree 0"
  - "RAG-03 formula applied verbatim: semantic + (0.2 * pagerank) + (0.1 * in_degree_norm) with 0.3 fallback for non-seed nodes"

patterns-established:
  - "Graph RAG retrieval: three-step pipeline always called via graph_rag_retrieve orchestrator"
  - "Bidirectional BFS: always use nx.ego_graph(undirected=True), never nx.bfs_tree"
  - "Node hydration: always from G.nodes[node_id] dict, never reconstruct from pgvector rows"
  - "Edge filtering: nx.subgraph_view with filter_edge lambda for zero-copy type-scoped traversal"

requirements-completed: [RAG-01, RAG-02, RAG-03, RAG-04]

# Metrics
duration: 4min
completed: 2026-03-19
---

# Phase 8 Plan 01: Graph RAG Retrieval Package Summary

**Graph RAG three-step retrieval pipeline in app/retrieval/graph_rag.py: pgvector cosine search + bidirectional BFS via nx.ego_graph + RAG-03 weighted reranking returning list[CodeNode] and stats dict**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-19T07:28:31Z
- **Completed:** 2026-03-19T07:32:31Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Created `backend/app/retrieval/` package mirroring the existing `app/ingestion/` layout
- Implemented `semantic_search` — lazy OpenAI client, pgvector `<=>` cosine query, returns (node_id, score) pairs scoped by repo_path
- Implemented `expand_via_graph` — bidirectional BFS via `nx.ego_graph(undirected=True)` with optional zero-copy edge_types filtering via `nx.subgraph_view`
- Implemented `rerank_and_assemble` — exact RAG-03 formula with 0.3 fallback for non-seed nodes and zero-division guard; reconstructs CodeNode from G.nodes attrs
- Implemented `graph_rag_retrieve` — orchestrates all three steps, returns (list[CodeNode], stats_dict) with seed_count/expanded_count/returned_count/hop_depth

## Task Commits

Each task was committed atomically:

1. **Task 1: Create retrieval package skeleton** - `33106ec` (chore)
2. **Task 2: Implement graph_rag.py with all four retrieval functions** - `81bd71c` (feat)

## Files Created/Modified
- `backend/app/retrieval/__init__.py` - Empty package init
- `backend/app/retrieval/graph_rag.py` - Four public functions: semantic_search, expand_via_graph, rerank_and_assemble, graph_rag_retrieve

## Decisions Made
- `semantic_search` returns `list[tuple[str, float]]` not CodeNode objects — `code_embeddings` table only has (id, name, file_path, line_start, line_end), lacks signature/docstring/body_preview; full CodeNode hydration deferred to `graph_rag_retrieve` which reads from `G.nodes`
- `nx.ego_graph(undirected=True)` chosen over manual BFS with `G.predecessors()`/`G.successors()` — one-line call handles depth tracking, visited set, and bidirectionality
- `nx.subgraph_view` for edge_types filtering — zero-copy view, no graph copying overhead
- `from openai import OpenAI` kept at module level (same as embedder.py); lazy init means `client = OpenAI(api_key=...)` is inside the function body — import never raises ValidationError when OPENAI_API_KEY absent

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Functional test with manually constructed graph attrs (no node_id in attrs dict) initially failed in CodeNode reconstruction — confirmed this is test fixture pattern issue, not a code bug; real `build_graph()` uses `model_dump()` which always includes node_id as an attr. Implementation is correct for real usage.
- Pre-existing test failures in `tests/test_embedder.py` (4 tests) were confirmed pre-existing (unrelated to this plan's changes, missing postgres env vars in CI env); out of scope per deviation rules.

## Next Phase Readiness
- All four functions importable with no errors even when OPENAI_API_KEY is not set
- Ready for Phase 8 test plan (RAG-05, RAG-06, TEST-05, TEST-06) — conftest fixtures and test_graph_rag.py
- Ready for Phase 9 Explorer Agent which will call graph_rag_retrieve as its retrieval step

---
*Phase: 08-graph-rag*
*Completed: 2026-03-19*
