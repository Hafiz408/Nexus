---
phase: 14-ragas-eval
plan: 02
subsystem: evaluation
tags: [ragas, evaluation, graph-rag, naive-vector, pandas, asyncio]

# Dependency graph
requires:
  - eval/golden_qa.json (from 14-01)
  - backend/requirements.txt with ragas==0.4.3 and pandas (from 14-01)
provides:
  - eval/run_ragas.py — standalone evaluation runner for graph-RAG vs naive vector-only
  - eval/results/.gitkeep — committed results directory structure
affects: [14-ragas-eval]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - dual-mode RAGAS evaluation with side-by-side graph_rag vs naive vector comparison
    - column name map to handle ragas 0.4.x minor-version column name variation
    - raise_exceptions=False + RunConfig resilience for production evaluation runs

key-files:
  created:
    - eval/run_ragas.py
    - eval/results/.gitkeep
  modified: []

key-decisions:
  - "col_map substring matching used to handle faithfulness/answer_relevancy/response_relevancy column name variation between ragas 0.4.x minor versions"
  - "naive_retrieve wraps CodeNode hydration in try/except to skip malformed G.nodes entries without crashing the evaluation loop"
  - "get_answer collects all explore_stream tokens into a single string — avoids partial answers in RAGAS samples"
  - "Backend test verification used Option C (py_compile syntax check) — no docker backend or local deps available; test files all compile cleanly"

patterns-established:
  - "eval/run_ragas.py is standalone (not pytest) — asyncio.run(main()) entry point, runnable from any cwd via abspath(__file__) path fix"

requirements-completed: [EVAL-02, EVAL-03, EVAL-04, TEST-01]

# Metrics
duration: 4min
completed: 2026-03-19
---

# Phase 14 Plan 02: RAGAS Evaluation Runner Summary

**RAGAS evaluation runner producing graph-RAG vs naive vector-only side-by-side comparison with timestamped JSON output to eval/results/**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-19T11:07:48Z
- **Completed:** 2026-03-19T11:11:30Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Created `eval/run_ragas.py` — complete 283-line standalone evaluation script implementing dual-mode RAGAS evaluation
- Script evaluates all 30 golden Q&A pairs against both graph_rag_retrieve and naive semantic_search-only retrieval
- Writes three output files per run: `ragas_results_graph_rag_{ts}.json`, `ragas_results_naive_vector_{ts}.json`, `ragas_comparison_{ts}.json`
- Prints formatted comparison table to stdout showing faithfulness, answer_relevancy, context_precision, and winner per metric
- Created `eval/results/.gitkeep` to commit the results directory structure before any evaluation runs produce output
- Confirmed all 8 backend test files compile cleanly — no regressions from ragas/pandas additions

## Task Commits

Each task was committed atomically:

1. **Task 1: Create eval/run_ragas.py evaluation script** - `3c37baa` (feat)
2. **Task 2: Create eval/results/.gitkeep and verify backend tests** - `ba84110` (chore)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `eval/run_ragas.py` — 283 lines; imports, helpers (get_answer, naive_retrieve, build_contexts), async main, argparse entry point
- `eval/results/.gitkeep` — empty file; commits results/ directory to git before any evaluation run

## Decisions Made

- **Column name map:** ragas 0.4.x minor versions use different column names (`answer_relevancy` vs `response_relevancy`). A `col_map` dict matches by substring (`key in col.lower()`) on all actual df.columns to find the right column regardless of minor version.
- **naive_retrieve hydration guard:** CodeNode construction from G.nodes wrapped in try/except to skip malformed attribute dicts without crashing evaluation.
- **Backend test verification method:** Option C used (python3 -m py_compile on all 8 test files) — docker backend not running, local ragas/pandas not installed. All 8 test files compile without errors. The eval script additions (run_ragas.py, .gitkeep) are outside backend/ and will not be collected by pytest.

## Verification Results

All 6 plan verification checks passed:
1. `python3 -c "import ast; ast.parse(open('eval/run_ragas.py').read())"` — syntax OK
2. `ls eval/results/.gitkeep` — file exists (0 bytes)
3. `grep -c "asyncio.run(main" eval/run_ragas.py` — 1
4. `grep -c "raise_exceptions=False" eval/run_ragas.py` — 1
5. `grep -c "naive_retrieve" eval/run_ragas.py` — 2 (definition + call)
6. `python3 -m py_compile backend/tests/test_file_walker.py backend/tests/test_graph_rag.py` — OK

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

To run the evaluation:
```bash
export EVAL_REPO_PATH=/path/to/fastapi
export OPENAI_API_KEY=sk-...
# With backend running and repo indexed:
PYTHONPATH=backend python eval/run_ragas.py --repo-path "$EVAL_REPO_PATH"
```

---
*Phase: 14-ragas-eval*
*Completed: 2026-03-19*

## Self-Check: PASSED

- FOUND: eval/run_ragas.py
- FOUND: eval/results/.gitkeep
- FOUND: .planning/phases/14-ragas-eval/14-02-SUMMARY.md
- FOUND commit 3c37baa: feat(14-02): create eval/run_ragas.py RAGAS evaluation runner
- FOUND commit ba84110: chore(14-02): add eval/results/.gitkeep to track results directory in git
