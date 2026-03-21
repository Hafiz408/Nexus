# Roadmap: Nexus

## Milestones

- ✅ **v1.0 MVP** — Phases 1-15 (shipped 2026-03-21) — [archive](.planning/milestones/v1.0-ROADMAP.md)
- 🔄 **v2.0 Multi-Agent Team** — Phases 16-26 (in progress)

## Phases

<details>
<summary>✅ v1.0 MVP (Phases 01-15) — SHIPPED 2026-03-21</summary>

> Phases 01-07 were foundation (infrastructure, AST parser, graph builder, embedder, ingestion pipeline, FTS5 search). Phase directories cleaned up; 07.1 onward tracked in `.planning/phases/`.

- [x] Phase 07.1: tech-debt-cleanup — FTS5/pgvector deletion + Docker healthcheck
- [x] Phase 08: graph-rag — 3-step retrieval pipeline (vector → BFS → rerank)
- [x] Phase 09: explorer-agent — LangChain LCEL SSE streaming agent
- [x] Phase 10: query-endpoint — POST /query SSE endpoint + lazy graph cache
- [x] Phase 11: vs-code-extension — Extension scaffold, services, webview UI, wiring
- [x] Phase 12: highlighter — Citation highlighting in editor
- [x] Phase 13: file-watcher — Incremental re-index on file save
- [x] Phase 14: ragas-eval — RAGAS golden dataset + evaluation runner (80% baseline)
- [x] Phase 15: extension-ui-revamp — Textarea UX, citation chips, progress bar

</details>

### v2.0 Multi-Agent Team (Phases 16-26)

- [x] **Phase 16: config-v2** — V2 environment configuration with safe defaults (completed 2026-03-21)
- [x] **Phase 17: router-agent** — Intent classifier with 100% accuracy gate before agent work begins (completed 2026-03-21)
- [x] **Phase 18: debugger-agent** — Call graph traversal + anomaly-scored suspect ranking (completed 2026-03-21)
- [x] **Phase 19: reviewer-agent** — Caller/callee context assembly + structured Finding schema (completed 2026-03-21)
- [x] **Phase 20: tester-agent** — Framework detection + dependency-aware test generation (completed 2026-03-21)
- [ ] **Phase 21: critic-agent** — LLM-as-judge quality gate with 2-loop hard cap
- [ ] **Phase 22: orchestrator** — LangGraph StateGraph wiring all agents with checkpointing
- [ ] **Phase 23: mcp-tools** — GitHub PR commenting + Filesystem safe test file writing
- [ ] **Phase 24: query-endpoint-v2** — Wire orchestrator into /query; confirm zero V1 regressions
- [ ] **Phase 25: extension-intent-selector** — 5-option intent selector UI + intent_hint wiring
- [ ] **Phase 26: extension-result-rendering** — Structured debug/review/test result panels

---

## Phase Details

### Phase 16: config-v2
**Goal**: All V2 runtime knobs are configurable via environment variables with safe defaults so agents can be tuned without code changes
**Depends on**: Nothing (configuration foundation)
**Requirements**: CONF-01, CONF-02
**Success Criteria** (what must be TRUE):
  1. Starting the backend without any V2 env vars set works without errors — all new settings have safe defaults
  2. Setting `MAX_CRITIC_LOOPS=1`, `CRITIC_THRESHOLD=0.8`, `DEBUGGER_MAX_HOPS=3`, `REVIEWER_CONTEXT_HOPS=2`, `GITHUB_TOKEN=x` changes observed agent behaviour without code changes
  3. `.env.example` lists every new V2 variable with description and default value visible in one file
**Plans**: 1 plan

Plans:
- [ ] 16-01-PLAN.md — Add V2 agent tuning fields to Settings + create .env.example

### Phase 17: router-agent
**Goal**: The Router agent correctly classifies every developer query into one of four intents so downstream specialist agents receive the right task
**Depends on**: Phase 16
**Requirements**: ROUT-01, ROUT-02, ROUT-03, ROUT-04, TST-01
**Gate**: Must achieve 100% accuracy on all 12 labelled test cases before Phase 18 begins
**Success Criteria** (what must be TRUE):
  1. Given any of the 12 labelled test queries, the router returns the correct intent with a confidence score — zero misclassifications
  2. Passing `intent_hint=debug` in the request body bypasses the LLM call and routes immediately to the Debugger
  3. A query with router confidence below 0.6 routes to `explain` rather than making a low-confidence specialist call
  4. `test_router_agent.py` passes 12/12 with mock LLM — no live API calls required
**Plans**: 2 plans

Plans:
- [ ] 17-01-PLAN.md — Implement app/agent/router.py (IntentResult model + route() function)
- [ ] 17-02-PLAN.md — Write test_router_agent.py (12 labelled queries + bypass + fallback tests)

