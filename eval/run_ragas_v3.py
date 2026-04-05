"""RAGAS evaluation: Graph RAG v3 (cosine floor + CE floor + full body expansion).

Loads all prior pipeline baselines from existing result files — no re-running.
Only runs the new v3 pipeline (current branch, use_cross_encoder=True).

Baselines loaded from file:
  - Naive Vector  : ragas_three_way_20260403_183816.json → "naive"
  - Graph RAG v1  : ragas_three_way_20260403_183816.json → "graph_rag"
  - Graph RAG v2  : ragas_redesign_20260404_024959.json  → "new_rag_v2"
  - Graph RAG v2+CE: ragas_redesign_20260404_024959.json → "new_rag_v2_ce"

v3 improvements evaluated:
  ① Cosine similarity floor on semantic_search (min_similarity=0.15)
  ② CE score floor before MMR (drop CE ≤ 0.0 nodes)
  ③ Full body expansion for top-5 CE-ranked nodes

build_contexts uses full_body when populated so RAGAS faithfulness
scoring sees the same content the LLM received.

Usage:
    # Quick sanity check (5 questions, ~15 min)
    python eval/run_ragas_v3.py --limit 5

    # Full 30-question eval (1.5–2 h)
    OLLAMA_NUM_PARALLEL=2 python eval/run_ragas_v3.py --limit 30 --workers 2

    # Mistral judge (faster)
    python eval/run_ragas_v3.py --limit 30 --judge mistral
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
RESULTS_DIR = Path(__file__).parent / "results"
MAX_NODES = 15


# ─── Context builder ─────────────────────────────────────────────────────────

def build_contexts(nodes: list[CodeNode]) -> list[str]:
    """Build RAGAS context strings using full_body when populated.

    Uses full_body (populated by _expand_full_bodies for top-5 nodes) when
    non-empty, falling back to body_preview. This ensures RAGAS faithfulness
    scoring sees the same content the LLM received — not the truncated preview.
    """
    return [
        f"{n.file_path}:{n.line_start}-{n.line_end}\n"
        f"{n.signature or ''}\n{n.docstring or ''}\n"
        f"{n.full_body if n.full_body else n.body_preview}"
        for n in nodes
    ]


# ─── Baselines ───────────────────────────────────────────────────────────────

def load_baselines() -> dict:
    """Load all prior pipeline scores from existing result files."""
    baselines: dict[str, dict | None] = {
        "naive": None, "v1": None, "v2": None, "v2_ce": None,
    }

    # Three-way run: naive, graph_rag (v1), improved (HyDE+CE)
    three_way_files = sorted(RESULTS_DIR.glob("ragas_three_way_*.json"), reverse=True)
    if three_way_files:
        data = json.loads(three_way_files[0].read_text())
        baselines["naive"] = data.get("naive")
        baselines["v1"] = data.get("graph_rag")
        print(f"  three-way baseline : {three_way_files[0].name}  ({data.get('questions', '?')}Q)")
    else:
        print("  [warn] no ragas_three_way_*.json found")

    # Redesign run: v2 and v2+CE
    redesign_files = sorted(RESULTS_DIR.glob("ragas_redesign_*.json"), reverse=True)
    if redesign_files:
        data = json.loads(redesign_files[0].read_text())
        baselines["v2"] = data.get("new_rag_v2")
        baselines["v2_ce"] = data.get("new_rag_v2_ce")
        print(f"  redesign baseline  : {redesign_files[0].name}  ({data.get('questions', '?')}Q)")
    else:
        print("  [warn] no ragas_redesign_*.json found")

    return baselines


# ─── Helpers ─────────────────────────────────────────────────────────────────

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


async def run_question(
    sem: asyncio.Semaphore,
    i: int,
    total: int,
    entry: dict,
    G,
) -> tuple[SingleTurnSample, dict]:
    q, ref = entry["question"], entry["ground_truth"]
    qid = entry.get("id", f"Q{i:02d}")

    nodes = stat = None
    for attempt in range(5):
        try:
            nodes, stat = graph_rag_retrieve(
                q, REPO_PATH, G, DB_PATH,
                max_nodes=MAX_NODES, hop_depth=1, use_cross_encoder=True,
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
        print(
            f"[{i}/{total}] {qid}: {q[:65]}…  "
            f"(ce_dropped={stat.get('ce_floor_dropped', 0)}, "
            f"expanded={stat.get('full_body_expanded', 0)})"
        )
        answer = await get_answer(nodes, q)

    stat["qid"] = qid
    sample = SingleTurnSample(
        user_input=q,
        retrieved_contexts=build_contexts(nodes),
        response=answer,
        reference=ref,
    )
    return sample, stat


# ─── Scoring ─────────────────────────────────────────────────────────────────

def score_pipeline(samples, metrics, run_config, label: str = "v3") -> tuple[dict, object]:
    print(f"\nScoring {label} ({len(samples)} samples)...")
    ds = EvaluationDataset(samples=samples)
    res = evaluate(
        dataset=ds, metrics=metrics, run_config=run_config,
        show_progress=True, raise_exceptions=False,
    )
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


# ─── Main ────────────────────────────────────────────────────────────────────

async def main(limit: int, judge: str, ollama_chat: str, ollama_embed: str,
               answer_concurrency: int, workers: int) -> None:
    print(f"\nNexus RAGAS — v3 Evaluation")
    print(f"  corpus : {REPO_PATH}")
    print(f"  golden : {GOLDEN_PATH.name}")
    print(f"  limit  : {limit or 'all'}")
    print(f"  judge  : {judge}\n")

    print("Loading baselines...")
    baselines = load_baselines()

    print("\nLoading graph...")
    G = load_graph(REPO_PATH, DB_PATH)
    print(f"  {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    golden: list[dict] = json.loads(GOLDEN_PATH.read_text())
    if limit:
        golden = golden[:limit]
    print(f"  {len(golden)} questions\n")

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

    print("Running v3 pipeline...")
    v3_results = await asyncio.gather(*[
        run_question(sem, i, len(golden), entry, G)
        for i, entry in enumerate(golden, 1)
    ])
    v3_samples = [r[0] for r in v3_results]
    v3_stats   = [r[1] for r in v3_results]

    v3_agg, v3_df = score_pipeline(v3_samples, metrics, run_cfg, label="v3")

    # ── v3 aggregate retrieval stats ──────────────────────────────────────────
    ce_dropped_total = sum(s.get("ce_floor_dropped", 0) for s in v3_stats)
    expanded_total   = sum(s.get("full_body_expanded", 0) for s in v3_stats)
    print(f"\n  v3 retrieval summary across {len(golden)} questions:")
    print(f"    ce_floor_dropped  total={ce_dropped_total}  avg={ce_dropped_total/len(golden):.1f}")
    print(f"    full_body_expanded total={expanded_total}   avg={expanded_total/len(golden):.1f}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = {
        "timestamp": timestamp,
        "repo_path": REPO_PATH,
        "golden_qa": "golden_qa_v2.json",
        "questions": len(golden),
        "pipeline": "v3 (cosine_floor + ce_floor + full_body)",
        "v3": v3_agg,
        "baselines": baselines,
        "retrieval_stats_v3": v3_stats,
        "per_question_v3": v3_df.to_dict(orient="records"),
        "v3_retrieval_summary": {
            "ce_floor_dropped_total": ce_dropped_total,
            "full_body_expanded_total": expanded_total,
            "ce_floor_dropped_avg": round(ce_dropped_total / len(golden), 2),
            "full_body_expanded_avg": round(expanded_total / len(golden), 2),
        },
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"ragas_v3_{timestamp}.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))

    # ── Comparison table ──────────────────────────────────────────────────────
    W = 100
    f4  = lambda x: f"{x:.4f}" if x is not None else "  N/A  "
    pct = lambda a, b: f"{(b - a) / a * 100:+.1f}%" if (a and b and a != 0) else "  N/A "

    print("\n" + "=" * W)
    print("  RAGAS — Pipeline Comparison  (30Q, golden_qa_v2.json)")
    print("=" * W)
    print(f"\n  {'Metric':<26} {'Naive':>10} {'v1':>10} {'v2':>10} {'v2+CE':>10} {'v3':>10} {'Δ v3 vs v2+CE':>14}")
    print("  " + "-" * (W - 2))

    for m in ("faithfulness", "answer_relevancy", "context_precision"):
        naive  = baselines["naive"].get(m)  if baselines["naive"]  else None
        v1     = baselines["v1"].get(m)     if baselines["v1"]     else None
        v2     = baselines["v2"].get(m)     if baselines["v2"]     else None
        v2_ce  = baselines["v2_ce"].get(m)  if baselines["v2_ce"]  else None
        v3     = v3_agg.get(m)
        print(
            f"  {m:<26} {f4(naive):>10} {f4(v1):>10} {f4(v2):>10} "
            f"{f4(v2_ce):>10} {f4(v3):>10} {pct(v2_ce, v3):>14}"
        )

    print("=" * W)
    print(f"\n  v3 retrieval: ce_floor_dropped avg={ce_dropped_total/len(golden):.1f}/q  "
          f"full_body_expanded avg={expanded_total/len(golden):.1f}/q")
    print(f"\n  Results → {out_path}")
    print("=" * W)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="RAGAS eval: v3 pipeline only, compare vs cached baselines")
    p.add_argument("--limit", type=int, default=5)
    p.add_argument("--judge", choices=["mistral", "ollama"], default="ollama")
    p.add_argument("--ollama-chat-model", default="qwen2.5:7b")
    p.add_argument("--ollama-embed-model", default="nomic-embed-text")
    p.add_argument("--answer-concurrency", type=int, default=1)
    p.add_argument("--workers", type=int, default=1)
    args = p.parse_args()
    asyncio.run(main(
        args.limit, args.judge, args.ollama_chat_model, args.ollama_embed_model,
        args.answer_concurrency, args.workers,
    ))
