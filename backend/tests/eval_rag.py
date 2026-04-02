"""
RAG Accuracy Evaluation — eval_rag.py

Runs a fixed question bank against the live /query endpoint and scores
each answer on:
  - ANSWERED: did the model give a real answer (not hedge)?
  - CORRECT:  does the answer contain the expected keywords?
  - CITED:    was the expected source file in the citations?

Usage:
  python tests/eval_rag.py --repo /Users/mohammedhafiz/Desktop/Personal/super_tutor
  python tests/eval_rag.py --repo /path/to/repo --url http://localhost:8000

Output: coloured table + JSON results file at eval_results.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from dataclasses import dataclass, field

# ── Colours (works in most terminals) ────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"


# ── Question bank ─────────────────────────────────────────────────────────────
# Each entry:
#   question        - what we ask
#   expected_kws    - list of strings; answer must contain ALL to be CORRECT
#                     (case-insensitive substring match)
#   expected_file   - filename substring expected somewhere in citations
#   category        - "factual" | "architectural" | "count" | "flow"

QUESTIONS = [
    # ── Factual / config ─────────────────────────────────────────────────────
    {
        "question": "Where is the model provider configured?",
        "expected_kws": ["config.py", "agent_provider"],
        "expected_file": "config.py",
        "category": "factual",
    },
    {
        "question": "What is the default agent model?",
        "expected_kws": ["gpt-4o"],
        "expected_file": "config.py",
        "category": "factual",
    },
    {
        "question": "What database does the backend use for session history?",
        "expected_kws": ["sqlite"],
        "expected_file": "tutor_team.py",
        "category": "factual",
    },
    # ── Count questions (the hard ones — test body_preview fix) ──────────────
    {
        "question": "How many members does the agent team have?",
        "expected_kws": ["5, five"],            # comma = OR: "5" or "five"
        "expected_file": "tutor_team.py",
        "category": "count",
    },
    {
        "question": "How many agents are in the TutorTeam?",
        "expected_kws": ["5, five"],
        "expected_file": "tutor_team.py",
        "category": "count",
    },
    # ── Architectural ─────────────────────────────────────────────────────────
    {
        "question": "What is the role of the Explainer agent?",
        "expected_kws": ["question", "material"],
        "expected_file": "tutor_team.py",
        "category": "architectural",
    },
    {
        "question": "What guardrails are applied to the tutor team?",
        "expected_kws": ["TopicRelevance", "guardrail"],
        "expected_file": "guardrails.py",
        "category": "architectural",
    },
    {
        "question": "How does the get_model function decide which provider to use?",
        "expected_kws": ["agent_provider", "settings"],
        "expected_file": "model_factory.py",
        "category": "architectural",
    },
    # ── Flow ─────────────────────────────────────────────────────────────────
    {
        "question": "How does session history get passed to member agents?",
        "expected_kws": ["session_state, add_session_state_to_context, add_history_to_context"],
        "expected_file": "tutor_team.py",
        "category": "flow",
    },
    {
        "question": "What SSE events does the tutor router emit?",
        "expected_kws": ["token", "done"],
        "expected_file": "tutor_team.py",
        "category": "flow",
    },
]

HEDGE_PHRASES = [
    "i'm not certain",
    "i don't know",
    "not enough information",
    "cannot determine",
    "not available in",
    "unable to find",
    "no information",
    "i cannot answer",
]


# ── SSE query helper ──────────────────────────────────────────────────────────
def query(question: str, repo_path: str, base_url: str, timeout: int = 45, db_path: str = "") -> dict:
    """Send a /query request and collect the full SSE response."""
    payload = json.dumps({
        "question": question,
        "repo_path": repo_path,
        "db_path": db_path or f"{repo_path}/.nexus/graph.db",
        "max_nodes": 15,
        "hop_depth": 1,
    }).encode()

    req = urllib.request.Request(
        f"{base_url}/query",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    tokens: list[str] = []
    citations: list[dict] = []
    error: str | None = None

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8").rstrip("\n")
                if not line.startswith("data:"):
                    continue
                try:
                    event = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                t = event.get("type")
                if t == "token":
                    tokens.append(event.get("content", ""))
                elif t == "citations":
                    citations = event.get("citations", [])
                elif t == "error":
                    error = event.get("message", "unknown error")
    except Exception as e:
        error = str(e)

    return {
        "answer": "".join(tokens),
        "citations": citations,
        "error": error,
    }


# ── Scoring ───────────────────────────────────────────────────────────────────
@dataclass
class Result:
    question: str
    category: str
    answer: str
    citations: list[dict]
    error: str | None
    answered: bool = False
    correct: bool = False
    cited: bool = False
    matched_kws: list[str] = field(default_factory=list)
    missing_kws: list[str] = field(default_factory=list)
    latency_s: float = 0.0


def score_result(r: Result, q: dict) -> None:
    answer_lo = r.answer.lower()

    # ANSWERED: non-empty, not a hedge
    r.answered = bool(r.answer.strip()) and not any(
        h in answer_lo for h in HEDGE_PHRASES
    )

    # CORRECT: all expected keywords present (OR logic for list items separated by commas)
    for kw_group in q["expected_kws"]:
        # Each item in expected_kws can be a comma-separated OR list
        alternatives = [k.strip().lower() for k in kw_group.split(",")]
        if any(alt in answer_lo for alt in alternatives):
            r.matched_kws.append(kw_group)
        else:
            r.missing_kws.append(kw_group)
    r.correct = r.answered and len(r.missing_kws) == 0

    # CITED: expected file appears in any citation file_path
    exp_file = q.get("expected_file", "")
    if exp_file:
        r.cited = any(exp_file in c.get("file_path", "") for c in r.citations)


def status_icon(val: bool) -> str:
    return f"{GREEN}✓{RESET}" if val else f"{RED}✗{RESET}"


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="RAG accuracy evaluator")
    parser.add_argument("--repo", required=True, help="Indexed repo path")
    parser.add_argument("--url", default="http://localhost:8000", help="Backend base URL")
    parser.add_argument("--timeout", type=int, default=45, help="Per-query timeout (s)")
    parser.add_argument("--db-path", default="", dest="db_path", help="Path to .nexus/graph.db (default: <repo>/.nexus/graph.db)")
    args = parser.parse_args()

    print(f"\n{BOLD}{CYAN}Nexus RAG Evaluation{RESET}")
    print(f"Repo : {args.repo}")
    print(f"API  : {args.url}")
    print(f"Tests: {len(QUESTIONS)}\n")

    results: list[Result] = []

    for i, q in enumerate(QUESTIONS, 1):
        cat_label = f"[{q['category']:12s}]"
        print(f"  {i:2d}/{len(QUESTIONS)} {CYAN}{cat_label}{RESET} {q['question'][:60]}", end=" ", flush=True)

        t0 = time.time()
        raw = query(q["question"], args.repo, args.url, args.timeout, getattr(args, "db_path", ""))
        latency = time.time() - t0

        r = Result(
            question=q["question"],
            category=q["category"],
            answer=raw["answer"],
            citations=raw["citations"],
            error=raw["error"],
            latency_s=round(latency, 1),
        )
        score_result(r, q)
        results.append(r)

        if raw["error"]:
            print(f"{RED}ERROR: {raw['error'][:60]}{RESET}")
        else:
            icons = f"answered={status_icon(r.answered)} correct={status_icon(r.correct)} cited={status_icon(r.cited)}"
            print(f"{icons}  ({latency:.1f}s)")

    # ── Summary table ─────────────────────────────────────────────────────────
    total      = len(results)
    n_answered = sum(r.answered for r in results)
    n_correct  = sum(r.correct  for r in results)
    n_cited    = sum(r.cited    for r in results)

    print(f"\n{BOLD}{'─'*72}{RESET}")
    print(f"{BOLD}Results{RESET}")
    print(f"{'─'*72}")
    print(f"  {'#':<3} {'Cat':12} {'A':1} {'C':1} {'F':1}  {'Answer (truncated)':45}")
    print(f"{'─'*72}")

    for i, r in enumerate(results, 1):
        a_icon = "✓" if r.answered else "✗"
        c_icon = "✓" if r.correct  else "✗"
        f_icon = "✓" if r.cited    else "✗"
        colour = GREEN if r.correct else (YELLOW if r.answered else RED)
        ans_short = r.answer[:45].replace("\n", " ") if r.answer else (r.error or "—")[:45]
        print(f"  {colour}{i:<3} {r.category:12} {a_icon} {c_icon} {f_icon}  {ans_short}{RESET}")

    print(f"{'─'*72}")
    print(f"  Score: answered {n_answered}/{total} ({100*n_answered//total}%)  "
          f"correct {n_correct}/{total} ({100*n_correct//total}%)  "
          f"cited {n_cited}/{total} ({100*n_cited//total}%)")
    print(f"{'─'*72}\n")

    # ── Failures detail ───────────────────────────────────────────────────────
    failures = [r for r in results if not r.correct]
    if failures:
        print(f"{BOLD}Failures{RESET}")
        for r in failures:
            print(f"\n  {RED}✗{RESET} {r.question}")
            if r.error:
                print(f"    Error   : {r.error}")
            else:
                print(f"    Answer  : {r.answer[:120].replace(chr(10),' ')}")
                if r.missing_kws:
                    print(f"    Missing : {', '.join(r.missing_kws)}")
                if not r.cited:
                    print(f"    No citation to expected file")

    # ── Category breakdown ────────────────────────────────────────────────────
    categories = sorted({r.category for r in results})
    print(f"\n{BOLD}Category Breakdown{RESET}")
    for cat in categories:
        cat_results = [r for r in results if r.category == cat]
        n_ok = sum(r.correct for r in cat_results)
        bar = ("█" * n_ok) + ("░" * (len(cat_results) - n_ok))
        print(f"  {cat:12} {bar}  {n_ok}/{len(cat_results)}")

    # ── JSON output ───────────────────────────────────────────────────────────
    out = {
        "repo": args.repo,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "summary": {
            "total": total,
            "answered": n_answered,
            "correct": n_correct,
            "cited": n_cited,
            "accuracy_pct": round(100 * n_correct / total),
        },
        "results": [
            {
                "question": r.question,
                "category": r.category,
                "answered": r.answered,
                "correct": r.correct,
                "cited": r.cited,
                "answer": r.answer,
                "missing_kws": r.missing_kws,
                "latency_s": r.latency_s,
                "error": r.error,
                "citations": [c["node_id"] for c in r.citations],
            }
            for r in results
        ],
    }
    out_path = "eval_results.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nResults saved → {out_path}\n")
    return 0 if n_correct == total else 1


if __name__ == "__main__":
    sys.exit(main())
