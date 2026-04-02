# Phase 8: Graph RAG - Research

**Researched:** 2026-03-19
**Domain:** Graph-augmented retrieval — NetworkX BFS expansion + pgvector semantic search + reranking
**Confidence:** HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| RAG-01 | `semantic_search(query, repo_path, top_k)` embeds query, cosine similarity in pgvector, returns top_k CodeNodes | pgvector `<=>` operator section; OpenAI embeddings mock pattern |
| RAG-02 | `expand_via_graph(seed_node_ids, G, hop_depth, edge_types)` BFS in both directions up to `hop_depth` hops; returns deduplicated node IDs | NetworkX `ego_graph(undirected=True)` or manual predecessor/successor BFS with depth_limit |
| RAG-03 | `rerank_and_assemble(expanded_node_ids, seed_scores, G, max_nodes)` — exact formula: `(semantic_score if seed else 0.3) + (0.2 * pagerank) + (0.1 * in_degree_norm)` | Score formula section; PageRank + in_degree already stored as node attributes on G |
| RAG-04 | `graph_rag_retrieve(query, repo_path, G, max_nodes, hop_depth)` orchestrates full 3-step retrieval, returns `(list[CodeNode], stats_dict)` | Orchestration pattern section |
| RAG-05 | Unit tests pass using in-memory NetworkX fixture — no database required | Mock embedder pattern; conftest `sample_graph` fixture design |
| RAG-06 | Tests verify BFS expansion at hop depth 1 and 2, reranking order, max_nodes limit | Test fixture and assertion patterns |
| TEST-05 | `tests/test_graph_rag.py` — BFS expansion, reranking, max_nodes; all with in-memory fixture (no DB) | New test file design section |
| TEST-06 | `tests/conftest.py` — `mock_embedder` (deterministic np.random.seed(42)), `sample_graph` (small NetworkX DiGraph) | conftest additions section |

</phase_requirements>

---

## Summary

Phase 8 implements the Graph RAG retrieval layer: a three-step pipeline that (1) embeds the user query and runs cosine similarity search in pgvector to get seed nodes, (2) expands the seed set by BFS traversal of the code call/import graph in both directions, and (3) reranks the expanded set using a weighted combination of semantic score, PageRank, and in-degree normalisation.

All required libraries are already installed — NetworkX (with scipy for PageRank), pgvector with psycopg2, and OpenAI SDK are dependencies from Phases 4, 5. The retrieval module belongs in a new `app/retrieval/` package to mirror the existing `app/ingestion/` package layout. The graph (`nx.DiGraph`) is received as a parameter to every function, which eliminates all database dependencies from the retrieval path and makes tests trivially achievable with in-memory NetworkX fixtures.

The primary risk is correctly implementing bidirectional BFS on a `nx.DiGraph`. Since `nx.bfs_successors` and `nx.bfs_predecessors` traverse only one direction, the safest approach is `nx.ego_graph(G, node, radius=hop_depth, undirected=True)` which internally calls `G.to_undirected()` before BFS — this covers both callers and callees in one call. In-degree normalisation requires tracking the maximum in-degree across all expanded nodes to avoid a zero-division error.

**Primary recommendation:** Implement `app/retrieval/graph_rag.py` with four public functions in dependency order: `semantic_search` → `expand_via_graph` → `rerank_and_assemble` → `graph_rag_retrieve`. Use `nx.ego_graph(undirected=True)` for bidirectional BFS and the exact formula from RAG-03 verbatim.

---

## Standard Stack

### Core (already installed — no new dependencies)

| Library | Version (from project) | Purpose | Why Standard |
|---------|------------------------|---------|--------------|
| networkx | 3.x (+ scipy) | DiGraph BFS traversal, ego_graph, node attribute access | Already used in graph_builder.py; scipy enables PageRank |
| pgvector (psycopg2 adapter) | installed | `<=>` cosine distance operator in SQL | Already used in embedder.py; same connection pattern |
| openai | installed | Embed query via `text-embedding-3-small` | Same model used in embed_and_store() — vectors are comparable |
| numpy | installed (transitive) | Deterministic mock vectors in tests via `np.random.seed(42)` | Enables reproducible test embeddings |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| unittest.mock | stdlib | Patch `openai.OpenAI` and `get_db_connection` in tests | No DB or API key needed in test suite |
| pytest | installed | Test runner | All tests use existing pytest harness |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `nx.ego_graph(undirected=True)` | Manual BFS with `G.predecessors()` + `G.successors()` | Manual is more explicit but requires deduplication and depth tracking by hand; ego_graph is one line and handles both directions |
| pgvector cosine query | In-memory numpy dot product | Would break the interface: semantic_search must use pgvector since that is where embeddings are persisted (EMBED-01) |

