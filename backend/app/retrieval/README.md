# Retrieval — Graph RAG

Three-step pipeline that combines **semantic similarity** with **structural graph traversal** to retrieve the most relevant code context for a query.

## Pipeline

```
Query
  │
  ▼ 1. Dual Search (semantic + FTS5)
  a) Embed query → sqlite-vec cosine similarity → top-k semantic seeds
  b) FTS5 BM25 keyword search on name + embedding_text → top-k keyword seeds
  Merge: per-node score = max(semantic_score, fts_score)

  ▼ 2. BFS Expansion
  ego_graph (undirected) from each seed → callers + callees within hop_depth
  Optional edge_types filter (e.g. CALLS-only) via zero-copy subgraph view

  ▼ 3. Rerank & Assemble
  score = semantic_score
        + 0.2 × PageRank
        + 0.1 × in_degree_norm
  → top max_nodes CodeNode objects returned
```

## Why Dual Search?

Semantic search finds conceptually similar nodes. FTS5 keyword search catches exact symbol names and identifiers that vector similarity may score poorly (e.g. the user types a precise function name). Merging both pools with `max(score)` per node improves recall without duplicating entries.

FTS5 scores are capped at 0.85 so exact keyword matches rank below perfect semantic matches (score 1.0), preserving the natural ordering.

## Why Graph Expansion?

Pure search returns isolated nodes. BFS adds calling context — the functions that call and are called by your seed nodes. This surfaces relevant code that doesn't match the query but is structurally connected.

Eval result: **+13% composite RAGAS score** vs. vector-only retrieval, with largest gains in context precision (+0.14) and recall (+0.17). See [eval/README.md](../../../../eval/README.md).

## Parameters

| Param | Default | Notes |
|---|---|---|
| `max_nodes` | 10 | Result cap (LLM context window is the bottleneck) |
| `hop_depth` | 1 | BFS radius — 2+ hops adds noise for most queries |
| `top_k` | 10 | Seed count for both semantic and FTS searches |

Non-seed nodes (added by BFS) receive a fallback semantic score of **0.3** so they can still rank highly via PageRank/degree.

## Stats Dictionary

`graph_rag_retrieve` returns a stats dict alongside the nodes:

| Key | Description |
|---|---|
| `seed_count` | Total unique seeds after merging semantic + FTS |
| `semantic_seeds` | Seeds from vector search |
| `fts_seeds` | Seeds from FTS5 keyword search |
| `expanded_count` | Nodes after BFS expansion |
| `returned_count` | Final nodes returned (≤ max_nodes) |
| `hop_depth` | BFS depth used |
