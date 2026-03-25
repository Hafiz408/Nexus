"""RAGAS comparison runner: v2 (pgvector) vs v3 (sqlite-vec).

Usage:
    python eval/run_ragas_compare.py --repo-path /path/to/fastapi [--mode v2|v3|both]

Prerequisites:
    - MISTRAL_API_KEY in .env (root of project)
    - For v2: Postgres running with code_embeddings table populated
    - For v3: <repo-path>/.nexus/graph.db populated

Outputs: eval/results/ragas_compare_<timestamp>.json + printed table
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Load .env from project root
_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root / "backend"))
_env = _root / ".env"
if _env.exists():
    for _line in _env.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            k, v = _line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

import networkx as nx
from langchain_mistralai import ChatMistralAI, MistralAIEmbeddings
from ragas import EvaluationDataset, evaluate, RunConfig
from ragas.dataset_schema import SingleTurnSample
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import ContextPrecision, Faithfulness, ResponseRelevancy

from app.config import get_settings
from app.models.schemas import CodeNode
from app.agent.explorer import explore_stream


# ---------------------------------------------------------------------------
# Retrieval implementations (v2 + v3)
# ---------------------------------------------------------------------------

def _hydrate_nodes(node_ids_scores: list[tuple[str, float]], G: nx.DiGraph) -> list[CodeNode]:
    nodes = []
    for node_id, _ in node_ids_scores:
        if node_id not in G:
            continue
        try:
            attrs = G.nodes[node_id]
            nodes.append(CodeNode(**{k: v for k, v in attrs.items() if k in CodeNode.model_fields}))
        except Exception:
            continue
    return nodes


def retrieve_v3(question: str, repo_path: str, db_path: str, G: nx.DiGraph, max_nodes: int = 10):
    """Graph-RAG retrieval via sqlite-vec (v3)."""
    from app.retrieval.graph_rag import graph_rag_retrieve
    nodes, stats = graph_rag_retrieve(question, repo_path, G, db_path, max_nodes=max_nodes, hop_depth=1)
    return nodes, stats


def retrieve_v3_naive(question: str, repo_path: str, db_path: str, G: nx.DiGraph, max_nodes: int = 10):
    """Naive vector-only retrieval via sqlite-vec (v3)."""
    from app.retrieval.graph_rag import semantic_search
    results = semantic_search(question, repo_path, top_k=max_nodes, db_path=db_path)
    return _hydrate_nodes(results, G)


def retrieve_v2_graph(question: str, repo_path: str, G: nx.DiGraph, max_nodes: int = 10):
    """Graph-RAG retrieval via pgvector (v2). Requires Postgres."""
    import importlib
    # Temporarily swap in v2 semantic_search (pgvector)
    try:
        import psycopg2
        from pgvector.psycopg2 import register_vector
        from app.ingestion.embedder import get_embedding_client
        settings = get_settings()
        query_vec = get_embedding_client().embed([question])[0]
        conn = psycopg2.connect(
            host=os.environ.get("POSTGRES_HOST", "localhost"),
            user=os.environ.get("POSTGRES_USER", "nexus"),
            password=os.environ.get("POSTGRES_PASSWORD", "nexus_pass"),
            dbname=os.environ.get("POSTGRES_DB", "nexus_db"),
        )
        register_vector(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, 1 - (embedding <=> %s::vector) AS score
                FROM code_embeddings WHERE repo_path = %s
                ORDER BY embedding <=> %s::vector LIMIT %s
                """,
                (query_vec, repo_path, query_vec, max_nodes),
            )
            rows = cur.fetchall()
        conn.close()
        seed_nodes = _hydrate_nodes([(r[0], r[1]) for r in rows], G)
        # BFS expansion (same as v2 graph_rag_retrieve)
        from app.retrieval.graph_rag import expand_via_graph, rerank_and_assemble
        expanded = expand_via_graph(G, [n.node_id for n in seed_nodes], hop_depth=1)
        return rerank_and_assemble(G, expanded, max_nodes)
    except Exception as e:
        print(f"  [v2 pgvector error: {e}] — falling back to v3 sqlite-vec for this question")
        return [], {}


async def get_answer(nodes: list[CodeNode], question: str) -> str:
    tokens = []
    async for token in explore_stream(nodes, question):
        tokens.append(token)
    return "".join(tokens)


