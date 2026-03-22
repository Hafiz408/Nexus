# Session State

## Project Reference

See: .planning/PROJECT.md

## Current Position

Phase: 26 — extension-result-rendering
Plan: 03 — complete
Status: Phase 26 Plan 03 complete; DebugPanel + ReviewPanel + postReviewToPR stub; EXT-04 through EXT-07 panel rendering complete
Last activity: 2026-03-22 — Completed 26-03-PLAN.md (DebugPanel, ReviewPanel, FindingCard components + Phase 26 CSS + postReviewToPR stub)

**Core value:** Grounded, graph-aware codebase intelligence — no hallucination
**Current focus:** v2.0 multi-agent team — Phase 25 complete; V2 agent routing reachable from extension UI

**Progress:** [██████████] 95%

## Performance Metrics

- V1 test suite: 93 tests passing in 0.37s (must stay green)
- V1 RAGAS baseline: 80% (8/10)
- V2 router gate: 100% accuracy on 12 labelled queries required before Phase 18

## Accumulated Context

### Decisions
- V2 starts at Phase 16 (V1 shipped Phases 1-15)
- Branch: feature/v2
- All V2 agent tests must use mock LLM + mock graph (no live API calls)
- Never modify backend/app/agent/explorer.py
- Critic loop hard cap = 2 (never infinite)
- SqliteSaver checkpointer uses a separate DB from graph_store.py's "data/nexus.db"
- get_llm() factory from model_factory.py — never instantiate ChatOpenAI directly
- Phase 17 (router-agent) is a gate: 100% accuracy required before Phase 18 begins
- [Phase 16-config-v2]: All five V2 fields are optional with safe defaults — backend starts without any V2 env vars set
- [Phase 16-config-v2]: github_token defaults to empty string so downstream MCP layer checks truthiness without None handling
- [Phase 16-config-v2]: critic_threshold typed as float (not int) to accept values like 0.7 and 0.8
- [Phase 17-router-agent]: get_llm() imported inside route() body (not module level) to prevent import-time ValidationError when API keys are absent
- [Phase 17-router-agent]: Low-confidence fallback (<0.6) constructs new IntentResult preserving original confidence, overriding intent to 'explain' — Pydantic v2 immutability pattern
- [Phase 17-router-agent]: Patch lazy-imported get_llm at source module (app.core.model_factory.get_llm), not consumer module — lazy imports don't appear in module __dict__
- [Phase 17-router-agent]: LCEL mock pattern: use MagicMock(return_value=IntentResult(...)) for with_structured_output() result — pipe operator creates RunnableLambda that calls mock as __call__, not .invoke()
- [Phase 18-debugger-agent]: Anomaly score weights 0.30/0.25/0.20/0.15/0.10 for complexity/error-absence/keyword-match/out-degree/inverted-PageRank
- [Phase 18-debugger-agent]: Debugger entry node fallback uses highest in_degree (most-called) node when no function name matches bug description
- [Phase 18-debugger-agent]: Lazy import pattern applied to both get_settings() and get_llm() inside debug() body — consistent with Phase 17 router.py pattern
- [Phase 18-debugger-agent]: mock_settings fixture injects debugger_max_hops=4 directly into debug() to bypass postgres env var requirement in tests
- [Phase 18-debugger-agent]: Traversal path upper bound 6 (all 6 nodes in debug_graph reachable from entry within max_hops=4)
- [Phase 19-reviewer-agent]: Groundedness post-filter applied after LLM call to drop findings with file_path not in retrieved_nodes set
- [Phase 19-reviewer-agent]: range_clause injected via REVIEWER_PROMPT.partial() per-call, not baked into REVIEWER_SYSTEM constant
- [Phase 19-reviewer-agent]: get_llm() and get_settings() imported inside review() body (lazy) — same pattern as router.py and debugger.py
- [Phase 19-reviewer-agent]: LCEL mock pattern for with_structured_output: mock_structured.return_value = fixture_result — RunnableSequence calls structured_llm via __call__, not .invoke()
- [Phase 20-tester-agent]: Tester uses two-model pattern: _LLMTestOutput for LLM call (test_code only), TestResult assembled deterministically post-call
- [Phase 20-tester-agent]: get_llm() and get_settings() imported inside test() body (lazy) — consistent with router.py, debugger.py, reviewer.py pattern
- [Phase 20-tester-agent]: _derive_test_path() derives test_file_path from (func_name, framework) deterministically — LLM never generates file paths
- [Phase 20-tester-agent]: Import alias 'test as run_test' required in test_tester.py — pytest collects production test() function from module namespace causing fixture resolution error
- [Phase 21-critic-agent]: Groundedness dispatch per result type: DebugResult uses traversal_path/suspects, ReviewResult uses retrieved_nodes/findings, TestResult always 1.0
- [Phase 21-critic-agent]: Lazy specialist imports inside private helpers to prevent circular imports when orchestrator imports all agents together
- [Phase 21-critic-agent]: Hard cap checked before quality gate — loop_count >= max_loops forces passed=True unconditionally (CRIT-03)
- [Phase 21-critic-agent TST-05]: Module-level helper builders (make_debug_result, make_review_result, make_test_result) used instead of fixtures to allow arbitrary argument construction per test
- [Phase 21-critic-agent TST-05]: critic_threshold=0.0 override in test_feedback_none_on_pass forces pass path — tests feedback=None invariant independently of score arithmetic
- [Phase 21-critic-agent TST-05]: Loop boundary test (loop_count=1) added to confirm hard cap fence-post: cap fires at max_loops (2), not max_loops-1 (1)
- [Phase 22-orchestrator]: G typed as Optional[object] in NexusState so SqliteSaver does not attempt JSON serialization of nx.DiGraph
- [Phase 22-orchestrator]: _explain_node uses chain.invoke() (sync) not explore_stream() (async generator) — asyncio.run() inside FastAPI raises RuntimeError: event loop already running
- [Phase 22-orchestrator]: loop_count incremented in critic_node on RETRY path only — specialist nodes have no loop awareness
- [Phase 22-orchestrator]: _ExplainResult converted from plain class to Pydantic BaseModel — MemorySaver cannot msgpack-serialize plain Python classes; all state fields must be Pydantic-compatible for checkpointing
- [Phase 22-orchestrator]: G=None in orchestrator test base_state — MemorySaver cannot serialize nx.DiGraph even with Optional[object] typing; explain_node try/except handles None-graph gracefully
- [Phase 22-orchestrator]: LangChain LCEL mock pattern: set mock.return_value and mock.invoke.return_value — LCEL pipe calls llm via __call__ not .invoke() so both paths must be covered
- [Phase 23-mcp-tools]: [Phase 23-mcp-tools]: httpx.Client used as context manager in post_review_comments() for consistent mock patch target; tenacity 5xx-only retry predicate; '..' path traversal guard before Path ops; falsy github_token check
- [Phase 23-mcp-tools]: Patch target is 'app.mcp.tools.httpx.Client' (module-level binding), not 'httpx.Client' directly — patching at the import site intercepts the already-bound name
- [Phase 24-query-endpoint-v2]: V2 branch gated on intent_hint not None and not 'auto'; both None and 'auto' fall through to V1 SSE path
- [Phase 24-query-endpoint-v2]: SqliteSaver checkpointer uses data/checkpoints.db (not data/nexus.db) with per-request uuid4 thread_id
- [Phase 24-query-endpoint-v2]: asyncio.to_thread(graph.invoke, ...) prevents blocking FastAPI event loop from synchronous LangGraph invoke
- [Phase 24-query-endpoint-v2 TST-09]: build_graph patched at source module (app.agent.orchestrator.build_graph) for V2 endpoint tests — lazy import inside v2_event_generator body is not bound in query_router module __dict__; source-module patch intercepts the binding (consistent with Phase 17 router-agent pattern)
- [Phase 25-extension-intent-selector]: Auto intent sends undefined (not 'auto') — backend V2 gate checks intent_hint not None and not 'auto'; sending 'auto' silently degrades to V1 path
- [Phase 25-extension-intent-selector]: CSS \!important required on pill background/border — global button reset applies background:transparent \!important and border:none \!important to all buttons
- [Phase 25-extension-intent-selector]: Pill selection is sticky — selectedIntent not reset after send; user changes intent explicitly
- [Phase 26-02]: App.tsx defines its own local IncomingMessage type (not imported from types.ts) — must be updated in Plan 03, not in 26-02
- [Phase 26-01]: write_test_file called only for test intent; MCP error isolation via try/except keeps SSE stream intact; has_github_token uses bool() consistent with Phase 16 empty-string default
- [Phase 26-03]: DebugPanel and ReviewPanel defined as module-level function components to prevent re-mounting on every App render
- [Phase 26-03]: postReviewToPR added to WebviewToHostMessage union in types.ts to satisfy SidebarProvider.ts discriminated union switch

