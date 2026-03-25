# Graph RAG Retrieval

Graph RAG (Retrieval-Augmented Generation) orchestrates a three-step pipeline to retrieve the most relevant code context for a natural language query. It combines semantic similarity (pgvector embeddings) with structural knowledge (call graph traversal) to produce grounded, citation-backed results.

## Architecture Overview

```
User Query
    ↓
Step 1: Semantic Search
    • Embed query with the same provider (Mistral/OpenAI) used for code
    • Cosine similarity search in pgvector (top-k=10)
    • Return: [(node_id, cosine_score), ...]
    ↓
Step 2: Graph Expansion (BFS)
    • Starting from seed nodes (top-k), traverse call/import graph
    • Breadth-first search, both directions (ego_graph undirected=True)
    • Hop depth configurable (default 1, max recommended 3)
    • Return: set of expanded node_ids
    ↓
Step 3: Reranking & Assembly
    • Score each expanded node using the exact RAG-03 formula
    • sort by score descending, take top max_nodes
    • Reconstruct full CodeNode objects from graph attributes
    • Return: [CodeNode, CodeNode, ...]
```

## Public API

```python
def graph_rag_retrieve(
    query: str,
    repo_path: str,
    G: nx.DiGraph,
    max_nodes: int = 10,
    hop_depth: int = 1,
) -> tuple[list[CodeNode], dict]:
    """
    Retrieve and rank code nodes for a natural language query.

    Args:
        query: Natural language question
        repo_path: Repository identifier (used to scope pgvector search)
        G: The code call/import DiGraph (with full node attributes)
        max_nodes: Max results to return (default 10)
        hop_depth: BFS traversal depth (default 1)

    Returns:
        Tuple of:
          - list[CodeNode]: top max_nodes CodeNode objects
          - dict: stats with seed_count, expanded_count, returned_count, hop_depth
    """
```

---

## Step 1: Semantic Search

**Function:**
```python
def semantic_search(query: str, repo_path: str, top_k: int) -> list[tuple[str, float]]:
    """
    Embed query and return top_k nearest neighbors from pgvector.

    Returns:
        [(node_id, cosine_similarity_score), ...] sorted descending by score
    """
```

**Algorithm:**

1. **Embed query:**
   ```python
   query_vec = get_embedding_client().embed([query])[0]  # e.g., 1536-dim for OpenAI
   ```

2. **pgvector cosine search:**
   ```sql
   SELECT id, 1 - (embedding <=> %s::vector) AS score
   FROM code_embeddings
   WHERE repo_path = %s
   ORDER BY embedding <=> %s::vector
   LIMIT %s
   ```

   - `<=>` is pgvector's distance operator (L2 in this case)
   - `1 - distance` converts to similarity score in [0, 1]
   - Only searches embeddings for the current repo_path

3. **Return ordered pairs:**
   ```
   [
       ("backend/app/agent/router.py::route", 0.82),
       ("backend/app/agent/critic.py::critique", 0.78),
       ("backend/app/agent/debugger.py::debug", 0.75),
       ...
   ]
   ```

**Characteristics:**
- Fast: pgvector IVFFlat index scales to 100k+ nodes, <50ms queries
- Approximate: IVFFlat may miss some neighbors (tunable via `lists=100` in index)
- Dimension-dependent: Mistral=1024, OpenAI=1536 (requires re-index on provider switch)

**Example:**
```python
# User asks: "How does the router detect intent?"
query = "How does the router detect intent?"
seed_results = semantic_search(query, "/path/to/repo", top_k=10)
# [("router.py::route", 0.85), ("router.py::CONFIDENCE_THRESHOLD", 0.71), ...]
```

---

## Step 2: Graph Expansion (BFS)

**Function:**
```python
def expand_via_graph(
    seed_node_ids: list[str],
    G: nx.DiGraph,
    hop_depth: int,
    edge_types: list[str] | None = None,
) -> set[str]:
    """
    Expand seed nodes via BFS in both directions.

    Args:
        seed_node_ids: Starting nodes from semantic search
        G: The code call/import DiGraph
        hop_depth: Traversal radius (inclusive)
        edge_types: Optional filter (e.g., ["CALLS"] to ignore IMPORTS)

    Returns:
        Set of all reachable node_ids within hop_depth
    """
```

**Algorithm:**

1. **Filter graph (optional):**
   ```python
   if edge_types is not None:
       G_work = nx.subgraph_view(
           G,
           filter_edge=lambda u, v: G[u][v].get("type") in edge_types,
       )
   else:
       G_work = G
   ```

   - Zero-copy filtered view (no copying full graph)
   - Useful for separating call/import traversal

2. **BFS expansion per seed:**
   ```python
   for node_id in seed_node_ids:
       subgraph = nx.ego_graph(G_work, node_id, radius=hop_depth, undirected=True)
       expanded.update(subgraph.nodes())
   ```

   - `ego_graph(undirected=True)` treats all edges as bidirectional
   - Captures both callers (predecessors) and callees (successors)
   - `radius=hop_depth` includes the starting node itself (depth 0)