**Installation:** No new packages required — all dependencies already present.

---

## Architecture Patterns

### Recommended Project Structure

```
backend/app/
├── retrieval/
│   ├── __init__.py          # empty
│   └── graph_rag.py         # semantic_search, expand_via_graph, rerank_and_assemble, graph_rag_retrieve
├── ingestion/               # existing (Phases 2-6)
└── api/                     # existing (Phase 7)

backend/tests/
├── conftest.py              # ADD: mock_embedder, sample_graph fixtures
└── test_graph_rag.py        # NEW: all RAG-01 through RAG-06 tests
```

### Pattern 1: semantic_search — pgvector cosine query returning CodeNodes

**What:** Embed the query string, run a cosine similarity search against `code_embeddings`, reconstruct `CodeNode` objects from the result rows.
**When to use:** Step 1 of every `graph_rag_retrieve` call.

```python
# Source: embedder.py connection pattern + pgvector <=> operator
def semantic_search(query: str, repo_path: str, top_k: int) -> list[tuple[CodeNode, float]]:
    """Returns list of (CodeNode, cosine_similarity_score) sorted descending."""
    client = OpenAI(api_key=get_settings().openai_api_key)
    response = client.embeddings.create(model="text-embedding-3-small", input=[query])
    query_vec = response.data[0].embedding

    conn = get_db_connection()
    register_vector(conn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, file_path, line_start, line_end,
                       1 - (embedding <=> %s::vector) AS score
                FROM code_embeddings
                WHERE repo_path = %s
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (query_vec, repo_path, query_vec, top_k),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    # Reconstruct minimal CodeNode objects from DB rows
    # NOTE: only fields present in code_embeddings table are available here;
    # signature/docstring/body_preview require a graph lookup or a separate store.
    results = []
    for row in rows:
        node_id, name, file_path, line_start, line_end, score = row
        # Reconstruct from graph G if available; otherwise return partial node
        results.append((node_id, float(score)))
    return results
```

**IMPORTANT design decision:** `code_embeddings` table only stores `(id, name, file_path, line_start, line_end, embedding)` — it does NOT store `signature`, `docstring`, or `body_preview`. Full `CodeNode` objects must be retrieved from the `nx.DiGraph` node attributes (which store the complete `model_dump()` from the parser). This means `graph_rag_retrieve` must reconstruct `CodeNode` from `G.nodes[node_id]` dict, not from the pgvector query.

### Pattern 2: expand_via_graph — Bidirectional BFS

**What:** For each seed node ID, expand up to `hop_depth` hops in BOTH directions (callers and callees). Returns a flat, deduplicated set of node IDs.
**When to use:** Step 2 of retrieval pipeline.

```python
# Source: networkx.org ego_graph documentation
def expand_via_graph(
    seed_node_ids: list[str],
    G: nx.DiGraph,
    hop_depth: int,
    edge_types: list[str] | None = None,
) -> set[str]:
    """BFS expansion in both in- and out-edge directions up to hop_depth."""
    expanded = set()
    for node_id in seed_node_ids:
        if node_id not in G:
            continue
        # ego_graph with undirected=True treats all edges as bidirectional
        subgraph = nx.ego_graph(G, node_id, radius=hop_depth, undirected=True)
        expanded.update(subgraph.nodes())
    return expanded
```

**Key fact (HIGH confidence):** `nx.ego_graph(G, n, radius=hop_depth, undirected=True)` calls `G.to_undirected()` internally and then runs `single_source_shortest_path_length` with `cutoff=hop_depth`. This correctly includes both predecessors and successors within `hop_depth` steps. Source: networkx.org/documentation/stable/_modules/networkx/generators/ego.html

**edge_types filtering:** If `edge_types` is provided (e.g., `["CALLS"]` only), manually filter edges before BFS by constructing a subgraph view: `G_filtered = nx.subgraph_view(G, filter_edge=lambda u, v: G[u][v].get("type") in edge_types)`. This avoids copying the full graph.

### Pattern 3: rerank_and_assemble — Score combination

**What:** Score every expanded node using the exact formula from RAG-03 and return the top `max_nodes`.
**When to use:** Step 3 of retrieval pipeline.