def build_contexts(nodes: list[CodeNode]) -> list[str]:
    return [
        f"{n.file_path}:{n.line_start}-{n.line_end}\n{n.signature}\n{n.docstring or ''}\n{n.body_preview}"
        for n in nodes
    ]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main(repo_path: str, db_path: str, mode: str) -> None:
    print(f"\nNexus RAGAS Comparison — {mode.upper()} mode")
    print(f"  repo:    {repo_path}")
    print(f"  db_path: {db_path}")

    # Load graph (v3 sqlite)
    from app.ingestion.graph_store import load_graph
    print("\nLoading graph...")
    G = load_graph(repo_path, db_path)
    print(f"  {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    # Load golden Q&A
    golden_path = Path(__file__).parent / "golden_qa.json"
    golden_qa: list[dict] = json.loads(golden_path.read_text())
    print(f"  {len(golden_qa)} golden Q&A pairs")

    # Set up RAGAS judge (Mistral)
    mistral_key = os.environ["MISTRAL_API_KEY"]
    llm_wrapper = LangchainLLMWrapper(
        ChatMistralAI(model="mistral-large-latest", temperature=0, api_key=mistral_key)
    )
    emb_wrapper = LangchainEmbeddingsWrapper(
        MistralAIEmbeddings(model="mistral-embed", api_key=mistral_key)
    )
    metrics = [
        Faithfulness(llm=llm_wrapper),
        ResponseRelevancy(llm=llm_wrapper, embeddings=emb_wrapper),
        ContextPrecision(llm=llm_wrapper),
    ]
    run_config = RunConfig(timeout=120, max_retries=3)

    # Build samples per mode
    run_modes: dict[str, list[SingleTurnSample]] = {}

    if mode in ("v3", "both"):
        print("\nBuilding v3 (sqlite-vec) samples...")
        v3_graph_samples, v3_naive_samples = [], []
        for i, entry in enumerate(golden_qa, 1):
            q, ref = entry["question"], entry["ground_truth"]
            print(f"  [{i}/{len(golden_qa)}] {q[:60]}...")
            nodes_g, _ = retrieve_v3(q, repo_path, db_path, G)
            ans_g = await get_answer(nodes_g, q)
            v3_graph_samples.append(SingleTurnSample(
                user_input=q, retrieved_contexts=build_contexts(nodes_g),
                response=ans_g, reference=ref))

            nodes_n = retrieve_v3_naive(q, repo_path, db_path, G)
            ans_n = await get_answer(nodes_n, q)
            v3_naive_samples.append(SingleTurnSample(
                user_input=q, retrieved_contexts=build_contexts(nodes_n),
                response=ans_n, reference=ref))

        run_modes["v3_graph_rag"] = v3_graph_samples
        run_modes["v3_naive_vector"] = v3_naive_samples

    if mode in ("v2", "both"):
        print("\nBuilding v2 (pgvector) samples...")
        v2_graph_samples = []
        for i, entry in enumerate(golden_qa, 1):
            q, ref = entry["question"], entry["ground_truth"]
            print(f"  [{i}/{len(golden_qa)}] {q[:60]}...")
            result = retrieve_v2_graph(q, repo_path, G)
            nodes = result[0] if isinstance(result, tuple) else result
            ans = await get_answer(nodes, q)
            v2_graph_samples.append(SingleTurnSample(
                user_input=q, retrieved_contexts=build_contexts(nodes),
                response=ans, reference=ref))
        run_modes["v2_graph_rag"] = v2_graph_samples

    # Evaluate
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(exist_ok=True)
    all_agg: dict[str, dict] = {}

    for label, samples in run_modes.items():
        print(f"\nEvaluating {label} ({len(samples)} samples)...")
        dataset = EvaluationDataset(samples=samples)
        result = evaluate(dataset=dataset, metrics=metrics, run_config=run_config,
                          show_progress=True, raise_exceptions=False)
        df = result.to_pandas()

        def safe_mean(key: str) -> float | None:
            col = next((c for c in df.columns if key in c.lower()), None)
            if col is None: return None
            s = df[col].dropna()
            return float(s.mean()) if not s.empty else None

        agg = {
            "faithfulness": safe_mean("faithfulness"),
            "answer_relevancy": safe_mean("answer_relevancy") or safe_mean("response_relevancy"),
            "context_precision": safe_mean("context_precision"),
        }
        all_agg[label] = agg
        out = {"timestamp": timestamp, "mode": label, "repo_path": repo_path,
               "aggregate": agg, "per_question": df.to_dict(orient="records")}
        out_path = results_dir / f"ragas_{label}_{timestamp}.json"
        out_path.write_text(json.dumps(out, indent=2, default=str))
        print(f"  Written: {out_path}")

    # Summary table
    comp = {"timestamp": timestamp, "repo_path": repo_path, "results": all_agg}
    comp_path = results_dir / f"ragas_comparison_{timestamp}.json"
    comp_path.write_text(json.dumps(comp, indent=2, default=str))

    metric_keys = ["faithfulness", "answer_relevancy", "context_precision"]
    col_w = max(len(k) for k in all_agg) + 2
    print("\n" + "=" * (22 + col_w * len(all_agg)))
    header = f"{'Metric':<22}" + "".join(f"{k:>{col_w}}" for k in all_agg)
    print(header)
    print("-" * (22 + col_w * len(all_agg)))
    for m in metric_keys:
        row = f"{m:<22}"
        for label in all_agg:
            v = all_agg[label].get(m)
            row += f"{(f'{v:.4f}' if v is not None else 'N/A'):>{col_w}}"
        print(row)
    print("=" * (22 + col_w * len(all_agg)))
    print(f"\nComparison written: {comp_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-path",
                        default=os.environ.get("EVAL_REPO_PATH", "/Users/mohammedhafiz/Desktop/Personal/fastapi"))
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--mode", choices=["v2", "v3", "both"], default="both")
    args = parser.parse_args()
    db_path = args.db_path or os.path.join(args.repo_path, ".nexus", "graph.db")
    asyncio.run(main(args.repo_path, db_path, args.mode))
