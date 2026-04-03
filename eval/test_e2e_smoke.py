"""End-to-end smoke test for Graph RAG v2 against the fastapi corpus.

Verifies that graph_rag_retrieve completes without error, returns at least
one CodeNode, and produces a stats dict with all expected keys.

No LLM is invoked — retrieval only, so no API keys are required.

Usage:
    python eval/test_e2e_smoke.py

Exit codes:
    0 — all checks passed
    1 — one or more checks failed (details printed to stdout)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

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

REPO_PATH = "/Users/mohammedhafiz/Desktop/Personal/fastapi"
DB_PATH = REPO_PATH + "/.nexus/graph.db"

EXPECTED_STATS_KEYS = {
    "seed_count",
    "semantic_seeds",
    "fts_seeds",
    "fts_new",
    "neighbor_count",
    "candidate_pool",
    "returned_count",
    "cross_encoder_used",
}

# Queries chosen for high expected recall against the fastapi corpus
SMOKE_QUERIES = [
    "How does FastAPI handle dependency injection?",
    "Where is the routing registered?",
    "How are request body parameters validated?",
]

GREEN = "\033[92m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"


def check(label: str, condition: bool, detail: str = "") -> bool:
    mark = f"{GREEN}PASS{RESET}" if condition else f"{RED}FAIL{RESET}"
    suffix = f"  ({detail})" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    return condition


def run_smoke() -> bool:
    from app.ingestion.graph_store import load_graph
    from app.retrieval.graph_rag import graph_rag_retrieve

    print(f"\n{BOLD}Loading graph …{RESET}")
    if not Path(DB_PATH).exists():
        print(f"{RED}ERROR:{RESET} database not found at {DB_PATH}")
        print("  Run 'Nexus: Index Workspace' against the fastapi repo first.")
        return False

    G = load_graph(REPO_PATH, DB_PATH)
    node_count = G.number_of_nodes()
    edge_count = G.number_of_edges()
    print(f"  graph loaded: {node_count} nodes, {edge_count} edges")

    if not check("graph is non-empty", node_count > 0, f"{node_count} nodes"):
        return False

    all_passed = True
    ce_used_any = False

    for query in SMOKE_QUERIES:
        print(f"\n{BOLD}Query:{RESET} {query}")
        try:
            nodes, stats = graph_rag_retrieve(
                query, REPO_PATH, G, DB_PATH, max_nodes=10, hop_depth=1
            )
        except Exception as exc:
            print(f"  {RED}EXCEPTION:{RESET} {type(exc).__name__}: {exc}")
            all_passed = False
            continue

        ok = True
        ok &= check("returns at least 1 node", len(nodes) >= 1, f"got {len(nodes)}")
        ok &= check(
            "stats has all expected keys",
            EXPECTED_STATS_KEYS.issubset(stats.keys()),
            f"missing: {EXPECTED_STATS_KEYS - stats.keys() or 'none'}",
        )
        ok &= check(
            "returned_count matches len(nodes)",
            stats["returned_count"] == len(nodes),
            f"stats={stats['returned_count']} len={len(nodes)}",
        )
        ok &= check(
            "candidate_pool >= returned_count",
            stats["candidate_pool"] >= stats["returned_count"],
            f"pool={stats['candidate_pool']} returned={stats['returned_count']}",
        )
        ok &= check(
            "all nodes have file_path",
            all(n.file_path for n in nodes),
            "",
        )
        ok &= check(
            "cross_encoder_used key present in stats",
            "cross_encoder_used" in stats,
            "",
        )

        if stats.get("cross_encoder_used"):
            ce_used_any = True

        if ok:
            top = nodes[0]
            print(
                f"  top result: {top.name} ({top.file_path}:{top.line_start})"
                f"  seeds={stats['seed_count']} neighbors={stats['neighbor_count']}"
                f" pool={stats['candidate_pool']} returned={stats['returned_count']}"
                f" ce={stats.get('cross_encoder_used')}"
            )
        else:
            all_passed = False

    print(f"\n{BOLD}Cross-encoder summary:{RESET}")
    ce_ok = check(
        "cross_encoder_used is True for at least one query",
        ce_used_any,
        "CE ran on at least one query" if ce_used_any else "CE was not used on any query",
    )
    if not ce_ok:
        all_passed = False

    return all_passed


if __name__ == "__main__":
    passed = run_smoke()
    print()
    if passed:
        print(f"{GREEN}{BOLD}All smoke checks passed.{RESET}")
        sys.exit(0)
    else:
        print(f"{RED}{BOLD}One or more smoke checks failed.{RESET}")
        sys.exit(1)