```python
# Source: REQUIREMENTS.md RAG-03 verbatim formula
def rerank_and_assemble(
    expanded_node_ids: set[str],
    seed_scores: dict[str, float],   # node_id -> semantic similarity score from semantic_search
    G: nx.DiGraph,
    max_nodes: int,
) -> list[CodeNode]:
    """Score each node and return top max_nodes as CodeNode objects."""
    # Compute max in_degree for normalisation (avoid zero-division)
    in_degrees = [G.nodes[n].get("in_degree", 0) for n in expanded_node_ids if n in G]
    max_in_degree = max(in_degrees) if in_degrees else 1

    scored = []
    for node_id in expanded_node_ids:
        if node_id not in G:
            continue
        attrs = G.nodes[node_id]
        semantic = seed_scores.get(node_id, 0.3)   # 0.3 for non-seed nodes
        pagerank = attrs.get("pagerank", 0.0)
        in_degree_norm = attrs.get("in_degree", 0) / max_in_degree

        score = semantic + (0.2 * pagerank) + (0.1 * in_degree_norm)

        # Reconstruct CodeNode from graph attributes (complete node data is stored there)
        node = CodeNode(**{k: v for k, v in attrs.items() if k in CodeNode.model_fields})
        scored.append((score, node))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [node for _, node in scored[:max_nodes]]
```

**Formula (exact, from RAG-03):**
```
score = (semantic_score if seed else 0.3) + (0.2 * pagerank) + (0.1 * in_degree_norm)
```
- `semantic_score` = cosine similarity returned from pgvector (0.0–1.0)
- `0.3` = fallback score for non-seed nodes (graph-expanded but not in top-k vector results)
- `pagerank` = float stored as node attribute by `graph_builder._compute_metrics()`
- `in_degree_norm` = node's `in_degree` / max `in_degree` across all expanded nodes

### Pattern 4: graph_rag_retrieve — Orchestration

**What:** Calls the three steps in sequence and returns `(list[CodeNode], stats_dict)`.

```python
def graph_rag_retrieve(
    query: str,
    repo_path: str,
    G: nx.DiGraph,
    max_nodes: int = 10,
    hop_depth: int = 1,
) -> tuple[list[CodeNode], dict]:
    # Step 1: semantic search
    seed_results = semantic_search(query, repo_path, top_k=max_nodes)
    seed_scores = {node_id: score for node_id, score in seed_results}

    # Step 2: BFS expansion
    expanded = expand_via_graph(list(seed_scores.keys()), G, hop_depth)

    # Step 3: rerank
    nodes = rerank_and_assemble(expanded, seed_scores, G, max_nodes)

    stats = {
        "seed_count": len(seed_scores),
        "expanded_count": len(expanded),
        "returned_count": len(nodes),
        "hop_depth": hop_depth,
    }
    return nodes, stats
```

### Pattern 5: conftest.py additions (TEST-06)

