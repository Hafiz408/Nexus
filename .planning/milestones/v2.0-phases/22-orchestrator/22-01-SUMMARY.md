---
phase: 22-orchestrator
plan: 01
subsystem: agent
tags: [langgraph, stategraph, orchestrator, sqlite, checkpointing, multi-agent]

# Dependency graph
requires:
  - phase: 21-critic-agent
    provides: critic.py critique() quality gate + CriticResult model
  - phase: 20-tester-agent
    provides: tester.py test() + TestResult model
  - phase: 19-reviewer-agent
    provides: reviewer.py review() + ReviewResult model
  - phase: 18-debugger-agent
    provides: debugger.py debug() + DebugResult model
  - phase: 17-router-agent
    provides: router.py route() + IntentResult model
provides:
  - NexusState TypedDict with 12 typed fields for LangGraph graph state
  - build_graph(checkpointer) factory returning CompiledStateGraph
  - orchestrator.py wiring all 5 V2 agents into one pipeline
affects: [23-api-integration, 24-streaming, 25-frontend-v2, 26-deployment]

# Tech tracking
tech-stack:
  added:
    - langgraph>=1.1.3 (StateGraph, START, END, CompiledStateGraph)
    - langgraph-checkpoint-sqlite>=3.0.3 (SqliteSaver)
  patterns:
    - NexusState TypedDict with Optional[object] for non-JSON-serializable fields
    - Lazy agent imports inside every node function body (prevents ValidationError at collection time)
    - build_graph() factory accepting optional checkpointer (MemorySaver for tests, SqliteSaver for production)
    - Conditional edges for router→specialist and critic→done/retry routing
    - loop_count incremented in critic_node on RETRY path only

key-files:
  created:
    - backend/app/agent/orchestrator.py
  modified:
    - backend/requirements.txt

key-decisions:
  - "G typed as Optional[object] in NexusState — SqliteSaver cannot JSON-serialize nx.DiGraph; callers must re-supply G on every invoke()"
  - "_explain_node uses chain.invoke() inline (sync), not explore_stream() (async generator) — asyncio.run() inside FastAPI raises RuntimeError: event loop already running"
  - "All agent imports (route, debug, review, test, critique) are lazy inside node function bodies — established pattern from all prior V2 agents"
  - "loop_count incremented in _critic_node on RETRY path only — specialist nodes have no loop awareness"
  - "SqliteSaver must use check_same_thread=False — LangGraph writes checkpoints from background threads; documented in build_graph() docstring"
  - "build_graph(checkpointer=None) compiles without checkpointer for stateless operation; MemorySaver() recommended for tests"

patterns-established:
  - "Lazy import pattern: every node function imports its agent at call time, not at module level"
  - "NexusState Optional[object] pattern: any field that holds a non-JSON-serializable object must be typed as Optional[object]"
  - "Graph factory pattern: build_graph(checkpointer) accepts injected checkpointer, enabling test isolation"

requirements-completed: [ORCH-01, ORCH-02, ORCH-03]

# Metrics
duration: 2min
completed: 2026-03-22
---

# Phase 22 Plan 01: Orchestrator Summary

**LangGraph StateGraph wiring all 5 V2 agents into a single typed pipeline with SqliteSaver checkpointing and critic retry loop**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-21T20:40:58Z
- **Completed:** 2026-03-21T20:42:58Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- NexusState TypedDict with all 12 required fields, including G typed as Optional[object] to prevent SqliteSaver JSON serialization errors
- build_graph(checkpointer) factory compiling a 6-node StateGraph: router_node → [explain|debug|review|test]_node → critic_node with conditional retry loop
- All five agent imports (route, debug, review, test, critique) are lazy inside node function bodies — zero import-time ValidationErrors
- 158 existing tests continue to pass with zero regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Add langgraph dependencies to requirements.txt** - `aa75acb` (chore)
2. **Task 2: Implement orchestrator.py** - `48cb44e` (feat)

**Plan metadata:** (docs commit follows)

## NexusState Fields

All 12 required fields defined:

| Field | Type | Purpose |
|---|---|---|
| question | str | Developer's query |
| repo_path | str | Repository path for retrieval |
| intent_hint | Optional[str] | Explicit intent bypass for router |
| G | Optional[object] | nx.DiGraph (typed as object to skip JSON serialization) |
| target_node_id | Optional[str] | Node for review/test specialists |
| selected_file | Optional[str] | REVW-03 range targeting |
| selected_range | Optional[tuple] | REVW-03 (line_start, line_end) |
| repo_root | Optional[str] | Framework detection for tester |
| intent | Optional[str] | Set by router_node |
| specialist_result | Optional[object] | DebugResult / ReviewResult / TestResult / _ExplainResult |
| critic_result | Optional[object] | CriticResult from critic_node |
| loop_count | int | 0 on first call; incremented by critic_node on retry |

## Explain Path Strategy

The `_explain_node` builds an LCEL chain inline using `chain.invoke()` (synchronous), NOT `explore_stream()` (async generator). Rationale:
- `explore_stream()` is an async generator that cannot be driven with `asyncio.run()` inside a FastAPI async endpoint — raises `RuntimeError: This event loop is already running`
- `chain.invoke()` produces identical answer quality using the same prompt template and LLM
- `_get_chain()` from explorer.py was NOT imported — it is a private function and calls `get_llm()` at the call site without the lazy import guard needed here

## Lazy Import Confirmation

Every agent import in orchestrator.py is inside the function body that uses it:

- `_router_node`: `from app.agent.router import route`
- `_explain_node`: `from app.core.model_factory import get_llm`, `from app.agent.prompts import SYSTEM_PROMPT`, `from app.agent.explorer import format_context_block`, `from app.retrieval.graph_rag import graph_rag_retrieve`
- `_debug_node`: `from app.agent.debugger import debug`
- `_review_node`: `from app.agent.reviewer import review`
- `_test_node`: `from app.agent.tester import test as run_test`
- `_critic_node`: `from app.agent.critic import critique`

No agent imports at module level.

## Files Created/Modified

- `backend/app/agent/orchestrator.py` — NexusState TypedDict + _ExplainResult carrier + 6 node functions + build_graph() factory; 286 lines
- `backend/requirements.txt` — added langgraph>=1.1.3 and langgraph-checkpoint-sqlite>=3.0.3

## Decisions Made

- G typed as Optional[object]: SqliteSaver serializes entire state dict to JSON; nx.DiGraph is not JSON-serializable; callers must re-supply G on every graph.invoke() call
- chain.invoke() not explore_stream(): async generator cannot be used inside a running FastAPI event loop
- All lazy imports: established pattern from Phases 17-21 to prevent ValidationError during pytest collection when API keys are absent
- loop_count in critic_node only: specialist nodes have no retry awareness; only critic_node knows whether this is a first attempt or retry

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Test Count

- Before: 158 tests passing
- After: 158 tests passing (zero regressions)

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- orchestrator.py is fully importable and build_graph() compiles cleanly
- Ready for Phase 23 (API integration): the API layer can import build_graph and NexusState and wire them to the FastAPI query endpoint
- Production usage: `SqliteSaver(sqlite3.connect("data/checkpoints.db", check_same_thread=False))` must use `check_same_thread=False`
- Test usage: `build_graph(checkpointer=MemorySaver())` avoids SQLite threading issues in pytest

---
*Phase: 22-orchestrator*
*Completed: 2026-03-22*
