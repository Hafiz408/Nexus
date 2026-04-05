# Retrieval — Graph RAG v3.1

Eight-step pipeline combining **semantic similarity**, **keyword search**, **rank fusion**, **Personalized PageRank graph expansion**, **cross-encoder reranking**, **hybrid CE floor**, **full-body expansion**, and **MMR diversity** to retrieve the most relevant code context for a query.

## Pipeline

```
Query
  │
  ▼ 1. Semantic Search  (cosine floor: min_similarity=0.15)
  Embed query → sqlite-vec cosine NN → top-k (node_id, score) pairs
  Results with cosine score < 0.15 filtered out before entering pool

  ▼ 2. FTS5 Keyword Search
  Tokenise query → strip stopwords → BM25 on name + embedding_text → top-5
  Scores capped at 0.85 (perfect semantic match = 1.0 always wins)

  ▼ 3. RRF Merge
  Reciprocal Rank Fusion across both lists: score = Σ 1/(60 + rank + 1)
  Rank-based → immune to cosine vs BM25 scale differences

  ▼ 4. Personalized PageRank Expansion  (from semantic seeds)
  PPR seeded proportionally from RRF scores; traverses CALLS + CLASS_CONTAINS edges
  IMPORTS excluded — prevents cross-file pollution
  Returns top-30 non-seed neighbors by PPR score
  Source: HippoRAG (NeurIPS 2024)

  ▼ 5. Combine Candidate Pool
  Merge neighbor scores + RRF scores; seeds overwrite neighbors on overlap
  Test-file penalty: ×0.5 for any node whose file path contains "test"/"spec"
  Sort descending → scored list (score, CodeNode)

  ▼ 6. Cross-Encoder Rerank  (use_cross_encoder=True, default on)
  ms-marco-MiniLM-L-6-v2 jointly reads (query, node_context) for top 2×max_nodes
  Relevance score via joint attention — more accurate than bi-encoder cosine
  Re-sorted descending; falls back to score order silently if model raises

  ▼ 7. Hybrid CE Floor
  Always keep top-3 candidates regardless of score
  Drop remaining candidates with CE score > 4.0 logit-units below the best
  Prevents zero-context responses on abstract queries while filtering noise
  Source: FILCO

  ▼ 8. Full-Body Expansion + MMR Selection
  Top-5 CE-ranked nodes: read full source (line_start → line_end) from disk
  Falls back to body_preview silently if file unreadable
  MMR: iteratively pick node with highest (score − 0.35 × same-file-count)
  → top max_nodes CodeNode objects returned
  Source: cAST 2025 (full syntactic units +5.5pts on RepoEval)
```

## Why Personalized PageRank Instead of BFS?

BFS depth-1 expansion treats all neighbors equally — a high-pagerank utility
node (`logger`, `config`) gets the same weight as a directly relevant callee.
PPR seeds the random walk proportionally from each seed's RRF score, so
neighbors of highly-relevant seeds receive more walk probability than neighbors
of tangential seeds. The result is a relevance-weighted neighborhood rather
than a flat set of callers/callees.

## Why CLASS_CONTAINS Edges?

Previously the graph only had CALLS and IMPORTS edges. Class methods could
only be reached by traversing CALLS from other callers. CLASS_CONTAINS edges
(class → method) let PPR walk from a class node directly into its methods —
critical for queries like "what methods does OAuth2PasswordBearer have?" where
the class node is a strong semantic seed but its methods have low individual
pagerank.

## Why the Hybrid CE Floor?

A hard `ce_score > 0` floor drops ~50% of candidates (FILCO result) but causes
zero-context responses on abstract/architectural queries where no candidate
scores above 0. The hybrid rule always keeps the top-3 and uses a logit-gap
threshold (4.0 units) for the rest — preserving the noise-reduction benefit
without starving abstract queries.

## Why RRF, MMR, and Cross-Encoder?

- **RRF over max():** cosine and BM25 scores have different scales; rank fusion is scale-invariant.
- **Cross-encoder:** bi-encoder vectors can't attend across query+document; CE joint attention distinguishes "validates JWT at request time" from "creates JWT on login."
- **MMR:** prevents one class's methods from monopolising results (e.g. all top-10 from `APIRouter`).

## Eval Results (2026-04-03 to 2026-04-05, 30Q, qwen2.5:7b judge)

| Metric | Naive Vector | v2+CE | **v3.1** | Δ v2+CE→v3.1 |
|---|---|---|---|---|
| Faithfulness | 0.3148 | 0.5417 | **0.9133** | **+68.6%** |
| Answer Relevancy | 0.2133 | 0.4827 | **0.7742** | **+60.4%** |
| Context Precision | 0.1585 | 0.3706 | **0.6685** | **+80.4%** |

**v3.1 vs Naive:** +190% faithfulness · +263% answer relevancy · +322% context precision

See [eval/README.md](../../../../eval/README.md) for the full run history.

## Parameters

| Param | Default | Notes |
|---|---|---|
| `max_nodes` | 10 | Result cap (LLM context window is the bottleneck) |
| `top_k` | 10 | Seed count for both semantic and FTS searches |
| `min_similarity` | 0.15 | Cosine floor for semantic seeds |
| `use_cross_encoder` | `True` | Pass `False` to skip CE and return MMR-ordered nodes |

## Stats Dictionary

`graph_rag_retrieve` returns a stats dict alongside the nodes:

| Key | Description |
|---|---|
| `seed_count` | Total unique seeds after RRF merge (semantic ∪ FTS) |
| `semantic_seeds` | Seeds from vector search |
| `fts_seeds` | Seeds from FTS5 keyword search |
| `fts_new` | FTS seeds not already in the semantic set |
| `neighbor_count` | Nodes added by PPR expansion |
| `candidate_pool` | Total candidates before CE rerank |
| `returned_count` | Final nodes returned (≤ max_nodes) |
| `cross_encoder_used` | `True` if CE ran successfully; `False` if disabled or fell back |
| `ce_floor_dropped` | Candidates dropped by the hybrid CE floor |
| `full_body_expanded` | Nodes whose full source body was read from disk |