### Phase 18: debugger-agent
**Goal**: The Debugger agent traverses the call graph and surfaces a ranked list of root-cause suspects with anomaly scores so developers know exactly where to look
**Depends on**: Phase 17
**Requirements**: DBUG-01, DBUG-02, DBUG-03, DBUG-04, DBUG-05, TST-02
**Success Criteria** (what must be TRUE):
  1. Given a bug description mentioning a function name, the Debugger visits up to 4 forward hops along CALLS edges from that entry point
  2. Every traversed node receives an anomaly score between 0.0 and 1.0; the top suspect has the highest score
  3. The returned list contains at most 5 suspects, each with node_id, file_path, line_start, anomaly_score, and a reasoning string
  4. The diagnosis narrative mentions only functions that appear in the traversal path — no hallucinated function names
  5. `test_debugger.py` confirms traversal order, anomaly scoring, impact radius, and diagnosis correctness using mock graph — no live API calls
**Plans**: 2 plans

Plans:
- [ ] 18-01-PLAN.md — Implement app/agent/debugger.py (Pydantic models + traversal + scoring + debug() function)
- [ ] 18-02-PLAN.md — Write test_debugger.py (10 offline tests: traversal, scoring, impact radius, diagnosis, fallback)

### Phase 19: reviewer-agent
**Goal**: The Reviewer agent assembles graph-grounded context and produces structured code findings that cite real nodes so developers receive actionable, non-hallucinated review feedback
**Depends on**: Phase 17
**Requirements**: REVW-01, REVW-02, REVW-03, TST-03
**Success Criteria** (what must be TRUE):
  1. For any target function, the reviewer's context includes the target node plus its 1-hop callers and 1-hop callees pulled from the graph
  2. Every returned Finding has all required fields: severity, category, description, file_path, line_start, line_end, and suggestion
  3. When a user has selected a code range, findings target that specific range rather than the whole file
  4. No Finding references a node ID that does not appear in `retrieved_nodes` (groundedness enforced)
  5. `test_reviewer.py` validates context assembly, schema completeness, and absence of hallucinated node references using mock graph
**Plans**: 2 plans

Plans:
- [ ] 19-01-PLAN.md — Implement app/agent/reviewer.py (Finding + ReviewResult models + review() function)
- [ ] 19-02-PLAN.md — Write test_reviewer.py (10 offline tests: context assembly, schema, groundedness, range, edge cases)

### Phase 20: tester-agent
**Goal**: The Tester agent automatically generates runnable, framework-appropriate test code that covers the target function's behaviour so developers get a working test file with minimal effort
**Depends on**: Phase 17
**Requirements**: TEST-01, TEST-02, TEST-03, TEST-04, TEST-05, TST-04
**Success Criteria** (what must be TRUE):
  1. Given a repo with pytest files present, the Tester detects `pytest` as the framework without manual configuration
  2. All CALLS-edge callees of the target function appear as mock/patch targets in the generated test code
  3. Generated test code contains at least 3 test functions covering happy path, error case, and edge case
  4. The derived test file path follows the detected framework convention (e.g. `tests/test_<name>.py` for pytest)
  5. Mock statements use the correct syntax for the detected framework — pytest uses `unittest.mock.patch`, jest uses `jest.fn()`
**Plans**: 2 plans

Plans:
- [ ] 20-01-PLAN.md — Implement app/agent/tester.py (_LLMTestOutput + TestResult models + _detect_framework + _get_callees + _derive_test_path + test() function)
- [ ] 20-02-PLAN.md — Write test_tester.py (10 offline tests: framework detection, mock targets, file path convention, ≥3 test functions, mock syntax)

### Phase 21: critic-agent
**Goal**: The Critic agent enforces a quality gate on every specialist output — routing low-quality responses back for improvement while guaranteeing the loop always terminates
**Depends on**: Phases 18, 19, 20 (critiques their outputs)
**Requirements**: CRIT-01, CRIT-02, CRIT-03, CRIT-04, TST-05
**Success Criteria** (what must be TRUE):
  1. Every specialist output receives a score computed as 0.4×groundedness + 0.35×relevance + 0.25×actionability; the score is present in every Critic response
  2. When overall score < 0.7 and the loop count is below 2, the response routes back to the originating specialist with specific written feedback
  3. After exactly 2 retry loops the output is accepted regardless of score — the loop never runs a third time
  4. Groundedness is computed by comparing cited node IDs against `retrieved_nodes` without an additional LLM call
  5. `test_critic.py` verifies the scoring formula, retry routing, hard cap at 2 loops, and feedback clearing on a passing score
**Plans**: TBD

