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

## Results (Nexus codebase baseline)

| Strategy | Faithfulness | Relevance | Precision | Recall | **Composite** |
|---|---|---|---|---|---|
| Graph RAG | 0.92 | 0.88 | 0.85 | 0.81 | **0.87** |
| Naive vector | 0.89 | 0.83 | 0.71 | 0.64 | **0.77** |

Graph-aware retrieval: **+13%** composite. Largest gains in precision (+0.14) and recall (+0.17) — BFS expansion surfaces structurally relevant nodes that semantic similarity alone misses.

## Run

```bash
source ../venv/bin/activate
python run_ragas.py --repo-path /path/to/repo
```

**Prerequisites:** backend running · repo indexed · `OPENAI_API_KEY` set

| Flag | Default | |
|---|---|---|
| `--repo-path` | current dir | Target repo |
| `--backend-url` | `http://localhost:8000` | Backend |
| `--n` | 30 | Q&A pairs to evaluate (subset for speed) |
| `--output` | `results/results_<ts>.json` | Output path |

## Files

```
eval/
├── golden_qa.json    30 Q&A pairs with reference node IDs
├── run_ragas.py      evaluation runner
└── results/          timestamped JSON result files
```
