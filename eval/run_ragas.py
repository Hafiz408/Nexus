"""RAGAS Evaluation Runner — compares graph-RAG vs naive vector-only retrieval.

Prerequisites:
  1. Backend FastAPI server must be running (pgvector, embeddings accessible).
  2. The target repository must be indexed: POST /index?repo_path=<EVAL_REPO_PATH>.
  3. Set environment variables:
       EVAL_REPO_PATH  — absolute path to the indexed repository (default: /fastapi)
       OPENAI_API_KEY  — valid OpenAI API key (also loaded from backend/.env)
  4. Run from any directory:
       python eval/run_ragas.py --repo-path /path/to/fastapi

Outputs (written to eval/results/):
  ragas_results_graph_rag_{timestamp}.json
  ragas_results_naive_vector_{timestamp}.json
  ragas_comparison_{timestamp}.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime

# Path fix — insert backend/ so app.* imports resolve from any working directory.
# Must use abspath(__file__) so this works regardless of cwd.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

import networkx as nx
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from ragas import EvaluationDataset, evaluate, RunConfig
from ragas.dataset_schema import SingleTurnSample
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import ContextPrecision, Faithfulness, ResponseRelevancy

from app.config import get_settings
from app.ingestion.graph_store import load_graph
from app.models.schemas import CodeNode
from app.retrieval.graph_rag import graph_rag_retrieve, semantic_search
from app.agent.explorer import explore_stream


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def get_answer(nodes: list[CodeNode], question: str) -> str:
    """Collect all streamed tokens from explore_stream into a single string."""
    tokens: list[str] = []
    async for token in explore_stream(nodes, question):
        tokens.append(token)
    return "".join(tokens)


def naive_retrieve(
    question: str,
    repo_path: str,
    G: nx.DiGraph,
    max_nodes: int = 10,
) -> list[CodeNode]:
    """Retrieve nodes using semantic search only (no graph expansion).

    Calls semantic_search to get (node_id, score) pairs, then hydrates
    CodeNode objects from the graph's node attributes.  Skips any node_id
    that is not present in G or whose attributes are malformed.
    """
    results = semantic_search(question, repo_path, top_k=max_nodes)
    nodes: list[CodeNode] = []
    for node_id, _score in results:
        if node_id not in G:
            continue
        try:
            attrs = G.nodes[node_id]
            node = CodeNode(**{k: v for k, v in attrs.items() if k in CodeNode.model_fields})
            nodes.append(node)
        except Exception:
            # Skip malformed node attributes — evaluation should not crash.
            continue
    return nodes


def build_contexts(nodes: list[CodeNode]) -> list[str]:
    """Format each CodeNode as a context string for RAGAS evaluation."""
    return [
        f"{n.file_path}:{n.line_start}-{n.line_end}\n{n.signature}\n{n.docstring or ''}\n{n.body_preview}"
        for n in nodes
    ]


# ---------------------------------------------------------------------------
# Main evaluation loop
# ---------------------------------------------------------------------------

async def main(repo_path: str) -> None:
    """Run dual-mode RAGAS evaluation and write timestamped JSON results."""

    # Step 1 — Load graph and golden dataset
    settings = get_settings()

    print(f"Loading graph for repo: {repo_path}")
    G = load_graph(repo_path)
    print(f"  Graph loaded: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    golden_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden_qa.json")
    with open(golden_path, "r", encoding="utf-8") as f:
        golden_qa: list[dict] = json.load(f)

    print(f"  Golden dataset: {len(golden_qa)} Q&A pairs loaded")

    # Step 2 — Build sample lists for both modes
    graph_samples: list[SingleTurnSample] = []
    naive_samples: list[SingleTurnSample] = []

    total = len(golden_qa)
    for i, entry in enumerate(golden_qa, start=1):
        question: str = entry["question"]
        reference: str = entry["ground_truth"]
        qid: str = entry.get("id", f"Q{i:02d}")

        print(f"[{i}/{total}] {qid}: {question[:60]}...")

        # Graph-RAG path
        graph_nodes, _stats = graph_rag_retrieve(
            question, repo_path, G, max_nodes=10, hop_depth=1
        )
        graph_response = await get_answer(graph_nodes, question)
        graph_samples.append(
            SingleTurnSample(
                user_input=question,
                retrieved_contexts=build_contexts(graph_nodes),
                response=graph_response,
                reference=reference,
            )
        )

        # Naive vector-only path
        naive_nodes = naive_retrieve(question, repo_path, G, max_nodes=10)
        naive_response = await get_answer(naive_nodes, question)
        naive_samples.append(
            SingleTurnSample(
                user_input=question,
                retrieved_contexts=build_contexts(naive_nodes),
                response=naive_response,
                reference=reference,
            )
        )

    # Step 3 — Set up RAGAS evaluator
    # Always pass llm= explicitly; never use metric singletons (old ragas API).
    evaluator_llm = LangchainLLMWrapper(
        ChatOpenAI(model="gpt-4o-mini", temperature=0, api_key=settings.openai_api_key)
    )
    evaluator_embeddings = LangchainEmbeddingsWrapper(
        OpenAIEmbeddings(model="text-embedding-3-small", api_key=settings.openai_api_key)
    )
    metrics = [
        Faithfulness(llm=evaluator_llm),
        ResponseRelevancy(llm=evaluator_llm, embeddings=evaluator_embeddings),
        ContextPrecision(llm=evaluator_llm),
    ]
    run_config = RunConfig(timeout=120, max_retries=3)

    # Step 4 — Evaluate both modes and write per-mode result files
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(results_dir, exist_ok=True)

    all_aggregates: dict[str, dict] = {}

    for mode, samples in [("graph_rag", graph_samples), ("naive_vector", naive_samples)]:
        print(f"\nEvaluating mode: {mode} ({len(samples)} samples)...")
        dataset = EvaluationDataset(samples=samples)
        results = evaluate(
            dataset=dataset,
            metrics=metrics,
            run_config=run_config,
            show_progress=True,
            raise_exceptions=False,
        )
        df = results.to_pandas()

        # Column name map — ragas 0.4.x has minor-version variation in column names.
        # Match by substring (case-insensitive) to handle answer_relevancy vs response_relevancy.
        col_map: dict[str, str | None] = {
            "faithfulness": None,
            "answer_relevancy": None,
            "response_relevancy": None,
            "context_precision": None,
        }
        for col in df.columns:
            for key in col_map:
                if key in col.lower():
                    col_map[key] = col

        def safe_mean(col_key: str) -> float | None:
            col_name = col_map.get(col_key)
            if col_name is None or col_name not in df.columns:
                return None
            series = df[col_name].dropna()
            if series.empty:
                return None
            return float(series.mean())

        aggregate = {
            "faithfulness": safe_mean("faithfulness"),
            "answer_relevancy": safe_mean("answer_relevancy") or safe_mean("response_relevancy"),
            "context_precision": safe_mean("context_precision"),
        }

        output = {
            "timestamp": timestamp,
            "mode": mode,
            "repo_path": repo_path,
            "aggregate": aggregate,
            "per_question": df.to_dict(orient="records"),
        }

        out_path = os.path.join(results_dir, f"ragas_results_{mode}_{timestamp}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, default=str)
        print(f"  Written: {out_path}")

        all_aggregates[mode] = aggregate

    # Step 5 — Write comparison file and print summary table
    def _winner(metric: str) -> str | None:
        g = all_aggregates.get("graph_rag", {}).get(metric)
        n = all_aggregates.get("naive_vector", {}).get(metric)
        if g is None or n is None:
            return None
        return "graph_rag" if g >= n else "naive_vector"

    comparison = {
        "timestamp": timestamp,
        "repo_path": repo_path,
        "graph_rag": all_aggregates.get("graph_rag", {}),
        "naive_vector": all_aggregates.get("naive_vector", {}),
        "winner": {
            metric: _winner(metric)
            for metric in ("faithfulness", "answer_relevancy", "context_precision")
            if _winner(metric) is not None
        },
    }

    comp_path = os.path.join(results_dir, f"ragas_comparison_{timestamp}.json")
    with open(comp_path, "w", encoding="utf-8") as f:
        json.dump(comparison, f, indent=2, default=str)
    print(f"\nComparison written: {comp_path}")

    # Print summary table
    g_agg = all_aggregates.get("graph_rag", {})
    n_agg = all_aggregates.get("naive_vector", {})
    metrics_names = ["faithfulness", "answer_relevancy", "context_precision"]

    print("\n" + "=" * 68)
    print(f"{'Metric':<22} {'graph_rag':>12} {'naive_vector':>14} {'winner':>14}")
    print("=" * 68)
    for metric in metrics_names:
        g_val = g_agg.get(metric)
        n_val = n_agg.get(metric)
        winner = comparison["winner"].get(metric, "N/A")
        g_str = f"{g_val:.4f}" if g_val is not None else "N/A"
        n_str = f"{n_val:.4f}" if n_val is not None else "N/A"
        print(f"{metric:<22} {g_str:>12} {n_str:>14} {winner:>14}")
    print("=" * 68)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run RAGAS evaluation for Nexus")
    parser.add_argument(
        "--repo-path",
        default=os.environ.get("EVAL_REPO_PATH", "/fastapi"),
        help="Absolute path to the indexed repository (default: EVAL_REPO_PATH env var or /fastapi)",
    )
    args = parser.parse_args()
    asyncio.run(main(args.repo_path))
