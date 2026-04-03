# Retrieval — Graph RAG v2 + Cross-Encoder

Seven-step pipeline combining **semantic similarity**, **keyword search**, **rank fusion**, **call-graph expansion**, **MMR diversity**, and **cross-encoder reranking** to retrieve the most relevant code context for a query.

## Pipeline

```
Query
  │
  ▼ 1. Semantic Search
  Embed query → sqlite-vec cosine NN → top-k (node_id, score) pairs

  ▼ 2. FTS5 Keyword Search
  Tokenise query → strip stopwords → BM25 on name + embedding_text → top-5
  Scores capped at 0.85 (perfect semantic match = 1.0 always wins)

  ▼ 3. RRF Merge
  Reciprocal Rank Fusion across both lists: score = Σ 1/(60 + rank + 1)
  Rank-based → immune to cosine vs BM25 scale differences

  ▼ 4. CALLS Depth-1 Expansion  (semantic seeds only)
  For each semantic seed, fetch direct callers + callees via CALLS edges
  IMPORTS edges excluded — prevents cross-file pollution
  Neighbor score = max(parent_rrf_score) × 0.6 decay
  Per-seed cap: 5 callers + 5 callees, ordered by pagerank desc

  ▼ 5. Combine Candidate Pool
  Merge neighbor scores + RRF scores; seeds overwrite neighbors on overlap
  Test-file penalty: ×0.5 for any node whose file path contains "test"/"spec"
  Sort descending → scored list (score, CodeNode)

  ▼ 6. Cross-Encoder Rerank  (use_cross_encoder=True, default on)
  ms-marco-MiniLM-L-6-v2 jointly reads (query, node_context) for top 2×max_nodes
  Relevance score via joint attention — more accurate than bi-encoder cosine
  Re-sorted descending; falls back to score order silently if model raises

  ▼ 7. MMR Diversity Selection
  Iteratively pick the node with highest (score − 0.35 × same-file-count)
  Prevents one class's methods from monopolising the result set
  → top max_nodes CodeNode objects returned
```

## Why RRF Instead of max()?

`max(semantic, fts)` merging requires scores to be on the same scale.
Cosine similarity lives in [0, 1]; BM25 scores are negative and unbounded.
RRF uses only rank position, so a node that ranks highly in both lists
scores higher than one that tops only one — without any normalisation.

## Why CALLS-Only Expansion?

BFS over undirected `ego_graph` adds any edge type, including IMPORTS.
IMPORTS edges connect a file's `__module__` node to every imported symbol —
expanding through them pulls in unrelated dependencies. CALLS-only
expansion stays within the functional call chain, adding callers and callees
that are directly relevant to how the seed node is used.

## Why MMR?

Score-based ranking can cluster the final set. If `AuthService` has high
pagerank, its `login`, `logout`, and `refresh_token` methods may all
outscore nodes from other files. MMR subtracts `0.35 × same-file-count`
from the adjusted score, so the third node from the same file needs a
`0.70` score advantage to be selected over a fresh-file node.

## Why Cross-Encoder?

Bi-encoder similarity (embedding cosine) encodes query and document
independently. The vectors cannot interact — a query about "how is
a dependency resolved at runtime" may score equally against superficially
similar-looking nodes regardless of whether they actually implement
runtime resolution.

A cross-encoder reads the full `(query, node_context)` string jointly.
Tokens from the query and the code can attend to each other at every layer,
so the model can distinguish "validates a JWT at request time" from
"creates a JWT on login" even when both contain the same keywords.

The trade-off is speed: bi-encoder ANN search over the full index is O(log N);
cross-encoder scoring is O(candidates). Running CE over the top `2×max_nodes`
pool (≈20–30 nodes) costs ~100ms on CPU and is applied after the cheap
RRF+MMR pass has already filtered to high-signal candidates.

## Eval Results (Runs B + C, 2026-04-03/04, 30Q, qwen2.5:7b)

| Metric | Naive Vector | Graph RAG v2 | Graph RAG v2 + CE | Δ v2→v2+CE |
|---|---|---|---|---|
| Faithfulness | 0.3148 | 0.5389 | 0.5417 | +0.5% |
| Answer Relevancy | 0.2133 | 0.4121 | 0.4827 | **+17.1%** |
| Context Precision | 0.1585 | 0.2532 | 0.3706 | **+46.4%** |

**v2+CE vs Naive:** +72% faithfulness · +126% answer relevancy · +134% context precision

See [eval/README.md](../../../../eval/README.md) for the full run history including v1 and HyDE+CE baselines.

## Parameters

| Param | Default | Notes |
|---|---|---|
| `max_nodes` | 10 | Result cap (LLM context window is the bottleneck) |
| `hop_depth` | 1 | Retained for call-site compatibility; ignored internally — always depth-1 |
| `top_k` | 10 | Seed count for both semantic and FTS searches |
| `use_cross_encoder` | `True` | Pass `False` to skip CE and return MMR-ordered nodes (e.g. for benchmarking) |

## Stats Dictionary

`graph_rag_retrieve` returns a stats dict alongside the nodes:

| Key | Description |
|---|---|
| `seed_count` | Total unique seeds after RRF merge (semantic ∪ FTS) |
| `semantic_seeds` | Seeds from vector search |
| `fts_seeds` | Seeds from FTS5 keyword search |
| `fts_new` | FTS seeds not already in the semantic set |
| `neighbor_count` | Nodes added by CALLS depth-1 expansion |
| `candidate_pool` | Total candidates before MMR selection |
| `returned_count` | Final nodes returned (≤ max_nodes) |
| `cross_encoder_used` | `True` if CE ran successfully; `False` if disabled or fell back |
