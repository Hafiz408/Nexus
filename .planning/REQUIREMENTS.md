# Requirements: Nexus v2.0 Multi-Agent Team

**Defined:** 2026-03-21
**Core Value:** Grounded, graph-aware codebase intelligence — no hallucination

## v2 Requirements

### Configuration

- [x] **CONF-01**: System can be configured with `github_token`, `max_critic_loops`, `critic_threshold`, `debugger_max_hops`, `reviewer_context_hops` via environment variables, all optional with safe defaults
- [x] **CONF-02**: `.env.example` documents all new V2 environment variables

### Orchestration

- [ ] **ORCH-01**: System routes every query through a LangGraph StateGraph with typed `NexusState` (replacing V1 single LangChain runnable)
- [ ] **ORCH-02**: Graph compiles with `SqliteSaver` checkpointer so conversation state persists across requests
- [ ] **ORCH-03**: All V1 queries (without `intent_hint`) continue to work unchanged via the `explain` default path

### Router Agent

- [x] **ROUT-01**: Router classifies developer queries into `explain`, `debug`, `review`, or `test` with confidence score
- [x] **ROUT-02**: Router achieves 100% accuracy on all 12 labelled test cases in `test_router_agent.py`
- [x] **ROUT-03**: When `intent_hint` is provided, router uses it directly without an LLM call
- [x] **ROUT-04**: When confidence < 0.6, router defaults to `explain`

### Debugger Agent

- [ ] **DBUG-01**: Debugger performs forward call graph traversal (up to 4 hops via CALLS edges) from entry point functions identified in the bug description
- [ ] **DBUG-02**: Debugger scores each traversed node with an anomaly score (0.0–1.0) based on complexity, error handling, keyword match, coupling, and PageRank factors
- [ ] **DBUG-03**: Debugger performs backward traversal from top suspect to compute impact radius
- [ ] **DBUG-04**: Debugger returns ranked list of ≤5 suspect functions with `node_id`, `file_path`, `line_start`, `anomaly_score`, and reasoning
- [ ] **DBUG-05**: Debugger generates a diagnosis narrative citing only functions in the traversal path

### Reviewer Agent

- [ ] **REVW-01**: Reviewer assembles review context as: target node + 1-hop callers (predecessors) + 1-hop callees (successors)
- [ ] **REVW-02**: Reviewer generates structured `Finding` objects with `severity`, `category`, `description`, `file_path`, `line_start`, `line_end`, and `suggestion`
- [ ] **REVW-03**: When `selected_file` and `selected_range` are provided, reviewer targets the user-selected code range specifically

### Tester Agent

- [ ] **TEST-01**: Tester detects test framework from repo structure (pytest, jest, vitest, junit)
- [ ] **TEST-02**: Tester identifies all CALLS-edge callees of target functions as mock targets
- [ ] **TEST-03**: Tester generates runnable test code covering happy path, error cases, and edge cases
- [ ] **TEST-04**: Tester derives correct test file path following per-framework conventions (pytest: `tests/test_<name>.py`, jest: `__tests__/<name>.test.ts`, vitest: `<name>.test.ts`)
- [ ] **TEST-05**: Generated test code uses correct mock/patch syntax for the detected framework

### Critic Agent

- [ ] **CRIT-01**: Critic scores every specialist output on groundedness (citation accuracy), relevance, and actionability; produces an overall weighted score (0.4×G + 0.35×R + 0.25×A)
- [ ] **CRIT-02**: When overall score < 0.7 and loops < 2, critic routes back to the source agent with specific feedback
- [ ] **CRIT-03**: After 2 retry loops, critic forces `max_loops` path regardless of score (hard cap — never infinite)
- [ ] **CRIT-04**: Groundedness is pre-computed from cited node IDs vs. `retrieved_nodes` set (not LLM-estimated)

### MCP Tool Layer

- [ ] **MCP-01**: GitHub MCP posts Reviewer findings as inline PR comments (max 10 per call; excess → summary comment); skips silently if no PR context or `github_token` not set
- [ ] **MCP-02**: GitHub MCP retries on 5xx errors (3 attempts, exponential backoff); skips invalid-line findings (422) with warning
- [ ] **MCP-03**: Filesystem MCP writes Tester output to derived test file path; creates parent directories
- [ ] **MCP-04**: Filesystem MCP rejects any path containing `..` (path traversal protection)
- [ ] **MCP-05**: Filesystem MCP rejects extensions outside `.py`, `.ts`, `.js`, `.tsx`, `.jsx`, `.java`, `.go`
- [ ] **MCP-06**: Filesystem MCP returns error (not overwrite) when file exists and `overwrite=False`

### Test Suite

- [x] **TST-01**: `test_router_agent.py` — 12 labelled queries at 100% accuracy; intent_hint bypass; low-confidence fallback
- [ ] **TST-02**: `test_debugger.py` — traversal visits correct nodes; anomaly_score > 0; impact radius correct; diagnosis references traversal
- [ ] **TST-03**: `test_reviewer.py` — context includes callers + callees; findings schema valid; no hallucinated node references
- [ ] **TST-04**: `test_tester.py` — framework detection; mock targets; file path convention; ≥3 test functions; mock statements present
- [ ] **TST-05**: `test_critic.py` — groundedness math; retry routing; loop cap; feedback cleared on pass
- [ ] **TST-06**: `test_mcp_tools.py` — GitHub API mocked; 10-comment limit; path traversal rejected; extension filter; retry on 5xx
- [ ] **TST-07**: `test_orchestrator.py` — 6 integration tests (explain/debug/review/test/retry/max_loops) all pass
- [ ] **TST-08**: All V1 tests (`pytest backend/tests/`) continue to pass (zero regressions)
- [ ] **TST-09**: All V2 agent tests use mock LLM + mock graph (no live API calls in test suite)

