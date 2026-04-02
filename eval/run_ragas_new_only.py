"""RAGAS evaluation: new retrieval pipeline only, compared against Run 3 baseline.

Run 3 baseline (2026-04-02/03, Ollama qwen2.5:7b, 30Q, old naive-vector pipeline):
    faithfulness=0.5763, answer_relevancy=0.5607, context_precision=0.0776

Run 3 new-pipeline pre-fix (same run, FTS+BFS before fixes):
    faithfulness=0.5058, answer_relevancy=0.4287, context_precision=0.0896

This script evaluates only graph_rag_retrieve (with current fixes applied) and
prints a delta table against both Run 3 baselines so we can see net improvement.

Parallelisation levers
----------------------
--answer-concurrency N  Run N answer-gen calls concurrently via asyncio.gather
                        (default 4; Mistral handles this comfortably without 429s)
--workers N             RAGAS scoring parallelism via RunConfig(max_workers=N)
                        (default 1 for Ollama; set OLLAMA_NUM_PARALLEL=N to match)

Usage:
    # Fast dev run — 10 questions, defaults
    python eval/run_ragas_new_only.py

    # Full eval, parallel answer-gen + 2 Ollama scoring workers (~45 min)
    OLLAMA_NUM_PARALLEL=2 python eval/run_ragas_new_only.py --limit 30 --workers 2
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
from app.retrieval.graph_rag import graph_rag_retrieve
from app.agent.explorer import explore_stream

# Run 3 baselines — Ollama qwen2.5:7b, 30 questions, fastapi corpus
RUN3_OLD = {"faithfulness": 0.5763, "answer_relevancy": 0.5607, "context_precision": 0.0776}
RUN3_NEW_PREFIXED = {"faithfulness": 0.5058, "answer_relevancy": 0.4287, "context_precision": 0.0896}

REPO_PATH = "/Users/mohammedhafiz/Desktop/Personal/fastapi"
DB_PATH = REPO_PATH + "/.nexus/graph.db"
GOLDEN_PATH = Path(__file__).parent / "golden_qa.json"
MAX_NODES = 15


async def get_answer(nodes: list[CodeNode], question: str) -> str:
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
                await asyncio.sleep(wait)
            else:
                raise
    return ""


async def _retrieve_and_answer(
    sem: asyncio.Semaphore,
    i: int,
    total: int,
    entry: dict,
    G,
) -> tuple[dict, list[CodeNode], dict]:
    """Retrieve context for one question and generate an answer under the semaphore."""
    q, ref = entry["question"], entry["ground_truth"]
    qid = entry.get("id", f"Q{i:02d}")

    # Retrieval is CPU-bound and fast — run outside the semaphore so all
    # questions retrieve in parallel without waiting on answer-gen slots.
    for attempt in range(5):
        try:
            nodes, stats = graph_rag_retrieve(q, REPO_PATH, G, DB_PATH, max_nodes=MAX_NODES, hop_depth=1)
            break
        except Exception as e:
            if "429" in str(e) or "capacity" in str(e).lower():
                print(f"    [{qid}] retrieval rate limited, retry {attempt+1}/5, waiting 60s...")
                await asyncio.sleep(60)
            else:
                raise

    # Answer generation is I/O-bound — gate on the semaphore to cap concurrency.
    async with sem:
        print(f"[{i}/{total}] {qid}: {q[:65]}...")
        answer = await get_answer(nodes, q)

    sample = SingleTurnSample(
        user_input=q, retrieved_contexts=build_contexts(nodes), response=answer, reference=ref
    )
    retrieval_stat = {
        "qid": qid,
        "nodes_returned": len(nodes),
        "seed_count": stats.get("seed_count", 0),
        "semantic_seeds": stats.get("semantic_seeds", 0),
        "fts_seeds": stats.get("fts_seeds", 0),
        "expanded_count": stats.get("expanded_count", 0),
    }
    return sample, retrieval_stat


def build_contexts(nodes: list[CodeNode]) -> list[str]:
    return [
        f"{n.file_path}:{n.line_start}-{n.line_end}\n{n.signature}\n{n.docstring or ''}\n{n.body_preview}"
        for n in nodes
    ]


async def main(
    limit: int | None,
    judge: str,
    ollama_chat_model: str,
    ollama_embed_model: str,
    answer_concurrency: int,
    workers: int,
) -> None:
    print(f"\nNexus RAGAS — New pipeline only (vs Run 3 baseline)")
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
        run_config = RunConfig(timeout=180, max_retries=1, max_workers=workers)
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
        run_config = RunConfig(timeout=120, max_retries=3, max_workers=workers)

    metrics = [
        Faithfulness(llm=llm),
        ResponseRelevancy(llm=llm, embeddings=emb),
        ContextPrecision(llm=llm),
    ]

    print(f"  answer concurrency: {answer_concurrency}  |  ragas workers: {workers}\n")

    # Phase 1 + 2: retrieve context and generate answers in parallel.
    # A semaphore caps the number of concurrent LLM answer-gen calls.
    sem = asyncio.Semaphore(answer_concurrency)
    results = await asyncio.gather(*[
        _retrieve_and_answer(sem, i, len(golden), entry, G)
        for i, entry in enumerate(golden, 1)
    ])

    # Preserve question order (gather returns results in submission order)
    samples: list[SingleTurnSample] = [r[0] for r in results]
    retrieval_stats: list[dict] = [r[1] for r in results]

    print(f"\nEvaluating {len(samples)} samples...")
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

    # Save results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(exist_ok=True)

    avg_fts = sum(s["fts_seeds"] for s in retrieval_stats) / len(retrieval_stats)
    avg_expanded = sum(s["expanded_count"] for s in retrieval_stats) / len(retrieval_stats)
    avg_returned = sum(s["nodes_returned"] for s in retrieval_stats) / len(retrieval_stats)

    output = {
        "timestamp": timestamp,
        "repo_path": REPO_PATH,
        "questions": len(golden),
        "aggregate": agg,
        "run3_old_baseline": RUN3_OLD,
        "run3_new_prefixed_baseline": RUN3_NEW_PREFIXED,
        "retrieval_coverage": {
            "avg_fts_seeds_per_query": round(avg_fts, 1),
            "avg_expanded_nodes_per_query": round(avg_expanded, 1),
            "avg_nodes_returned": round(avg_returned, 1),
        },
        "per_question": df.to_dict(orient="records"),
        "per_question_retrieval": retrieval_stats,
    }
    out_path = results_dir / f"ragas_new_only_{timestamp}.json"
    out_path.write_text(json.dumps(output, indent=2, default=str))

    # Print report
    print("\n" + "=" * 80)
    print("  RAGAS REPORT — New Graph-RAG (FTS no-BFS + MMR) vs Run 3 Baselines")
    print("=" * 80)
    print(f"  {'Metric':<26} {'Run3 Old':>12} {'Run3 New(pre)':>14} {'This run':>12} {'vs Old%':>9} {'vs Pre%':>9}")
    print("-" * 80)
    for m in ("faithfulness", "answer_relevancy", "context_precision"):
        cur = agg.get(m)
        old = RUN3_OLD.get(m)
        pre = RUN3_NEW_PREFIXED.get(m)
        cur_s = f"{cur:.4f}" if cur is not None else "N/A"
        old_s = f"{old:.4f}" if old is not None else "N/A"
        pre_s = f"{pre:.4f}" if pre is not None else "N/A"
        vs_old = f"{(cur-old)/old*100:+.1f}%" if cur is not None and old else "N/A"
        vs_pre = f"{(cur-pre)/pre*100:+.1f}%" if cur is not None and pre else "N/A"
        print(f"  {m:<26} {old_s:>12} {pre_s:>14} {cur_s:>12} {vs_old:>9} {vs_pre:>9}")
    print("=" * 80)
    print(f"\n  Retrieval coverage (avg per query):")
    print(f"    FTS seeds:        {avg_fts:.1f}")
    print(f"    Expanded nodes:   {avg_expanded:.1f}  (was ~57.2 before FTS-BFS fix)")
    print(f"    Nodes returned:   {avg_returned:.1f}")
    print(f"\n  Results: {out_path.name}")
    print("=" * 80)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10,
                        help="Limit to first N questions (default: 10; use --limit 30 for full eval)")
    parser.add_argument("--judge", choices=["mistral", "ollama"], default="ollama")
    parser.add_argument("--ollama-chat-model", default="qwen2.5:7b")
    parser.add_argument("--ollama-embed-model", default="nomic-embed-text")
    parser.add_argument("--answer-concurrency", type=int, default=4,
                        help="Concurrent answer-gen LLM calls via asyncio.gather (default: 4)")
    parser.add_argument("--workers", type=int, default=1,
                        help="RAGAS scoring parallelism — set OLLAMA_NUM_PARALLEL=N to match (default: 1)")
    args = parser.parse_args()
    asyncio.run(main(
        args.limit, args.judge, args.ollama_chat_model, args.ollama_embed_model,
        args.answer_concurrency, args.workers,
    ))