### Implementation Notes
- Actual module paths: `app/agent/` (singular), `app/api/query_router.py`
- Graph edges use `type=` attribute: `G.add_edge(u, v, type="CALLS")`
- conftest.py has `sample_graph` + `mock_embedder` fixtures; need to add `mock_llm` for V2
- V1 explorer calls `explore_stream()` — LangGraph explorer_node wraps this, never modifies it

### Blockers
- None

## Session Log

- 2026-03-21: STATE.md regenerated by /gsd:health --repair
- 2026-03-21: Milestone v2.0 Multi-Agent Team started
- 2026-03-21: V2 roadmap created — Phases 16-26 defined, 46/46 requirements mapped
- 2026-03-21: Phase 16 Plan 01 complete — V2 config fields added to Settings; .env.example created; CONF-01, CONF-02 marked complete
- 2026-03-22: Phase 17 Plan 01 complete — Router agent module created; IntentResult model + route() function; ROUT-01, ROUT-03, ROUT-04 marked complete
- 2026-03-22: Phase 17 Plan 02 complete — Router agent test suite: 21 tests offline, 12/12 labelled queries PASSED, accuracy gate cleared; ROUT-02, TST-01 marked complete
- 2026-03-22: Phase 18 Plan 01 complete — Debugger agent module created; SuspectNode + DebugResult models + debug() with 5-factor anomaly scoring + BFS traversal; DBUG-01, DBUG-02, DBUG-03, DBUG-04, DBUG-05 marked complete; 114 tests passing
- 2026-03-22: Phase 18 Plan 02 complete — Debugger agent test suite: 10 offline tests, debug_graph + mock_settings + mock_llm_factory fixtures; TST-02 marked complete; 124 tests passing
- 2026-03-22: Phase 19 Plan 01 complete — Reviewer agent module created; Finding (7 fields) + ReviewResult (3 fields) models; _assemble_context() 1-hop CALLS-edge traversal; review() with LCEL structured-output chain and groundedness post-filter; REVW-01, REVW-02, REVW-03 marked complete; 124 tests passing
- 2026-03-22: Phase 19 Plan 02 complete — Reviewer agent test suite: 10 offline tests, reviewer_graph (5-node DiGraph) + mock_settings (reviewer_context_hops=1) + mock_llm_factory (source-level patch with __call__ return_value) fixtures; TST-03 marked complete; 134 tests passing
- 2026-03-22: Phase 20 Plan 01 complete — Tester agent module created; _detect_framework (marker file heuristics) + _get_callees (CALLS-edge enumeration) + _derive_test_path (deterministic convention mapping) + test() public API with lazy imports; TST-04 partial; 134 tests passing
- 2026-03-22: Phase 20 Plan 02 complete — Tester agent test suite: 10 offline tests, tester_graph (4-node DiGraph: target + 2 CALLS callees + 1 isolated) + mock_settings + mock_llm_factory fixtures; pytest.ini added to prevent test() function name collision; TST-04 marked complete; 148 tests passing
- 2026-03-22: Phase 21 Plan 01 complete — Critic agent module created; CriticResult (7 fields) + critique() deterministic quality gate; composite scoring 0.40/0.35/0.25 groundedness/relevance/actionability; hard cap at loop_count>=2; per-type groundedness dispatch; CRIT-01, CRIT-02, CRIT-03, CRIT-04 marked complete; 148 tests passing
- 2026-03-22: Phase 21 Plan 02 complete — Critic agent test suite: 10 offline tests, mock_settings (max_critic_loops=2, critic_threshold=0.7) + module-level helper builders; TST-05 marked complete; 158 tests passing
- 2026-03-22: Phase 22 Plan 01 complete — Orchestrator module created; NexusState (12 fields) + build_graph() factory; LangGraph StateGraph router→specialist→critic pipeline with conditional retry loop; langgraph + langgraph-checkpoint-sqlite added to requirements.txt; ORCH-01, ORCH-02, ORCH-03 marked complete; 158 tests passing
- 2026-03-22: Phase 22 Plan 02 complete — Orchestrator test suite: 6 offline integration tests, MemorySaver + G=None + source-module get_llm patch + per-agent mocks; _ExplainResult converted to Pydantic BaseModel for MemorySaver serialization; TST-07 marked complete; 164 tests passing
- 2026-03-22: Phase 23 Plan 01 complete — MCP tool layer created; post_review_comments() (10-cap + overflow + 5xx retry + 422 per-finding fallback) + write_test_file() (path traversal guard + extension allowlist + overwrite protection); httpx + tenacity added to requirements.txt; MCP-01 through MCP-06 marked complete; 164 tests passing
- 2026-03-22: Phase 23 Plan 02 complete — MCP tools test suite: test_mcp_tools.py with 18 offline tests (10-cap/overflow, 5xx tenacity retry, 422 per-finding fallback, no-op guards, path traversal, extension allowlist, overwrite protection); TST-06 marked complete; 182 tests passing
- 2026-03-22: Phase 24 Plan 01 complete — V2 branch wired into /query endpoint; QueryRequest extended with intent_hint, target_node_id, selected_file, selected_range, repo_root (all Optional=None); v2_event_generator uses lazy imports + asyncio.to_thread(graph.invoke) + SqliteSaver(checkpoints.db) + uuid4 thread_id; 9 V1 tests passing; TST-08 marked complete; 182 tests passing
- 2026-03-22: Phase 24 Plan 02 complete — V2 endpoint test suite: test_query_router_v2.py with 8 offline tests (debug/review/test/explain routing + auto/None sentinel fall-through + error propagation); build_graph patched at source module (app.agent.orchestrator.build_graph); TST-09 marked complete; 190 tests passing
- 2026-03-22: Phase 25 Plan 01 complete — Intent selector UI added to extension sidebar; five pills (Auto/Explain/Debug/Review/Test); intent_hint threaded from webview postMessage through SidebarProvider to SseStream POST body; Auto sends undefined (not 'auto'); EXT-01, EXT-02, EXT-03 marked complete
- 2026-03-22: Phase 26 Plan 01 complete — v2_event_generator result payload extended with has_github_token (github_token presence), file_written and written_path (MCP write outcome for test intent); lazy imports + try/except MCP error isolation; EXT-07, EXT-09 marked complete; 190 tests passing
- 2026-03-22: Phase 26 Plan 02 complete — SSE result plumbing added; HostToWebviewMessage union extended with result variant (types.ts); case 'result' handler wired in SseStream.ts forwarding intent/result/has_github_token/file_written/written_path to webview; EXT-04 through EXT-09 marked complete
- 2026-03-22: Phase 26 Plan 03 complete — DebugPanel (suspects + score bars + traversal breadcrumb + collapsible impact radius) and ReviewPanel (findings + severity badges + expandable suggestions + conditional GitHub PR button) implemented in App.tsx; postReviewToPR stub added to SidebarProvider.ts; Phase 26 CSS appended to index.css; EXT-04 through EXT-07 panel rendering complete