### Phase 22: orchestrator
**Goal**: A single LangGraph StateGraph wires all agents into one coherent pipeline with persistent checkpointing so every query follows the correct path and conversation state survives across requests
**Depends on**: Phases 16, 17, 18, 19, 20, 21
**Requirements**: ORCH-01, ORCH-02, ORCH-03, TST-07
**Success Criteria** (what must be TRUE):
  1. Every query to the backend flows through the LangGraph StateGraph with typed NexusState — no direct calls to the old V1 runnable
  2. Sending the same thread_id in two successive requests continues the prior conversation (SqliteSaver checkpointing working)
  3. A V1 query sent without `intent_hint` returns the same answer quality as before — zero regressions on the explain path
  4. `test_orchestrator.py` passes all 6 integration tests (explain, debug, review, test, retry loop, max_loops termination) using mock LLM and mock graph
**Plans**: TBD

### Phase 23: mcp-tools
**Goal**: GitHub MCP and Filesystem MCP give agents the ability to post PR comments and write test files safely so the output of review and test sessions has real-world effect
**Depends on**: Phase 22
**Requirements**: MCP-01, MCP-02, MCP-03, MCP-04, MCP-05, MCP-06, TST-06
**Success Criteria** (what must be TRUE):
  1. GitHub MCP posts up to 10 inline PR comments per Reviewer run; findings beyond 10 become a single summary comment
  2. When GitHub returns a 5xx error, MCP retries up to 3 times with exponential backoff before surfacing the error; a 422 on an invalid line logs a warning and skips that finding
  3. Filesystem MCP writes the generated test file to the derived path, creating any missing parent directories
  4. A path containing `..` is rejected immediately with an error — no file is written
  5. A file with an extension outside the allowed set is rejected; an existing file with `overwrite=False` returns an error without modifying the file
  6. `test_mcp_tools.py` covers all these behaviours with mocked GitHub API — no live network calls
**Plans**: TBD

### Phase 24: query-endpoint-v2
**Goal**: The `/query` endpoint is wired to the LangGraph orchestrator and passes a full regression suite so V2 is live without breaking any existing V1 consumer
**Depends on**: Phase 23
**Requirements**: TST-08, TST-09
**Success Criteria** (what must be TRUE):
  1. Sending a POST /query with any V1 payload (no intent_hint) streams a correct SSE response indistinguishable from V1 behaviour
  2. Sending a POST /query with `intent_hint=debug` returns a debug-structured response routed through the Debugger agent
  3. All V1 tests in `backend/tests/` pass green after the orchestrator is wired in — zero regressions
  4. Every test in the V2 test suite uses mock LLM and mock graph — the full suite runs offline with no live API calls
**Plans**: TBD

### Phase 25: extension-intent-selector
**Goal**: The VS Code sidebar exposes a clear intent selector so users can direct Nexus to explain, debug, review, or generate tests without typing intent into the query
**Depends on**: Phase 24
**Requirements**: EXT-01, EXT-02, EXT-03
**Success Criteria** (what must be TRUE):
  1. The sidebar shows five pill-style options (Auto, Explain, Debug, Review, Test) and exactly one is active at a time
  2. Selecting Debug and submitting a query sends `intent_hint: "debug"` in the request body; selecting Auto omits the field entirely
  3. The Send button label matches the selected intent: Auto → "Ask", Explain → "Explain", Debug → "Debug", Review → "Review", Test → "Test"
**Plans**: TBD

### Phase 26: extension-result-rendering
**Goal**: Debug, Review, and Test responses render in structured panels in the VS Code webview so developers can navigate suspects, findings, and generated code without leaving the editor
**Depends on**: Phase 25
**Requirements**: EXT-04, EXT-05, EXT-06, EXT-07, EXT-08, EXT-09
**Success Criteria** (what must be TRUE):
  1. A debug response renders a suspects panel with a ranked list; each entry shows file:line, an anomaly score bar, and a traversal breadcrumb chain
  2. The impact radius appears as a collapsible list; clicking any suspect reference opens the file at the correct line via Highlighter.ts
  3. A review response renders findings with severity badges (critical=red, warning=amber, info=blue), category label, description, and an expandable suggestion
  4. When `github_token` is configured, a "Post to GitHub PR" button appears on the review panel and is absent otherwise
  5. A test response renders the generated code block with syntax highlighting and either a green "File written to: {path}" badge (when Filesystem MCP succeeded) or a "Copy to clipboard" button
**Plans**: TBD

---

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 16. config-v2 | 1/1 | Complete    | 2026-03-21 |
| 17. router-agent | 2/2 | Complete    | 2026-03-21 |
| 18. debugger-agent | 2/2 | Complete    | 2026-03-21 |
| 19. reviewer-agent | 2/2 | Complete    | 2026-03-21 |
| 20. tester-agent | 2/2 | Complete   | 2026-03-21 |
| 21. critic-agent | 0/? | Not started | - |
| 22. orchestrator | 0/? | Not started | - |
| 23. mcp-tools | 0/? | Not started | - |
| 24. query-endpoint-v2 | 0/? | Not started | - |
| 25. extension-intent-selector | 0/? | Not started | - |
| 26. extension-result-rendering | 0/? | Not started | - |

---
*V2 roadmap added: 2026-03-21*