### VS Code Extension

- [ ] **EXT-01**: Sidebar shows intent selector with 5 options: Auto, Explain, Debug, Review, Test (pill-style segmented control)
- [ ] **EXT-02**: Selected intent is sent as `intent_hint` in query request body (`auto` → omit field)
- [ ] **EXT-03**: Send button label changes per selected intent: Ask / Explain / Debug / Review / Test
- [ ] **EXT-04**: Debug response renders suspects panel: ranked list with file:line, anomaly score bar, and traversal breadcrumb chain
- [ ] **EXT-05**: Debug response renders impact radius as collapsible list; suspect references are clickable (opens file at line via Highlighter.ts)
- [ ] **EXT-06**: Review response renders findings list with severity badges (critical=red, warning=amber, info=blue), category label, description, expandable suggestion
- [ ] **EXT-07**: Review response shows "Post to GitHub PR" button when `github_token` is configured
- [ ] **EXT-08**: Test response renders generated code block with syntax highlighting
- [ ] **EXT-09**: Test response shows "File written to: {path}" badge in green when Filesystem MCP succeeded, or "Copy to clipboard" button otherwise

## v3 Requirements (deferred)

### Platform

- **PLAT-01**: GitHub Actions CI/CD pipeline
- **PLAT-02**: Production deployment (Fly.io / Render)

### Quality

- **QUAL-01**: Bug localisation accuracy benchmark (top-1 / top-3 vs ground truth)

### Languages

- **LANG-01**: Java language support
- **LANG-02**: Go language support

### Extension

- **EXT-10**: CodeLens hotspot annotations in VS Code

### Engineering

- **ENG-01**: Prompt versioning registry

## Out of Scope

| Feature | Reason |
|---------|--------|
| Modifying `explorer.py` | V1 Explorer must run unchanged — non-negotiable constraint |
| Infinite critic retry | Loop cap = 2 hard-wired — production safety |
| Live API calls in tests | All tests must be offline — CI reliability |
| Overwriting existing test files | Filesystem MCP is conservative by default — user safety |
| Routing without intent confidence fallback | Router must always produce a valid intent |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| CONF-01 | Phase 16: config-v2 | Complete |
| CONF-02 | Phase 16: config-v2 | Complete |
| ROUT-01 | Phase 17: router-agent | Complete |
| ROUT-02 | Phase 17: router-agent | Complete |
| ROUT-03 | Phase 17: router-agent | Complete |
| ROUT-04 | Phase 17: router-agent | Complete |
| TST-01 | Phase 17: router-agent | Complete |
| DBUG-01 | Phase 18: debugger-agent | Pending |
| DBUG-02 | Phase 18: debugger-agent | Pending |
| DBUG-03 | Phase 18: debugger-agent | Pending |
| DBUG-04 | Phase 18: debugger-agent | Pending |
| DBUG-05 | Phase 18: debugger-agent | Pending |
| TST-02 | Phase 18: debugger-agent | Pending |
| REVW-01 | Phase 19: reviewer-agent | Pending |
| REVW-02 | Phase 19: reviewer-agent | Pending |
| REVW-03 | Phase 19: reviewer-agent | Pending |
| TST-03 | Phase 19: reviewer-agent | Pending |
| TEST-01 | Phase 20: tester-agent | Pending |
| TEST-02 | Phase 20: tester-agent | Pending |
| TEST-03 | Phase 20: tester-agent | Pending |
| TEST-04 | Phase 20: tester-agent | Pending |
| TEST-05 | Phase 20: tester-agent | Pending |
| TST-04 | Phase 20: tester-agent | Pending |
| CRIT-01 | Phase 21: critic-agent | Pending |
| CRIT-02 | Phase 21: critic-agent | Pending |
| CRIT-03 | Phase 21: critic-agent | Pending |
| CRIT-04 | Phase 21: critic-agent | Pending |
| TST-05 | Phase 21: critic-agent | Pending |
| ORCH-01 | Phase 22: orchestrator | Pending |
| ORCH-02 | Phase 22: orchestrator | Pending |
| ORCH-03 | Phase 22: orchestrator | Pending |
| TST-07 | Phase 22: orchestrator | Pending |
| MCP-01 | Phase 23: mcp-tools | Pending |
| MCP-02 | Phase 23: mcp-tools | Pending |
| MCP-03 | Phase 23: mcp-tools | Pending |
| MCP-04 | Phase 23: mcp-tools | Pending |
| MCP-05 | Phase 23: mcp-tools | Pending |
| MCP-06 | Phase 23: mcp-tools | Pending |
| TST-06 | Phase 23: mcp-tools | Pending |
| TST-08 | Phase 24: query-endpoint-v2 | Pending |
| TST-09 | Phase 24: query-endpoint-v2 | Pending |
| EXT-01 | Phase 25: extension-intent-selector | Pending |
| EXT-02 | Phase 25: extension-intent-selector | Pending |
| EXT-03 | Phase 25: extension-intent-selector | Pending |
| EXT-04 | Phase 26: extension-result-rendering | Pending |
| EXT-05 | Phase 26: extension-result-rendering | Pending |
| EXT-06 | Phase 26: extension-result-rendering | Pending |
| EXT-07 | Phase 26: extension-result-rendering | Pending |
| EXT-08 | Phase 26: extension-result-rendering | Pending |
| EXT-09 | Phase 26: extension-result-rendering | Pending |

**Coverage:**
- v2 requirements: 46 total
- Mapped to phases: 46
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-21*
*Last updated: 2026-03-21 — traceability updated with Phase 16-26 assignments*
