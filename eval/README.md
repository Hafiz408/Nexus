# Evaluation

RAGAS-based suite measuring retrieval quality across pipeline generations.
Judge: **Ollama qwen2.5:7b** (chat) + **nomic-embed-text** (embeddings).
Corpus: **fastapi** repo — 5,006 nodes, 29,579 edges.
Golden set: **`golden_qa_v2.json`** — 30 hand-labelled code-navigation Q&A pairs.

---

## Retrieval Pipelines

| Name | Key characteristics |
|---|---|
| **Naive Vector** | `semantic_search` only — cosine NN, top-15, no FTS, no graph |
| **Graph RAG v1** | FTS + BFS via CALLS+IMPORTS edges (ego_graph) + dual-score reranking (`0.7×semantic + 0.3×pagerank`) + MMR |
| **HyDE + CrossEncoder** | HyDE query expansion (1 LLM call) + RRF merge + BFS-threshold + cross-encoder reranker — eval-only, never production |
| **Graph RAG v2** | FTS + RRF merge + CALLS-only depth-1 expansion + propagated score (`parent_rrf × 0.6`) + MMR — current production |

---

## Results

### Run A — Three-Way Baseline
**Script:** `run_ragas_three_way.py` · **Date:** 2026-04-03 · **File:** `ragas_three_way_20260403_183816.json`

| Pipeline | Faithfulness | Answer Relevancy | Context Precision |
|---|---|---|---|
| Naive Vector | 0.3148 | 0.2133 | 0.1585 |
| Graph RAG v1 | 0.3636 | 0.2500 | 0.1176 |
| HyDE + CrossEncoder | 0.3571 | 0.2119 | 0.1764 |

Graph RAG v1 gains faithfulness (+15%) and answer relevancy (+17%) over naive but loses context precision (−26%). HyDE+CrossEncoder recovers context precision (+11% vs naive) at the cost of answer relevancy.

---

### Run B — Redesign
**Script:** `run_ragas_redesign.py` · **Date:** 2026-04-03 · **File:** `ragas_redesign_20260403_214931.json`
*(Naive baseline carried from Run A — same corpus, same golden set, same judge config)*

| Pipeline | Faithfulness | Answer Relevancy | Context Precision |
|---|---|---|---|
| Naive Vector *(Run A)* | 0.3148 | 0.2133 | 0.1585 |
| Graph RAG v1 *(Run A)* | 0.3636 | 0.2500 | 0.1176 |
| HyDE + CrossEncoder *(Run A)* | 0.3571 | 0.2119 | 0.1764 |
| **Graph RAG v2** | **0.5389** | **0.4121** | **0.2532** |

**vs Naive Vector:** +71% faithfulness · +93% answer relevancy · +60% context precision  
**vs Graph RAG v1:** +48% faithfulness · +65% answer relevancy · **+115%** context precision

Graph RAG v2 is the first pipeline to improve all three metrics simultaneously against every prior baseline.

---

## What drove the improvement (v1 → v2)

1. **Propagated score replaced the 0.0 semantic fallback** — Graph RAG v1 scored all BFS-expanded non-seed nodes at `0.3 × (0.2×pagerank + 0.1×in_degree)`, making score independent of query relevance. v2 sets `neighbor_score = parent_rrf_score × 0.6`, anchoring each neighbor's competitiveness to how relevant its parent seed was.

2. **CALLS-only expansion (IMPORTS removed)** — IMPORTS edges created cross-file pollution (e.g. querying about `Depends()` expanded into logging and typing modules). Restricting to CALLS edges keeps neighbors in the same call-flow context as the query.

3. **RRF replaced max() merge** — Semantic and FTS scores have different scales; RRF normalises by rank position making the merge scale-invariant.

4. **Per-seed neighbor cap (5+5)** — Previously BFS with `ego_graph` across all seeds could return 50+ nodes with heavy cluster overlap. Capping at top-5 callers + top-5 callees per seed (ordered by pagerank) keeps the candidate pool focused.

---

## Next target

Answer relevancy (0.4121) is still well below naive vector's headroom in earlier runs (~0.56 in Run 3 via `run_ragas_new_vs_old.py`). Next lever to try: **semantic filtering of CALLS neighbors** — instead of selecting the top-5 by pagerank, select by cosine similarity of neighbor to query. This avoids high-degree utility nodes that rank high on pagerank but are off-topic.

---

## Eval scripts

| Script | Purpose |
|---|---|
| `run_ragas_redesign.py` | Current — evaluates `graph_rag_retrieve` (v2) only; loads naive baseline from last three-way JSON |
| `run_ragas_three_way.py` | Archived — was naive / Graph RAG v1 / HyDE+CrossEncoder; `improved` column now stubs to v2 |
| `run_ragas_new_vs_old.py` | Archived — two-way comparison used during v1 iterative development |
| `run_ragas_new_only.py` | Archived — single-pipeline scoring used during v1 development |

---

## Golden set

**`golden_qa_v2.json`** — 30 questions spanning:
- Symbol navigation (find class/function definition)
- Inheritance and class hierarchy
- Parameter validation logic
- Middleware and dependency resolution
- Internal routing and ASGI stack

All questions were hand-authored against the fastapi corpus with reference answers.

---

## Run command

```bash
# Full 30Q eval (new_rag only, ~1.5 hours with 2 workers)
source venv_eval/bin/activate
OLLAMA_NUM_PARALLEL=2 python eval/run_ragas_redesign.py --limit 30 --workers 2

# Quick sanity check (5 questions, ~15 min)
python eval/run_ragas_redesign.py --limit 5
```
