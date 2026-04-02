"""RAGAS evaluation: new retrieval (FTS + test-penalty + graph) vs old (naive semantic-only).

New  = graph_rag_retrieve: dual semantic+FTS search, test-file penalty, BFS expansion, reranking
Old  = semantic_search only: cosine vector nearest-neighbours, no FTS, no penalty, no graph

Usage:
    python eval/run_ragas_new_vs_old.py
    python eval/run_ragas_new_vs_old.py --limit 10   # first 10 questions only
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.WARNING)
os.environ["LANGCHAIN_TRACING_V2"] = "false"

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root / "backend"))
_env = _root / ".env"
if _env.exists():
    for _line in _env.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            k, v = _line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from ragas import EvaluationDataset, evaluate, RunConfig
from ragas.dataset_schema import SingleTurnSample
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import ContextPrecision, Faithfulness, ResponseRelevancy

from app.ingestion.graph_store import load_graph
from app.models.schemas import CodeNode
import app.retrieval.graph_rag as _graph_rag_module
from app.retrieval.graph_rag import graph_rag_retrieve, semantic_search
from app.agent.explorer import explore_stream

# Cache semantic_search results so both old-path and new-path (graph_rag_retrieve)
# use a single embed API call per question instead of two.
_semantic_cache: dict = {}
_orig_semantic_search = _graph_rag_module.semantic_search

def _cached_semantic_search(query: str, repo_path: str, top_k: int, db_path: str):
    key = (query, repo_path, top_k, db_path)
    if key not in _semantic_cache:
        _semantic_cache[key] = _orig_semantic_search(query, repo_path, top_k=top_k, db_path=db_path)
    return _semantic_cache[key]

_graph_rag_module.semantic_search = _cached_semantic_search

REPO_PATH = "/Users/mohammedhafiz/Desktop/Personal/fastapi"
DB_PATH = REPO_PATH + "/.nexus/graph.db"
GOLDEN_PATH = Path(__file__).parent / "golden_qa.json"
MAX_NODES = 15  # bump default (new pipeline)


async def get_answer(nodes: list[CodeNode], question: str) -> str:
    import time
    for attempt in range(6):
        try:
            tokens: list[str] = []
            async for token in explore_stream(nodes, question):
                tokens.append(token)
            return "".join(tokens)
        except Exception as e:
            if "429" in str(e) or "rate" in str(e).lower() or "capacity" in str(e).lower():
                wait = 60 * (attempt + 1)
                print(f"    [answer gen rate limited, retry {attempt+1}/6, waiting {wait}s...]")
                time.sleep(wait)
            else:
                raise
    return ""  # empty fallback if all retries exhausted


def hydrate_naive(results: list[tuple[str, float]], G) -> list[CodeNode]:
    nodes = []
    for node_id, _ in results:
        if node_id not in G:
            continue
        try:
            attrs = G.nodes[node_id]
            nodes.append(CodeNode(**{k: v for k, v in attrs.items() if k in CodeNode.model_fields}))
        except Exception:
            continue
    return nodes


def build_contexts(nodes: list[CodeNode]) -> list[str]:
    return [
        f"{n.file_path}:{n.line_start}-{n.line_end}\n{n.signature}\n{n.docstring or ''}\n{n.body_preview}"
        for n in nodes
    ]


async def main(limit: int | None, judge: str, ollama_chat_model: str, ollama_embed_model: str) -> None:
    print(f"\nNexus RAGAS — New vs Old retrieval")
    print(f"  repo:    {REPO_PATH}")
    print(f"  db:      {DB_PATH}")

    print("Loading graph...")
    G = load_graph(REPO_PATH, DB_PATH)
    print(f"  {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    golden: list[dict] = json.loads(GOLDEN_PATH.read_text())
    if limit:
        golden = golden[:limit]
    print(f"  {len(golden)} questions to evaluate\n")

    if judge == "ollama":
        from langchain_ollama import ChatOllama, OllamaEmbeddings
        ollama_base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        llm = LangchainLLMWrapper(ChatOllama(model=ollama_chat_model, temperature=0, base_url=ollama_base))
        emb = LangchainEmbeddingsWrapper(OllamaEmbeddings(model=ollama_embed_model, base_url=ollama_base))
        print(f"  judge:   ollama  chat={ollama_chat_model}  embed={ollama_embed_model}  base={ollama_base}")
    else:
        from langchain_mistralai import ChatMistralAI, MistralAIEmbeddings
        mistral_key = (
            os.environ.get("MISTRAL_API_KEY")
            or os.environ.get("LLM_PROVIDER_API_KEY")
            or os.environ.get("EMBEDDING_PROVIDER_API_KEY")
        )
        if not mistral_key:
            raise RuntimeError("No API key found. Set MISTRAL_API_KEY or LLM_PROVIDER_API_KEY in .env")
        llm = LangchainLLMWrapper(ChatMistralAI(model="mistral-large-latest", temperature=0, api_key=mistral_key))
        emb = LangchainEmbeddingsWrapper(MistralAIEmbeddings(model="mistral-embed", api_key=mistral_key))
        print(f"  judge:   mistral (mistral-large-latest)")

    metrics = [
        Faithfulness(llm=llm),
        ResponseRelevancy(llm=llm, embeddings=emb),
        ContextPrecision(llm=llm),
    ]
    # Ollama serves one request at a time — force sequential scoring to avoid timeout pile-up
    if judge == "ollama":
        run_config = RunConfig(timeout=180, max_retries=1, max_workers=1)
    else:
        run_config = RunConfig(timeout=120, max_retries=3)

    new_samples: list[SingleTurnSample] = []
    old_samples: list[SingleTurnSample] = []
    retrieval_stats: list[dict] = []

    import time

    for i, entry in enumerate(golden, 1):
        q, ref = entry["question"], entry["ground_truth"]
        qid = entry.get("id", f"Q{i:02d}")
        print(f"[{i}/{len(golden)}] {qid}: {q[:65]}...")

        # Throttle only for Mistral (rate limited API); Ollama runs locally with no limit
        if i > 1 and judge != "ollama":
            time.sleep(15)

        # NEW: graph_rag_retrieve (FTS + test-penalty + BFS + rerank).
        # The monkeypatched semantic_search caches the query embed, so the old-path
        # call below is a free cache hit with no additional API call.
        for attempt in range(5):
            try:
                new_nodes, stats = graph_rag_retrieve(q, REPO_PATH, G, DB_PATH, max_nodes=MAX_NODES, hop_depth=1)
                break
            except Exception as e:
                if "429" in str(e) or "capacity" in str(e).lower():
                    print(f"    [rate limited, retry {attempt+1}/5, waiting 60s...]")
                    time.sleep(60)
                else:
                    raise
        new_ans = await get_answer(new_nodes, q)

        # OLD: semantic vector search only — cache hit, zero extra API calls
        old_results = _cached_semantic_search(q, REPO_PATH, top_k=MAX_NODES, db_path=DB_PATH)
        old_nodes = hydrate_naive(old_results, G)
        old_ans = await get_answer(old_nodes, q)


        new_samples.append(SingleTurnSample(
            user_input=q, retrieved_contexts=build_contexts(new_nodes), response=new_ans, reference=ref
        ))
        old_samples.append(SingleTurnSample(
            user_input=q, retrieved_contexts=build_contexts(old_nodes), response=old_ans, reference=ref
        ))
        retrieval_stats.append({
            "qid": qid,
            "new_nodes_returned": len(new_nodes),
            "old_nodes_returned": len(old_nodes),
            "new_seed_count": stats.get("seed_count", 0),
            "new_semantic_seeds": stats.get("semantic_seeds", 0),
            "new_fts_seeds": stats.get("fts_seeds", 0),
            "new_expanded": stats.get("expanded_count", 0),
        })

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(exist_ok=True)

    all_agg: dict[str, dict] = {}

    for label, samples in [("new_graph_rag", new_samples), ("old_naive_vector", old_samples)]:
        print(f"\nEvaluating {label} ({len(samples)} samples)...")
        dataset = EvaluationDataset(samples=samples)
        result = evaluate(dataset=dataset, metrics=metrics, run_config=run_config,
                          show_progress=True, raise_exceptions=False)
        df = result.to_pandas()

        def _safe_mean(key: str) -> float | None:
            col = next((c for c in df.columns if key in c.lower()), None)
            if col is None:
                return None
            s = df[col].dropna()
            return float(s.mean()) if not s.empty else None

        agg = {
            "faithfulness": _safe_mean("faithfulness"),
            "answer_relevancy": _safe_mean("answer_relevancy") or _safe_mean("response_relevancy"),
            "context_precision": _safe_mean("context_precision"),
        }
        all_agg[label] = agg

        per_q_path = results_dir / f"ragas_{label}_{timestamp}.json"
        per_q_path.write_text(json.dumps({
            "timestamp": timestamp, "label": label,
            "aggregate": agg, "per_question": df.to_dict(orient="records"),
        }, indent=2, default=str))
        print(f"  Written: {per_q_path.name}")

    # Delta calculation
    new_a, old_a = all_agg["new_graph_rag"], all_agg["old_naive_vector"]
    deltas = {}
    for m in ("faithfulness", "answer_relevancy", "context_precision"):
        n, o = new_a.get(m), old_a.get(m)
        if n is not None and o is not None:
            deltas[m] = {"delta": n - o, "pct_change": (n - o) / o * 100 if o else None}

    # Retrieval coverage stats
    avg_new_fts = sum(s["new_fts_seeds"] for s in retrieval_stats) / len(retrieval_stats)
    avg_new_expanded = sum(s["new_expanded"] for s in retrieval_stats) / len(retrieval_stats)
    avg_old_returned = sum(s["old_nodes_returned"] for s in retrieval_stats) / len(retrieval_stats)
    avg_new_returned = sum(s["new_nodes_returned"] for s in retrieval_stats) / len(retrieval_stats)

    comparison = {
        "timestamp": timestamp,
        "repo_path": REPO_PATH,
        "questions": len(golden),
        "new_graph_rag": new_a,
        "old_naive_vector": old_a,
        "deltas": deltas,
        "retrieval_coverage": {
            "avg_fts_seeds_per_query": round(avg_new_fts, 1),
            "avg_expanded_nodes_per_query": round(avg_new_expanded, 1),
            "avg_nodes_returned_new": round(avg_new_returned, 1),
            "avg_nodes_returned_old": round(avg_old_returned, 1),
        },
        "per_question_retrieval": retrieval_stats,
    }
    comp_path = results_dir / f"ragas_new_vs_old_{timestamp}.json"
    comp_path.write_text(json.dumps(comparison, indent=2, default=str))

    # Print report
    print("\n" + "=" * 72)
    print("  RAGAS COMPARISON REPORT — New Graph-RAG vs Old Naive Vector")
    print("=" * 72)
    print(f"  {'Metric':<26} {'Old (semantic)':>16} {'New (FTS+graph)':>16} {'Δ':>10} {'%Δ':>8}")
    print("-" * 72)
    for m in ("faithfulness", "answer_relevancy", "context_precision"):
        o_val = old_a.get(m)
        n_val = new_a.get(m)
        d = deltas.get(m, {})
        o_str = f"{o_val:.4f}" if o_val is not None else "N/A"
        n_str = f"{n_val:.4f}" if n_val is not None else "N/A"
        d_str = f"{d.get('delta', 0):+.4f}" if "delta" in d else "N/A"
        p_str = f"{d.get('pct_change', 0):+.1f}%" if "pct_change" in d and d.get("pct_change") is not None else "N/A"
        print(f"  {m:<26} {o_str:>16} {n_str:>16} {d_str:>10} {p_str:>8}")
    print("=" * 72)
    print(f"\n  Retrieval Coverage (avg per query):")
    print(f"    FTS seeds added by new pipeline: {avg_new_fts:.1f}")
    print(f"    Nodes after BFS expansion (new): {avg_new_expanded:.1f}")
    print(f"    Nodes returned (old): {avg_old_returned:.1f}   Nodes returned (new): {avg_new_returned:.1f}")
    print(f"\n  Comparison file: {comp_path.name}")
    print("=" * 72)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Limit to first N questions")
    parser.add_argument("--judge", choices=["mistral", "ollama"], default="ollama",
                        help="LLM backend for RAGAS scoring (default: ollama)")
    parser.add_argument("--ollama-chat-model", default="qwen2.5:7b",
                        help="Ollama chat model for RAGAS judge (default: qwen2.5:7b)")
    parser.add_argument("--ollama-embed-model", default="nomic-embed-text",
                        help="Ollama embedding model for RAGAS judge (default: nomic-embed-text)")
    args = parser.parse_args()
    asyncio.run(main(args.limit, args.judge, args.ollama_chat_model, args.ollama_embed_model))
