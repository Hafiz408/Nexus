"""Three-way RAGAS evaluation: naive | graph_rag | improved.

Evaluates against eval/golden_qa_v2.json (30 code-navigation questions).

Pipelines:
  naive    — semantic_search only, top-15, no FTS, no BFS, no reranking
  graph    — graph_rag_retrieve (FTS + BFS + MMR, current production baseline)
  improved — improved_graph_rag_retrieve (HyDE + RRF + BFS-threshold + cross-encoder)

Usage:
    # Quick sanity check — 5 questions
    python eval/run_ragas_three_way.py --limit 5

    # Full 30-question eval, 2 Ollama workers (~3-4 hours)
    OLLAMA_NUM_PARALLEL=2 python eval/run_ragas_three_way.py --limit 30 --workers 2

    # Mistral judge (faster scoring, requires MISTRAL_API_KEY)
    python eval/run_ragas_three_way.py --limit 30 --judge mistral
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
from app.retrieval.graph_rag import semantic_search, graph_rag_retrieve
from app.retrieval.improved_rag import improved_graph_rag_retrieve
from app.agent.explorer import explore_stream

REPO_PATH = "/Users/mohammedhafiz/Desktop/Personal/fastapi"
DB_PATH = REPO_PATH + "/.nexus/graph.db"
GOLDEN_PATH = Path(__file__).parent / "golden_qa_v2.json"
MAX_NODES = 15


# ─── Retrieval helpers ────────────────────────────────────────────────────────

def naive_retrieve(
    query: str,
    G,
    max_nodes: int = MAX_NODES,
) -> tuple[list[CodeNode], dict]:
    """Semantic-only retrieval: cosine NN, no FTS, no BFS, no reranking.

    Hydrates CodeNode objects from the graph (same source as graph_rag_retrieve)
    so the context format is identical across all three pipelines.
    """
    results = semantic_search(query, REPO_PATH, top_k=max_nodes, db_path=DB_PATH)
    nodes: list[CodeNode] = []
    for node_id, _ in results:
        if node_id not in G:
            continue
        attrs = G.nodes[node_id]
        try:
            node = CodeNode(**{k: v for k, v in attrs.items() if k in CodeNode.model_fields})
            nodes.append(node)
        except Exception:
            pass
    return nodes, {"returned_count": len(nodes), "pipeline": "naive"}


def build_contexts(nodes: list[CodeNode]) -> list[str]:
    return [
        f"{n.file_path}:{n.line_start}-{n.line_end}\n"
        f"{n.signature or ''}\n{n.docstring or ''}\n{n.body_preview or ''}"
        for n in nodes
    ]


# ─── Answer generation ────────────────────────────────────────────────────────

async def get_answer(nodes: list[CodeNode], question: str) -> str:
    for attempt in range(6):
        try:
            return "".join([t async for t in explore_stream(nodes, question)])
        except Exception as e:
            s = str(e).lower()
            if "429" in str(e) or "rate" in s or "capacity" in s or "timeout" in s or "connect" in s:
                wait = 15 * (attempt + 1)
                print(f"    [llm error, retry {attempt+1}/6, wait {wait}s]: {type(e).__name__}")
                await asyncio.sleep(wait)
            else:
                raise
    print(f"    [WARNING] get_answer exhausted all retries — returning empty string for question")
    return ""


# ─── Per-question evaluation ─────────────────────────────────────────────────

async def run_question(
    sem: asyncio.Semaphore,
    i: int,
    total: int,
    entry: dict,
    G,
) -> tuple:
    """Retrieve + answer for all three pipelines on one question.

    Returns (naive_sample, graph_sample, improved_sample,
             naive_stat, graph_stat, improved_stat).
    """
    q, ref = entry["question"], entry["ground_truth"]
    qid = entry.get("id", f"Q{i:02d}")

    # Retrieval (fast, outside semaphore)
    naive_nodes = naive_stat = graph_nodes = graph_stat = improved_nodes = improved_stat = None
    for attempt in range(5):
        try:
            naive_nodes, naive_stat = naive_retrieve(q, G)
            graph_nodes, graph_stat = graph_rag_retrieve(
                q, REPO_PATH, G, DB_PATH, max_nodes=MAX_NODES, hop_depth=1
            )
            improved_nodes, improved_stat = await improved_graph_rag_retrieve(
                q, REPO_PATH, G, DB_PATH, max_nodes=MAX_NODES, hop_depth=1
            )
            break
        except Exception as e:
            s = str(e).lower()
            if "429" in str(e) or "capacity" in s or "timeout" in s or "connect" in s:
                print(f"  [{qid}] retrieval error, retry {attempt+1}/5: {type(e).__name__}")
                await asyncio.sleep(30)
            else:
                raise
    else:
        raise RuntimeError(f"[{qid}] retrieval failed after 5 retries — aborting")

    # Answer generation (gated by semaphore to avoid LLM overload)
    async with sem:
        print(f"[{i}/{total}] {qid}: {q[:65]}...")
        naive_ans, graph_ans, improved_ans = await asyncio.gather(
            get_answer(naive_nodes, q),
            get_answer(graph_nodes, q),
            get_answer(improved_nodes, q),
        )

    def _sample(nodes, ans):
        return SingleTurnSample(
            user_input=q, retrieved_contexts=build_contexts(nodes),
            response=ans, reference=ref,
        )

    naive_stat.update({"qid": qid})
    graph_stat.update({"qid": qid})
    improved_stat.update({"qid": qid})

    return (
        _sample(naive_nodes, naive_ans),
        _sample(graph_nodes, graph_ans),
        _sample(improved_nodes, improved_ans),
        naive_stat, graph_stat, improved_stat,
    )


# ─── Scoring ──────────────────────────────────────────────────────────────────

def score_pipeline(samples, metrics, run_config, name):
    print(f"\nScoring {name} ({len(samples)} samples)...")
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

    agg = {
        "faithfulness": _mean("faithfulness"),
        "answer_relevancy": (lambda x: x if x is not None else _mean("response_relevancy"))(_mean("answer_relevancy")),
        "context_precision": _mean("context_precision"),
    }
    return agg, df


# ─── Main ────────────────────────────────────────────────────────────────────

async def main(limit, judge, ollama_chat, ollama_embed, answer_concurrency, workers):
    print(f"\nNexus RAGAS — Three-Way Evaluation")
    print(f"  corpus : {REPO_PATH}")
    print(f"  golden : {GOLDEN_PATH.name}")

    print("Loading graph...")
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

    def _metrics():
        return [Faithfulness(llm=llm), ResponseRelevancy(llm=llm, embeddings=emb), ContextPrecision(llm=llm)]

    sem = asyncio.Semaphore(answer_concurrency)
    all_results = await asyncio.gather(*[
        run_question(sem, i, len(golden), entry, G)
        for i, entry in enumerate(golden, 1)
    ])

    naive_samples  = [r[0] for r in all_results]
    graph_samples  = [r[1] for r in all_results]
    imprv_samples  = [r[2] for r in all_results]
    naive_stats    = [r[3] for r in all_results]
    graph_stats    = [r[4] for r in all_results]
    imprv_stats    = [r[5] for r in all_results]

    naive_agg, naive_df = score_pipeline(naive_samples,  _metrics(), run_cfg, "naive")
    graph_agg, graph_df = score_pipeline(graph_samples,  _metrics(), run_cfg, "graph_rag")
    imprv_agg, imprv_df = score_pipeline(imprv_samples,  _metrics(), run_cfg, "improved")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = {
        "timestamp": timestamp,
        "repo_path": REPO_PATH,
        "golden_qa": "golden_qa_v2.json",
        "questions": len(golden),
        "naive": naive_agg,
        "graph_rag": graph_agg,
        "improved": imprv_agg,
        "retrieval_stats": {
            "naive": naive_stats, "graph": graph_stats, "improved": imprv_stats,
        },
        "per_question": {
            "naive": naive_df.to_dict(orient="records"),
            "graph": graph_df.to_dict(orient="records"),
            "improved": imprv_df.to_dict(orient="records"),
        },
    }
    out_path = Path(__file__).parent / "results" / f"ragas_three_way_{timestamp}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, default=str))

    # ── Print comparison table ────────────────────────────────────────────────
    W = 90
    print("\n" + "=" * W)
    print("  RAGAS THREE-WAY COMPARISON  —  golden_qa_v2.json")
    print("=" * W)
    header = f"  {'Metric':<26} {'Naive':>10} {'Graph RAG':>11} {'Improved':>11} {'Δ N→I':>9} {'Δ G→I':>9}"
    print(header)
    print("-" * W)
    for m in ("faithfulness", "answer_relevancy", "context_precision"):
        n = naive_agg.get(m)
        g = graph_agg.get(m)
        v = imprv_agg.get(m)
        f = lambda x: f"{x:.4f}" if x is not None else "  N/A"
        pct = lambda a, b: f"{(b-a)/a*100:+.1f}%" if (a is not None and b is not None and a != 0) else "  N/A"
        print(f"  {m:<26} {f(n):>10} {f(g):>11} {f(v):>11} {pct(n,v):>9} {pct(g,v):>9}")
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
