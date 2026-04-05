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
| **Graph RAG v2** | FTS + RRF merge + CALLS-only depth-1 expansion + propagated score (`parent_rrf × 0.6`) + MMR |
| **Graph RAG v2 + CE** | Same as v2, plus cross-encoder rerank (`ms-marco-MiniLM-L-6-v2`) over top `2×N` candidates before MMR — current production |

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

### Run C — Cross-Encoder Reranking
**Script:** `run_ragas_redesign.py --ce-only` · **Date:** 2026-04-04 · **File:** `ragas_redesign_20260404_024959.json`
*(v2 baseline carried from Run B — same corpus, same golden set, same judge config)*

| Pipeline | Faithfulness | Answer Relevancy | Context Precision |
|---|---|---|---|
| Naive Vector *(Run A)* | 0.3148 | 0.2133 | 0.1585 |
| Graph RAG v2 *(Run B)* | 0.5389 | 0.4121 | 0.2532 |
| **Graph RAG v2 + CE** | **0.5417** | **0.4827** | **0.3706** |

**v2+CE vs v2:** +0.5% faithfulness · **+17.1% answer relevancy** · **+46.4% context precision**  
**v2+CE vs Naive:** +72.1% faithfulness · +126.3% answer relevancy · +133.8% context precision

Cross-encoder reranking produces the largest single-step gain in context precision (+46.4%) of any improvement to date. Answer relevancy improvement (+17.1%) confirms the CE is surfacing more query-relevant nodes. Faithfulness is unchanged — CE affects context selection, not answer generation.

---

## What drove the improvement (v1 → v2)

1. **Propagated score replaced the 0.0 semantic fallback** — Graph RAG v1 scored all BFS-expanded non-seed nodes at `0.3 × (0.2×pagerank + 0.1×in_degree)`, making score independent of query relevance. v2 sets `neighbor_score = parent_rrf_score × 0.6`, anchoring each neighbor's competitiveness to how relevant its parent seed was.

2. **CALLS-only expansion (IMPORTS removed)** — IMPORTS edges created cross-file pollution (e.g. querying about `Depends()` expanded into logging and typing modules). Restricting to CALLS edges keeps neighbors in the same call-flow context as the query.

3. **RRF replaced max() merge** — Semantic and FTS scores have different scales; RRF normalises by rank position making the merge scale-invariant.

4. **Per-seed neighbor cap (5+5)** — Previously BFS with `ego_graph` across all seeds could return 50+ nodes with heavy cluster overlap. Capping at top-5 callers + top-5 callees per seed (ordered by pagerank) keeps the candidate pool focused.

---

### Run D — v3.1 (PPR + CLASS_CONTAINS + hybrid CE floor + balanced prompt)
**Script:** `run_ragas_v3.py --skip-context-precision` · **Date:** 2026-04-05 · **Files:** `ragas_v3_20260405_214543.json` + `ragas_v3_20260406_*.json`

| Pipeline | Faithfulness | Answer Relevancy | Context Precision |
|---|---|---|---|
| Naive Vector *(Run A)* | 0.3148 | 0.2133 | 0.1585 |
| Graph RAG v2+CE *(Run C)* | 0.5417 | 0.4827 | 0.3706 |
| **Graph RAG v3.1** | **0.9133** | **0.7742** | **0.6685** |

**v3.1 vs v2+CE:** +68.6% faithfulness · +60.4% answer relevancy · +80.4% context precision  
**v3.1 vs Naive:** +190% faithfulness · +263% answer relevancy · +322% context precision

---

## What drove the v3.1 improvement

1. **CLASS_CONTAINS edges** — Python + TypeScript AST parsers now emit class→method hierarchy edges (255 new edges in fastapi corpus). Requires re-index.

2. **Personalized PageRank expansion** — replaced BFS depth-1 expansion with PPR seeded proportionally from RRF scores, traversing CALLS + CLASS_CONTAINS edges. Top-30 non-seed neighbors returned; IMPORTS excluded to avoid cross-file pollution. Source: HippoRAG (NeurIPS 2024).

3. **Hybrid CE floor** — replaces hard `ce_score > 0` cut with: always keep top-3 candidates, drop extras >4.0 logit-units below best. Prevents zero-context responses on abstract queries. Source: FILCO.

4. **Full-body expansion** — top-5 CE-ranked nodes get full source read (`line_start → line_end`) instead of `body_preview`. Source: cAST 2025 (+5.5pts on RepoEval).

5. **Balanced grounding prompt** — "prefer retrieved context as primary source; use general programming knowledge to explain and connect what you see in code." Replaced an over-restrictive "ban all parametric knowledge" rule that caused the LLM to refuse answering instead of reasoning from code (faith=0.04 with the ban; faith=0.91 with the balanced version).

---

## Eval scripts

| Script | Purpose |
|---|---|
| `run_ragas_v3.py` | **Current** — evaluates v3.1 pipeline only; loads all prior baselines from file. Supports `--skip-context-precision` to reuse ctx_prec and save ~33% eval time. |
| `run_ragas_redesign.py` | Archived — v2/v2+CE evaluation |
| `run_ragas_three_way.py` | Archived — naive / Graph RAG v1 / HyDE+CrossEncoder |
| `run_ragas_new_vs_old.py` | Archived — two-way comparison used during v1 development |
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
source venv_eval/bin/activate

# Full 30Q v3 eval (~2h)
python eval/run_ragas_v3.py --limit 30 --workers 1 --answer-concurrency 1

# Full 30Q — skip Context Precision (reuse from last result, saves ~40 min)
python eval/run_ragas_v3.py --limit 30 --workers 1 --skip-context-precision

# Quick sanity check (5 questions, ~15 min)
python eval/run_ragas_v3.py --limit 5
```

> **Note:** Re-index the corpus after any ingestion changes to pick up new edge types.
> Delete `.nexus/graph.db` or run `python eval/reindex_fastapi.py` to rebuild from scratch.