```python
# Add to backend/tests/conftest.py

import numpy as np
import networkx as nx
from app.models.schemas import CodeNode

@pytest.fixture
def sample_graph() -> nx.DiGraph:
    """Small in-memory DiGraph with 5 nodes and known edge structure.

    Topology:
      A -> B (CALLS)   B -> C (CALLS)
      D -> B (CALLS)   E (isolated)

    PageRank and degrees pre-computed so reranking tests are deterministic.
    """
    G = nx.DiGraph()
    nodes = [
        {"node_id": "a.py::func_a", "name": "func_a", "type": "function",
         "file_path": "/repo/a.py", "line_start": 1, "line_end": 5,
         "signature": "def func_a():", "pagerank": 0.15, "in_degree": 0, "out_degree": 1},
        {"node_id": "b.py::func_b", "name": "func_b", "type": "function",
         "file_path": "/repo/b.py", "line_start": 1, "line_end": 5,
         "signature": "def func_b():", "pagerank": 0.25, "in_degree": 2, "out_degree": 1},
        {"node_id": "c.py::func_c", "name": "func_c", "type": "function",
         "file_path": "/repo/c.py", "line_start": 1, "line_end": 5,
         "signature": "def func_c():", "pagerank": 0.30, "in_degree": 1, "out_degree": 0},
        {"node_id": "d.py::func_d", "name": "func_d", "type": "function",
         "file_path": "/repo/d.py", "line_start": 1, "line_end": 5,
         "signature": "def func_d():", "pagerank": 0.15, "in_degree": 0, "out_degree": 1},
        {"node_id": "e.py::func_e", "name": "func_e", "type": "function",
         "file_path": "/repo/e.py", "line_start": 1, "line_end": 5,
         "signature": "def func_e():", "pagerank": 0.10, "in_degree": 0, "out_degree": 0},
    ]
    for n in nodes:
        node_id = n["node_id"]
        G.add_node(node_id, **n)
    G.add_edge("a.py::func_a", "b.py::func_b", type="CALLS")
    G.add_edge("b.py::func_b", "c.py::func_c", type="CALLS")
    G.add_edge("d.py::func_d", "b.py::func_b", type="CALLS")
    return G


@pytest.fixture
def mock_embedder(monkeypatch):
    """Deterministic mock for openai.OpenAI embeddings — no API key required.

    Uses np.random.seed(42) so each call returns reproducible 1536-d vectors.
    The fixture patches app.retrieval.graph_rag.OpenAI at the retrieval module
    namespace (from-import binding).
    """
    import numpy as np
    from unittest.mock import MagicMock

    np.random.seed(42)

    def _fake_create(model, input):
        response = MagicMock()
        response.data = [
            MagicMock(embedding=np.random.rand(1536).tolist(), index=i)
            for i in range(len(input))
        ]
        return response

    mock_client = MagicMock()
    mock_client.embeddings.create.side_effect = _fake_create

    mock_openai_cls = MagicMock(return_value=mock_client)
    monkeypatch.setattr("app.retrieval.graph_rag.OpenAI", mock_openai_cls)
    return mock_client
```

### Anti-Patterns to Avoid

- **Storing embeddings in the graph nodes:** The graph node attributes from `build_graph()` do NOT include embedding vectors — they store metadata only. Never try to read `G.nodes[node_id]["embedding"]`.
- **Reconstructing CodeNode from pgvector rows alone:** The `code_embeddings` table does not have `signature`, `docstring`, or `body_preview`. Always hydrate full CodeNodes from `G.nodes[node_id]`.
- **Running semantic_search in tests without patching:** `semantic_search` calls `get_db_connection()` and `OpenAI()`. Both must be patched for the no-DB test requirement.
- **Using `nx.bfs_tree()` for bidirectional expansion:** `bfs_tree` only follows outgoing edges on a DiGraph. It will miss callers (predecessors).
- **Dividing by max_in_degree without a guard:** If all expanded nodes have in_degree 0 (e.g., isolated nodes), max_in_degree is 0 → ZeroDivisionError.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Bidirectional BFS on DiGraph | Custom predecessor+successor queue | `nx.ego_graph(G, n, radius=k, undirected=True)` | Handles depth tracking, visited set, and bidirectionality in one call |
| Cosine similarity | numpy dot product loop | pgvector `<=>` operator with `ORDER BY … LIMIT k` | pgvector uses ivfflat index for O(log n) ANN search; brute force is O(n) |
| Graph node hydration | Re-query SQLite graph_store | Read directly from `G.nodes[node_id]` dict | Graph is already loaded in memory; attributes are the full CodeNode model_dump |

**Key insight:** The graph is the source of truth for all node metadata after ingestion. The pgvector store is only needed to find semantically similar nodes by vector distance; everything else comes from `G`.

---

## Common Pitfalls

### Pitfall 1: CodeNode fields not in code_embeddings table
**What goes wrong:** `semantic_search` returns pgvector rows, and the planner assumes you can construct a full `CodeNode` from them. But `code_embeddings` only has `(id, name, file_path, line_start, line_end)` — no signature, docstring, body_preview, complexity.
**Why it happens:** The embedder stores the minimum needed for vector search, not for display.
**How to avoid:** `semantic_search` should return `(node_id, score)` pairs. `graph_rag_retrieve` then looks up each `node_id` in `G.nodes` to get the full attributes before constructing `CodeNode` objects.
**Warning signs:** `CodeNode(...)` construction fails with missing required field errors.

### Pitfall 2: Seed node not in graph
**What goes wrong:** A node in pgvector has no matching entry in G (e.g., stale index after a file deletion without re-indexing). BFS on a non-existent node raises `NetworkXError`.
**Why it happens:** pgvector and SQLite graph stores are written independently in the pipeline; a partial failure can leave them out of sync.
**How to avoid:** Guard every `G.nodes[node_id]` access with `if node_id in G`. In `expand_via_graph`, skip seeds not in G with a warning.
**Warning signs:** `KeyError` or `NetworkXError: The node X is not in the digraph`.