3. **Return deduplicated set:**
   ```python
   return expanded  # set[str] of all reachable node_ids
   ```

**Why `undirected=True`?**

In a directed call graph:
- Outgoing edges (`A → B`) represent "A calls B" (forward)
- Incoming edges (`B ← A`) represent "A calls B" (backward, i.e., A is a caller of B)

For comprehensive context, we need both:
- Callees (functions that this node calls)
- Callers (functions that call this node)

`ego_graph(undirected=True)` converts to undirected internally, so BFS follows both directions.

**Depth Examples:**

- **hop_depth=0:** Just the seed nodes themselves
- **hop_depth=1:** Seeds + direct callers/callees (most common)
- **hop_depth=2:** Up to 2 hops away (wider context, may include noise)

**Example:**
```python
seed_ids = ["router.py::route", "router.py::_route_by_intent"]
expanded = expand_via_graph(seed_ids, G, hop_depth=1)
# Now includes:
#   "orchestrator.py::_router_node" (caller of route)
#   "model_factory.py::get_llm" (callee of route)
#   "router.py::CONFIDENCE_THRESHOLD" (import from route)
#   ... all 1-hop neighbors
```

---

## Step 3: Reranking & Assembly

**Function:**
```python
def rerank_and_assemble(
    expanded_node_ids: set[str],
    seed_scores: dict[str, float],
    G: nx.DiGraph,
    max_nodes: int,
) -> list[CodeNode]:
    """
    Score expanded nodes and return top max_nodes.

    Args:
        expanded_node_ids: Set from expand_via_graph
        seed_scores: Dict mapping node_id -> cosine_score from semantic search
        G: The DiGraph with full node attributes
        max_nodes: Max results to return

    Returns:
        Top max_nodes CodeNode objects sorted by descending score
    """
```

**Reranking Formula (RAG-03):**

For each expanded node:
```
score = semantic_component + pagerank_component + degree_component

where:
  semantic_component = seed_scores.get(node_id, 0.3)
                       # 0.3 fallback for non-seed nodes

  pagerank_component = 0.2 * G.nodes[node_id]["pagerank"]
                       # 0.2 weight × normalized pagerank

  degree_component = 0.1 * (G.nodes[node_id]["in_degree"] / max_in_degree)
                     # 0.1 weight × normalized in-degree
```

**Normalization:**
```python
# in_degree normalization
in_degrees = [G.nodes[n].get("in_degree", 0) for n in expanded_node_ids if n in G]
max_in_degree = (max(in_degrees) if in_degrees else 0) or 1
# or 1: ensures zero-division guard when all in-degrees are 0
```

**Weighting Rationale:**
- **0.4 semantic:** Direct relevance to the query dominates
- **0.2 pagerank:** Central functions in the codebase are useful context
- **0.1 in_degree:** Well-called functions are important but lower priority than the above

(Note: These are not the Critic weights, which are different: 0.4G + 0.35R + 0.25A)

**CodeNode Assembly:**
```python
for node_id in expanded_node_ids:
    attrs = G.nodes[node_id]
    node = CodeNode(**{k: v for k, v in attrs.items() if k in CodeNode.model_fields})
    scored.append((score, node))

scored.sort(key=lambda x: x[0], reverse=True)
return [node for _, node in scored[:max_nodes]]
```

**Key Design:**
- CodeNode is reconstructed from graph attributes (which is the full `model_dump()` from ingestion)
- Only fields in `CodeNode.model_fields` are copied (safety against extra attributes)
- Score clamping ensures stable comparisons

**Example:**
```python
expanded = {"router.py::route", "critic.py::critique", "model_factory.py::get_llm", ...}
seed_scores = {
    "router.py::route": 0.85,
    "critic.py::critique": 0.71,
}

# Scoring:
#   router.py::route: 0.85 + (0.2 × 0.0045) + (0.1 × 0.67) = 0.854
#   critic.py::critique: 0.71 + (0.2 × 0.0032) + (0.1 × 0.72) = 0.793
#   model_factory.py::get_llm: 0.30 + (0.2 × 0.0028) + (0.1 × 0.45) = 0.346

# Top 10 by score descending
```

---

## End-to-End Example

**User Query:**
```
"How does the router detect intent?"
```

**Step 1 — Semantic Search:**
```
Embedded query vector (1536 dims) → pgvector cosine search
Results:
  ("backend/app/agent/router.py::route", 0.85)
  ("backend/app/agent/router.py::CONFIDENCE_THRESHOLD", 0.71)
  ("backend/app/agent/router.py::ROUTER_SYSTEM", 0.68)
  ("backend/app/agent/router.py::ROUTER_PROMPT", 0.65)
  ("backend/app/agent/orchestrator.py::_router_node", 0.63)
  ... (5 more)
```

