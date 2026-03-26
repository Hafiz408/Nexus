# Retrieval — Graph RAG

Three-step pipeline that combines **semantic similarity** with **structural graph traversal** to retrieve the most relevant code context for a query.

## Pipeline

```
Query
  │
  ▼ 1. Semantic Search
  Embed query → sqlite-vec cosine similarity → top-k seed nodes

  ▼ 2. BFS Expansion
  ego_graph (undirected) from each seed → callers + callees within hop_depth

  ▼ 3. Rerank & Assemble
  score = semantic_score
        + 0.2 × PageRank
        + 0.1 × in_degree_norm
  → top max_nodes CodeNode objects returned
```

## Why Graph Expansion?

Pure semantic search returns isolated nodes. BFS adds calling context — the functions that call and are called by your seed nodes. This surfaces relevant code that doesn't match the query semantically but is structurally connected.

Eval result: **+13% composite RAGAS score** vs. vector-only retrieval, with largest gains in context precision (+0.14) and recall (+0.17). See [eval/README.md](../../../../eval/README.md).

## Parameters

| Param | Default | Notes |
|---|---|---|
| `max_nodes` | 10 | Result cap (LLM context window is the bottleneck) |
| `hop_depth` | 1 | BFS radius — 2+ hops adds noise for most queries |
| `top_k` | 10 | Seed count from sqlite-vec |

Non-seed nodes (added by BFS) receive a fallback semantic score of **0.3** so they can still rank highly via PageRank/degree.