### Pitfall 3: BFS returns nodes outside edge_types filter
**What goes wrong:** `edge_types=["CALLS"]` is requested but `nx.ego_graph` ignores edge attributes — it expands across ALL edges including IMPORTS edges.
**Why it happens:** `nx.ego_graph` does not support edge attribute filtering natively.
**How to avoid:** If `edge_types` is not None, create a filtered subgraph view first:
```python
if edge_types:
    G = nx.subgraph_view(G, filter_edge=lambda u, v: G[u][v].get("type") in edge_types)
```
`subgraph_view` is zero-copy (returns a view, not a copy).
**Warning signs:** BFS reaches nodes that should be unreachable given the edge type filter.

### Pitfall 4: Patching OpenAI at the wrong namespace in tests
**What goes wrong:** Patch targets `openai.OpenAI` globally, but the module already imported `from openai import OpenAI` at load time — the patch has no effect.
**Why it happens:** Python's from-import binds the name at module load; patching the source module afterwards doesn't affect already-bound names.
**How to avoid:** Always patch at the retrieval module's namespace: `monkeypatch.setattr("app.retrieval.graph_rag.OpenAI", ...)`. This is the same pattern used throughout the test suite (see test_pipeline.py and test_embedder.py).
**Warning signs:** Test calls the real OpenAI API and fails with authentication errors.

### Pitfall 5: get_db_connection called in semantic_search tests
**What goes wrong:** Even with OpenAI mocked, `semantic_search` still calls `get_db_connection()` which attempts to connect to PostgreSQL.
**Why it happens:** semantic_search has two external dependencies: OpenAI + pgvector.
**How to avoid:** Tests for `semantic_search` must patch BOTH `app.retrieval.graph_rag.OpenAI` AND `app.retrieval.graph_rag.get_db_connection`. The remaining functions (`expand_via_graph`, `rerank_and_assemble`) are pure NetworkX — no patching needed.
**Warning signs:** `psycopg2.OperationalError: could not connect to server` during test run.

---

## Code Examples

### BFS expansion — ego_graph bidirectional

```python
# Source: https://networkx.org/documentation/stable/_modules/networkx/generators/ego.html
import networkx as nx

G = nx.DiGraph()
G.add_edges_from([("A", "B"), ("B", "C"), ("D", "B")])

# Hop depth 1 from B — should get A, B, C, D (both callers and callees)
subgraph = nx.ego_graph(G, "B", radius=1, undirected=True)
print(set(subgraph.nodes()))
# {'A', 'B', 'C', 'D'}

# Hop depth 1 from A — should get A, B only (A has no predecessors; B is 1 hop out)
subgraph2 = nx.ego_graph(G, "A", radius=1, undirected=True)
print(set(subgraph2.nodes()))
# {'A', 'B'}
```

### pgvector cosine similarity query

```python
# Source: embedder.py pattern + pgvector <=> operator
# register_vector must be called per-connection (Phase 05 decision)
from pgvector.psycopg2 import register_vector

conn = get_db_connection()
register_vector(conn)
with conn.cursor() as cur:
    cur.execute(
        """
        SELECT id, 1 - (embedding <=> %s::vector) AS score
        FROM code_embeddings
        WHERE repo_path = %s
        ORDER BY embedding <=> %s::vector
        LIMIT %s
        """,
        (query_vec, repo_path, query_vec, top_k),
    )
    rows = cur.fetchall()
conn.close()
```

### In-memory graph fixture for tests (no DB required)

```python
# Pattern for test_graph_rag.py — tests are pure NetworkX, no DB connection
import networkx as nx

def test_bfs_hop_depth_1():
    G = nx.DiGraph()
    G.add_node("a.py::func_a", pagerank=0.1, in_degree=0, out_degree=1,
               name="func_a", type="function", file_path="/r/a.py",
               line_start=1, line_end=5, signature="def func_a():")
    G.add_node("b.py::func_b", pagerank=0.2, in_degree=1, out_degree=0,
               name="func_b", type="function", file_path="/r/b.py",
               line_start=1, line_end=5, signature="def func_b():")
    G.add_edge("a.py::func_a", "b.py::func_b", type="CALLS")

    from app.retrieval.graph_rag import expand_via_graph
    result = expand_via_graph(["a.py::func_a"], G, hop_depth=1)
    assert "b.py::func_b" in result   # downstream at hop 1
    assert "a.py::func_a" in result   # seed itself always included
```

