"""RAGAS evaluation: redesigned graph_rag_retrieve only.

Evaluates against eval/golden_qa_v2.json (30 code-navigation questions).
Naive baseline is loaded from the most recent ragas_three_way_*.json — no
re-running needed since the corpus and golden set are unchanged.

Pipeline:
  new_rag — redesigned graph_rag_retrieve (RRF + CALLS-depth-1 + propagated score + MMR)

Comparison columns in output:
  Prev Naive   — naive scores from last three-way run
  Prev Graph   — graph_rag scores from last three-way run
  Prev Improved— improved scores from last three-way run
  New RAG      — this run
  Δ vs Naive   — new_rag vs prev naive
  Δ vs Graph   — new_rag vs prev graph_rag

Usage:
    # Quick sanity check — 5 questions
    python eval/run_ragas_redesign.py --limit 5

    # Full 30-question eval, 2 Ollama workers (~1-1.5 hours, new_rag only)
    OLLAMA_NUM_PARALLEL=2 python eval/run_ragas_redesign.py --limit 30 --workers 2

    # Mistral judge (faster scoring, requires MISTRAL_API_KEY)
    python eval/run_ragas_redesign.py --limit 30 --judge mistral
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
            v = v.strip().strip('"').strip("'")
            os.environ.setdefault(k.strip(), v)

from ragas import EvaluationDataset, evaluate, RunConfig
from ragas.dataset_schema import SingleTurnSample
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import ContextPrecision, Faithfulness, ResponseRelevancy

from app.ingestion.graph_store import load_graph
from app.models.schemas import CodeNode
from app.retrieval.graph_rag import graph_rag_retrieve
from app.agent.explorer import explore_stream

REPO_PATH = "/Users/mohammedhafiz/Desktop/Personal/fastapi"
DB_PATH = REPO_PATH + "/.nexus/graph.db"
GOLDEN_PATH = Path(__file__).parent / "golden_qa_v2.json"
MAX_NODES = 15


# ─── Helpers ──────────────────────────────────────────────────────────────────

def build_contexts(nodes: list[CodeNode]) -> list[str]:
    return [
        f"{n.file_path}:{n.line_start}-{n.line_end}\n"
        f"{n.signature or ''}\n{n.docstring or ''}\n{n.body_preview or ''}"
        for n in nodes
    ]


async def get_answer(nodes: list[CodeNode], question: str) -> str:
    for attempt in range(6):
        try:
            return "".join([t async for t in explore_stream(nodes, question)])
        except Exception as e:
            s = (str(e) + " " + type(e).__name__).lower()
            if "429" in str(e) or "rate" in s or "capacity" in s or "timeout" in s or "connect" in s:
                wait = 15 * (attempt + 1)
                print(f"    [llm error, retry {attempt+1}/6, wait {wait}s]: {type(e).__name__}")
                await asyncio.sleep(wait)
            else:
                raise
    print("    [WARNING] get_answer exhausted all retries — returning empty string")
    return ""


# ─── Per-question evaluation ──────────────────────────────────────────────────

async def run_question(
    sem: asyncio.Semaphore,
    i: int,
    total: int,
    entry: dict,
    G,
) -> tuple:
    q, ref = entry["question"], entry["ground_truth"]
    qid = entry.get("id", f"Q{i:02d}")

    new_nodes = new_stat = None
    for attempt in range(5):
        try:
            new_nodes, new_stat = graph_rag_retrieve(
                q, REPO_PATH, G, DB_PATH, max_nodes=MAX_NODES, hop_depth=1
            )
            break
        except Exception as e:
            s = (str(e) + " " + type(e).__name__).lower()
            if "429" in str(e) or "capacity" in s or "timeout" in s or "connect" in s:
                print(f"  [{qid}] retrieval error, retry {attempt+1}/5: {type(e).__name__}")
                await asyncio.sleep(30)
            else:
                raise
    else:
        raise RuntimeError(f"[{qid}] retrieval failed after 5 retries — aborting")

    async with sem:
        print(f"[{i}/{total}] {qid}: {q[:70]}...")
        answer = await get_answer(new_nodes, q)

    new_stat.update({"qid": qid})
    sample = SingleTurnSample(
        user_input=q,
        retrieved_contexts=build_contexts(new_nodes),
        response=answer,
        reference=ref,
    )
    return sample, new_stat


# ─── Scoring ──────────────────────────────────────────────────────────────────

def score_pipeline(samples, metrics, run_config):
    print(f"\nScoring new_rag ({len(samples)} samples)...")
    ds = EvaluationDataset(samples=samples)
    res = evaluate(dataset=ds, metrics=metrics, run_config=run_config,
                   show_progress=True, raise_exceptions=False)
    df = res.to_pandas()

    def _mean(key):
        col = next((c for c in df.columns if key in c.lower()), None)
        if col is None:
            return None
        s = df[col].dropna()
        return float(s.mean()) if not s.empty else None

    return {
        "faithfulness": _mean("faithfulness"),
        "answer_relevancy": (
            (lambda x: x if x is not None else _mean("response_relevancy"))(_mean("answer_relevancy"))
        ),
        "context_precision": _mean("context_precision"),
    }, df


# ─── Load previous baseline ───────────────────────────────────────────────────

def load_previous_baseline() -> dict | None:
    results_dir = Path(__file__).parent / "results"
    candidates = sorted(results_dir.glob("ragas_three_way_*.json"), reverse=True)
    if not candidates:
        print("  [warn] no previous three-way baseline found — comparison columns will be empty")
        return None
    data = json.loads(candidates[0].read_text())
    print(f"  baseline: {candidates[0].name}  ({data.get('questions', '?')}Q)")
    return data


# ─── Main ────────────────────────────────────────────────────────────────────

async def main(limit, judge, ollama_chat, ollama_embed, answer_concurrency, workers):
    print(f"\nNexus RAGAS — Redesign Evaluation (new_rag only)")
    print(f"  corpus : {REPO_PATH}")
    print(f"  golden : {GOLDEN_PATH.name}")

    print("Loading graph...")
    G = load_graph(REPO_PATH, DB_PATH)
    print(f"  {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    golden: list[dict] = json.loads(GOLDEN_PATH.read_text())
    if limit:
        golden = golden[:limit]
    print(f"  {len(golden)} questions\n")

    baseline = load_previous_baseline()

    if judge == "ollama":
        from langchain_ollama import ChatOllama, OllamaEmbeddings
        base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        llm = LangchainLLMWrapper(ChatOllama(model=ollama_chat, temperature=0, base_url=base))
        emb = LangchainEmbeddingsWrapper(OllamaEmbeddings(model=ollama_embed, base_url=base))
        print(f"  judge  : ollama  chat={ollama_chat}  embed={ollama_embed}")
        run_cfg = RunConfig(timeout=180, max_retries=1, max_workers=workers)
    else:
        from langchain_mistralai import ChatMistralAI, MistralAIEmbeddings
        key = os.environ.get("MISTRAL_API_KEY") or os.environ.get("LLM_PROVIDER_API_KEY")
        if not key:
            raise RuntimeError("Set MISTRAL_API_KEY in .env")
        llm = LangchainLLMWrapper(ChatMistralAI(model="mistral-large-latest", temperature=0, api_key=key))
        emb = LangchainEmbeddingsWrapper(MistralAIEmbeddings(model="mistral-embed", api_key=key))
        print(f"  judge  : mistral (mistral-large-latest)")
        run_cfg = RunConfig(timeout=120, max_retries=3, max_workers=workers)

    metrics = [Faithfulness(llm=llm), ResponseRelevancy(llm=llm, embeddings=emb), ContextPrecision(llm=llm)]

    sem = asyncio.Semaphore(answer_concurrency)
    all_results = await asyncio.gather(*[
        run_question(sem, i, len(golden), entry, G)
        for i, entry in enumerate(golden, 1)
    ])

    samples  = [r[0] for r in all_results]
    new_stats = [r[1] for r in all_results]

    new_agg, new_df = score_pipeline(samples, metrics, run_cfg)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = {
        "timestamp": timestamp,
        "repo_path": REPO_PATH,
        "golden_qa": "golden_qa_v2.json",
        "questions": len(golden),
        "new_rag": new_agg,
        "baseline_file": str(sorted(
            (Path(__file__).parent / "results").glob("ragas_three_way_*.json"), reverse=True
        )[0].name) if baseline else None,
        "retrieval_stats": {"new_rag": new_stats},
        "per_question": {"new_rag": new_df.to_dict(orient="records")},
    }
    out_path = Path(__file__).parent / "results" / f"ragas_redesign_{timestamp}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, default=str))

    # ── Comparison table ──────────────────────────────────────────────────────
    W = 96
    f4  = lambda x: f"{x:.4f}" if x is not None else "  N/A "
    pct = lambda a, b: f"{(b - a) / a * 100:+.1f}%" if (a and b and a != 0) else "  N/A"

    print("\n" + "=" * W)
    print("  RAGAS REDESIGN  —  golden_qa_v2.json")
    print("=" * W)

    if baseline:
        b_naive = baseline.get("naive", {})
        b_graph = baseline.get("graph_rag", {})
        b_imprv = baseline.get("improved", {})
        b_ts    = baseline.get("timestamp", "?")
        print(f"\n  Previous three-way baseline  ({b_ts}, {baseline.get('questions','?')}Q)")
        print(f"  {'Metric':<26} {'Naive':>10} {'Graph RAG':>10} {'Improved':>10}")
        print("  " + "-" * (W - 2))
        for m in ("faithfulness", "answer_relevancy", "context_precision"):
            print(f"  {m:<26} {f4(b_naive.get(m)):>10} {f4(b_graph.get(m)):>10} {f4(b_imprv.get(m)):>10}")

    print(f"\n  This run  ({timestamp}, {len(golden)}Q)")
    print(f"  {'Metric':<26} {'New RAG':>10} {'Δ vs Naive':>12} {'Δ vs Graph':>12}")
    print("  " + "-" * (W - 2))
    for m in ("faithfulness", "answer_relevancy", "context_precision"):
        v      = new_agg.get(m)
        b_n    = baseline.get("naive", {}).get(m) if baseline else None
        b_g    = baseline.get("graph_rag", {}).get(m) if baseline else None
        print(f"  {m:<26} {f4(v):>10} {pct(b_n, v):>12} {pct(b_g, v):>12}")

    print("=" * W)
    print(f"\n  Results → {out_path}")
    print("=" * W)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=5)
    p.add_argument("--judge", choices=["mistral", "ollama"], default="ollama")
    p.add_argument("--ollama-chat-model", default="qwen2.5:7b")
    p.add_argument("--ollama-embed-model", default="nomic-embed-text")
    p.add_argument("--answer-concurrency", type=int, default=3)
    p.add_argument("--workers", type=int, default=1)
    args = p.parse_args()
    asyncio.run(main(
        args.limit, args.judge, args.ollama_chat_model, args.ollama_embed_model,
        args.answer_concurrency, args.workers,
    ))