**Step 2 — Graph Expansion (hop_depth=1):**
```
Seeds: [route, CONFIDENCE_THRESHOLD, ROUTER_SYSTEM, ROUTER_PROMPT, _router_node]

BFS from each seed (undirected):
  route (node):
    ← calls from: orchestrator.py::_router_node, orchestrator.py::build_graph
    → calls to: model_factory.py::get_llm, orchestrator.py::_router_node
    ← imports: router.py::IntentResult, router.py::ChatPromptTemplate

  _router_node (node):
    → calls to: route
    ← calls from: orchestrator.py::build_graph

  CONFIDENCE_THRESHOLD (not a function, no outgoing)

  ... (and so on for all seeds)

Expanded set (all within 1 hop):
  {route, CONFIDENCE_THRESHOLD, ROUTER_SYSTEM, ROUTER_PROMPT, _router_node,
   model_factory.py::get_llm, orchestrator.py::build_graph, IntentResult, ...}

Total expanded: ~45 nodes
```

**Step 3 — Reranking (max_nodes=10):**
```
Scoring (formula: semantic + 0.2*pagerank + 0.1*in_degree_norm):
  route: 0.85 + 0.0009 + 0.0667 = 0.9176 ← top
  _router_node: 0.63 + 0.0008 + 0.0556 = 0.6864
  get_llm: 0.30 + 0.0012 + 0.1333 = 0.4345
  IntentResult: 0.30 + 0.0005 + 0.0833 = 0.3838
  ... (and 6 more)

Top 10 CodeNode objects returned:
  [
    CodeNode(node_id="route", name="route", type="function", ...),
    CodeNode(node_id="_router_node", name="_router_node", type="function", ...),
    ...
  ]

Stats returned:
  {
    "seed_count": 10,
    "expanded_count": 45,
    "returned_count": 10,
    "hop_depth": 1,
  }
```

---

## Configuration & Tuning

**QueryRequest Parameters:**
```python
class QueryRequest(BaseModel):
    question: str                    # Natural language query
    repo_path: str                   # Repo identifier for scoping
    max_nodes: int = 10              # Max results (default 10)
    hop_depth: int = 1               # BFS depth (default 1, max 3 recommended)
```

**Tuning Recommendations:**

| Parameter | Default | Tuning | Notes |
|-----------|---------|--------|-------|
| `max_nodes` | 10 | Increase for broader context | LLM context size is the bottleneck |
| `hop_depth` | 1 | Increase for deep call stacks | 2+ hops may include noisy nodes |
| pgvector `lists` | 100 | Decrease for speed, increase for accuracy | Higher = more accurate, slower |

---

## Performance Characteristics

| Operation | Time (100k node repo) |
|-----------|----------------------|
| Semantic search (pgvector) | ~50–100ms |
| BFS expansion (hop_depth=1) | ~10–20ms |
| Reranking + assembly | ~5–10ms |
| **Total retrieval** | **~65–130ms** |

**Scaling:**
- pgvector: IVFFlat index scales linearly to 1M+ nodes
- BFS: Scales as O(edges_in_expanded_set), typical ~100 edges per node × 10 nodes = 1000 edges traversed
- Reranking: O(expanded_count) = O(hop_depth × avg_degree)

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| pgvector search returns 0 results | Empty seed list → empty expansion → empty results |
| Seed node not in graph | BFS skips it (warning logged), continues with others |
| Graph has disconnected components | BFS only reaches reachable nodes |
| All expanded nodes have in_degree=0 | max_in_degree defaults to 1 (guard) |

---

## Comparison: Graph RAG vs. Naive Vector-Only Retrieval

**Naive Vector Search:**
```
query → embed → pgvector search → top-k nodes → return
```
- Fast (~50ms)
- May return isolated, similar nodes without context
- No structural understanding of call flows

**Graph RAG (this module):**
```
query → embed → pgvector search → BFS expansion → rerank → return
```
- Slightly slower (~65–130ms)
- Returns contextually related code (callers, callees)
- Structures results by importance (PageRank, degree)
- More useful for understanding function interactions

**When to use each:**
- Naive: Quick single-function lookups, simple questions
- Graph RAG: Multi-function interactions, understanding flows, debugging

Nexus uses Graph RAG by default (V1 path in `/query`).

---

## Testing

All components are unit-tested with mock graphs:

| Test File | Coverage |
|-----------|----------|
| `test_graph_rag.py` | semantic_search, expand_via_graph, reranking, formula validation |

Key test cases:
- Semantic search returns top-k ordered by score
- BFS expansion respects hop_depth
- Reranking formula weights are applied correctly
- Non-seed nodes get 0.3 fallback score
- in_degree normalization guards against zero-division

Run tests:
```bash
python -m pytest backend/tests/test_graph_rag.py -v
```

---

## Future Work (Phase 27+)

- [ ] Support multiple edge type filtering (e.g., "CALLS only" vs. "IMPORTS only")
- [ ] Hybrid ranking: combine BM25 (FTS5) with semantic similarity
- [ ] Dynamic hop_depth based on query intent (e.g., debug→4, explain→1)
- [ ] Approximate PageRank (incremental, not full recompute)
- [ ] Caching for frequently-accessed subgraphs