### Reranking score calculation (exact formula)

```python
# RAG-03: verbatim formula
def _score(node_id, seed_scores, G, max_in_degree):
    attrs = G.nodes[node_id]
    semantic = seed_scores.get(node_id, 0.3)
    pagerank = attrs.get("pagerank", 0.0)
    in_degree_norm = attrs.get("in_degree", 0) / max(max_in_degree, 1)
    return semantic + (0.2 * pagerank) + (0.1 * in_degree_norm)
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Pure vector search (semantic only) | Graph-augmented retrieval (vector + BFS + rerank) | This phase | Surfaces structurally related code even when lexically dissimilar |
| Copy graphs for subgraph filtering | `nx.subgraph_view()` — zero-copy view | NetworkX 2.4+ | Memory-efficient edge filtering without copying |
| `lang.query()` on tree-sitter | `Query()` constructor | tree-sitter 0.25.x | Already handled in Phase 3; irrelevant for Phase 8 |

**Deprecated/outdated:**
- Storing full node data in pgvector: Not done in this project — pgvector stores only vectors + minimal metadata. Full node data lives in the graph. This is by design (EMBED-01 through EMBED-06).

---

## Open Questions

1. **`semantic_search` return type**
   - What we know: RAG-01 says "returns top_k CodeNodes" but `code_embeddings` doesn't have all CodeNode fields
   - What's unclear: Whether semantic_search should return partial nodes or `(node_id, score)` pairs
   - Recommendation: Return `list[tuple[str, float]]` (node_id, score) from `semantic_search`. Let `graph_rag_retrieve` hydrate full CodeNodes from G. This aligns with RAG-04 which passes G to the orchestrator. The RAG-01 requirement text "returns top_k CodeNodes" can be satisfied at the orchestrator level.

2. **`edge_types` parameter usage**
   - What we know: RAG-02 signature includes `edge_types` parameter
   - What's unclear: The phase success criteria don't mention edge type filtering in tests; it may be a passthrough parameter
   - Recommendation: Implement the filter but default to `None` (no filtering). Tests don't need to exercise it for phase completion.

3. **PageRank scale vs semantic score scale**
   - What we know: PageRank values from `nx.pagerank()` sum to 1.0 across all nodes; for a 5-node graph each is ~0.2. Semantic similarity is also in [0, 1].
   - What's unclear: For very large graphs, PageRank per-node is tiny (e.g., 0.001 for 1000 nodes), reducing the PageRank term's influence
   - Recommendation: Use formula exactly as specified in RAG-03. Do not normalise PageRank separately — V1 scope, consistent with requirements.

---

## Sources

### Primary (HIGH confidence)
- https://networkx.org/documentation/stable/_modules/networkx/generators/ego.html — ego_graph `undirected=True` implementation confirmed
- https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.traversal.breadth_first_search.bfs_predecessors.html — depth_limit parameter confirmed
- Existing codebase: `backend/app/ingestion/graph_builder.py` — confirms pagerank/in_degree stored as node attrs
- Existing codebase: `backend/app/ingestion/embedder.py` — confirms code_embeddings schema and pgvector connection pattern
- Existing codebase: `backend/app/models/schemas.py` — CodeNode field list
- Existing codebase: `backend/tests/conftest.py` — existing fixture patterns
- Existing codebase: `backend/tests/test_pipeline.py` — mock patching namespace pattern

### Secondary (MEDIUM confidence)
- https://www.pgvector.co docs (via embedder.py code review) — `<=>` cosine distance operator, `1 - (embedding <=> vec)` for similarity score

### Tertiary (LOW confidence)
- None — all critical claims verified against codebase or official NetworkX docs

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already used in the project; no new dependencies
- Architecture: HIGH — functions, file locations, and module namespace follow established project patterns
- BFS pattern: HIGH — verified against official NetworkX docs; ego_graph undirected=True confirmed
- Reranking formula: HIGH — taken verbatim from REQUIREMENTS.md RAG-03
- Pitfalls: HIGH — derived from actual project decisions in STATE.md (namespace patching, per-connection register_vector, from-import binding)
- Test patterns: HIGH — directly derived from existing conftest.py and test_pipeline.py patterns

**Research date:** 2026-03-19
**Valid until:** 2026-04-18 (NetworkX API is stable; 30-day validity appropriate)
