# Retrieval — Graph RAG v2

Six-step pipeline combining **semantic similarity**, **keyword search**, **rank fusion**, **call-graph expansion**, and **MMR diversity** to retrieve the most relevant code context for a query.

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

  ▼ 6. MMR Diversity Selection
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

## Eval Results (Run B, 2026-04-03, 30Q, qwen2.5:7b)

| Metric | Naive (v1) | Graph RAG v1 | Graph RAG v2 | Δ vs v1 |
|---|---|---|---|---|
| Faithfulness | 0.364 | — | 0.539 | **+48%** |
| Answer Relevancy | 0.250 | — | 0.412 | **+65%** |
| Context Precision | 0.118 | — | 0.253 | **+115%** |

See [eval/README.md](../../../../eval/README.md) for full three-way comparison including the v1 Graph RAG baseline.

## Parameters

| Param | Default | Notes |
|---|---|---|
| `max_nodes` | 10 | Result cap (LLM context window is the bottleneck) |
| `hop_depth` | 1 | Retained for call-site compatibility; ignored internally — always depth-1 |
| `top_k` | 10 | Seed count for both semantic and FTS searches |

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
