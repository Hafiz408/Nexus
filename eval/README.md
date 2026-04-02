# Evaluation

RAGAS-based suite that measures retrieval quality by comparing **graph-aware retrieval** against **naive vector search**.

## How It Works

```
golden_qa.json  (30 hand-labelled Q&A pairs)
    │
    ├── Graph RAG    semantic → BFS expand → rerank  ─┐
    └── Naive vector semantic only                    ─┤
                                                       ▼
                                             RAGAS scorer
                              Faithfulness · Relevance · Precision · Recall
                                                       │
                                              results/<timestamp>.json
```

Both strategies feed the **same LLM** — score differences isolate retrieval quality, not model quality.

## Results — fastapi corpus, 30 questions, Ollama qwen2.5:7b judge

Three retrieval strategies evaluated on the same 30 golden Q&A pairs:

| Strategy | Faithfulness | Answer Relevancy | Context Precision |
|---|---|---|---|
| Naive vector (semantic only) | 0.5763 | 0.5607 | 0.0776 |
| Graph RAG — FTS + BFS (pre-fix) | 0.5058 | 0.4287 | 0.0896 |
| **Graph RAG — FTS no-BFS + MMR** | **0.5714** | **0.4410** | **0.1803** |

**vs naive vector:** context_precision **+132%** — retrieved chunks are far more on-topic. Faithfulness nearly recovered (−0.8%). Answer relevancy gap (−21%) is the next target.

**vs pre-fix graph RAG:** all three metrics improved. The two fixes applied:
1. **FTS seeds skip BFS** — FTS matches are added directly to the candidate pool without expanding their graph neighbours, cutting noise from symbol-adjacent but query-irrelevant context.
2. **MMR diversity pass** — after reranking, Maximal Marginal Relevance selects the final 15 nodes penalising repeated `file_path` clusters, preventing one file's methods from dominating the result set.

Retrieval stats (avg per query): FTS seeds 4.8 · expanded nodes 51.4 (↓ from 57.2) · nodes returned 15.

## Run

```bash
source ../venv/bin/activate
python run_ragas.py --repo-path /path/to/repo
```

**Prerequisites:** backend running (starts automatically with the extension, or run `uvicorn app.main:app` locally) · repo indexed · API key set for your chosen provider (OpenAI used by default for RAGAS scoring)

| Flag | Default | |
|---|---|---|
| `--repo-path` | current dir | Target repo |
| `--backend-url` | `http://localhost:8000` | Backend |
| `--n` | 30 | Q&A pairs to evaluate (subset for speed) |
| `--output` | `results/results_<ts>.json` | Output path |
| `--db-path` | `<repo>/.nexus/graph.db` | Explicit path to graph DB (useful when DB lives outside the repo root) |

## Files

```
eval/
├── golden_qa.json    30 Q&A pairs with reference node IDs
├── run_ragas.py      evaluation runner
└── results/          timestamped JSON result files
```
