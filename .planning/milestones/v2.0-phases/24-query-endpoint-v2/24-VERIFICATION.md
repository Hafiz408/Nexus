---
phase: 24-query-endpoint-v2
verified: 2026-03-22T00:00:00Z
status: passed
score: 10/10 must-haves verified
re_verification: false
---

# Phase 24: query-endpoint-v2 Verification Report

**Phase Goal:** The `/query` endpoint is wired to the LangGraph orchestrator and passes a full regression suite so V2 is live without breaking any existing V1 consumer
**Verified:** 2026-03-22
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | POST /query with no intent_hint (or intent_hint=auto) returns the identical V1 SSE sequence: token events, citations event, done event | VERIFIED | Gate condition `if request_body.intent_hint and request_body.intent_hint != "auto"` at line 51 of query_router.py correctly falls through to the V1 `event_generator()`. Tests 6 and 7 in test_query_router_v2.py confirm `build_graph.call_count == 0` and `event: token` is present. |
| 2 | POST /query with intent_hint=debug routes through the orchestrator and returns event: result + event: done | VERIFIED | V2 branch at lines 52-109 of query_router.py enters `v2_event_generator()`, calls `asyncio.to_thread(graph.invoke, ...)`, yields `event: result` and `event: done`. test_v2_debug_intent_returns_result_event passes. |
| 3 | All V1 tests in test_query_router.py pass without modification | VERIFIED | 9 tests pass (test output confirms: 9 passed, 0 failed). V1 generator block at lines 112-153 is completely unmodified per code inspection. |
| 4 | V1 callers sending only {question, repo_path} are never rejected with 422 | VERIFIED | All 5 V2 fields in QueryRequest use `Optional[...] = None` defaults (lines 45-49 of schemas.py). test_unindexed_repo_returns_400 and all 9 V1 tests hit the endpoint without 422. |
| 5 | test_query_router_v2.py runs fully offline — no live LLM calls, no live database | VERIFIED | All 8 tests use monkeypatch for get_status/load_graph, patch for build_graph, with MagicMock return values. No environment variables required. Suite completes in 0.35s. |
| 6 | intent_hint=debug routes to orchestrator and SSE body contains event: result with intent=debug | VERIFIED | test_v2_debug_intent_returns_result_event asserts `"event: result" in body`, `"event: done" in body`, `'"intent": "debug"' in body`, `mock_graph.invoke.call_count == 1`. PASSED. |
| 7 | intent_hint=auto falls through to the V1 path — orchestrator is NOT invoked | VERIFIED | test_v2_auto_sentinel_uses_v1_path asserts `mock_bg.call_count == 0` inside the patch context and `"event: token" in body`. PASSED. |
| 8 | intent_hint=None falls through to the V1 path — orchestrator is NOT invoked | VERIFIED | test_v2_none_intent_hint_uses_v1_path omits intent_hint entirely, asserts `mock_bg.call_count == 0` and `"event: token" in body`. PASSED. |
| 9 | Graph.invoke error is surfaced as event: error in the SSE stream | VERIFIED | test_v2_orchestrator_error_yields_error_event sets `mock_graph.invoke.side_effect = RuntimeError("graph failed")`, asserts `"event: error" in body` and `"graph failed" in body`. PASSED. |
| 10 | All tests pass when run alongside the V1 test suite (no fixture conflicts) | VERIFIED | Combined run: 17 passed (9 V1 + 8 V2) in 0.27s. Full suite: 190 passed in 3.62s. No fixture conflicts. |

**Score:** 10/10 truths verified

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/app/models/schemas.py` | QueryRequest with 5 additive optional V2 fields | VERIFIED | All 5 fields present at lines 45-49: `intent_hint: Optional[str] = None`, `target_node_id: Optional[str] = None`, `selected_file: Optional[str] = None`, `selected_range: Optional[tuple] = None`, `repo_root: Optional[str] = None`. `from typing import Optional` present at line 1. |
| `backend/app/api/query_router.py` | V2 branch gated on intent_hint; V1 path untouched below the branch | VERIFIED | Gate at line 51: `if request_body.intent_hint and request_body.intent_hint != "auto"`. V2 generator at lines 52-109. V1 comment `# V1 path (unchanged — zero modifications below this comment)` at line 111. V1 generator at lines 112-153 is unmodified. |
| `backend/tests/test_query_router_v2.py` | V2 endpoint test suite — 8 offline tests | VERIFIED | File exists, 8 test functions collected, all 8 pass in 0.35s. Docstring confirms TST-09 coverage and all-mocked approach. |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `backend/app/api/query_router.py` | `app.agent.orchestrator.build_graph` | lazy import inside v2_event_generator | VERIFIED | Line 56: `from app.agent.orchestrator import build_graph  # noqa: PLC0415` inside v2_event_generator body. No module-level import of orchestrator exists (confirmed by top-level import scan). |
| `backend/app/api/query_router.py` | `graph.invoke` | `asyncio.to_thread` | VERIFIED | Lines 85-88: `result_state = await asyncio.to_thread(graph.invoke, initial_state, {"configurable": {"thread_id": thread_id}})`. Pattern `asyncio.to_thread(graph.invoke` confirmed present. |
| `backend/tests/test_query_router_v2.py` | `app.agent.orchestrator.build_graph` | `patch()` at source module | VERIFIED (deviation documented) | Plan 02 `key_links` specified consumer-module patch `app.api.query_router.build_graph`, but actual implementation patches at `app.agent.orchestrator.build_graph` (source module). This is correct because `build_graph` is a lazy import inside the function body and is not bound in the consumer module's `__dict__` at patch time. Deviation self-documented in 24-02-SUMMARY.md and confirmed working — all 8 tests pass. |
| `backend/tests/test_query_router_v2.py` | `app.api.query_router.get_status` | `monkeypatch.setattr` | VERIFIED | All 8 tests call `monkeypatch.setattr("app.api.query_router.get_status", lambda repo_path: _make_status())`. |

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| TST-08 | 24-01-PLAN.md | All V1 tests (`pytest backend/tests/`) continue to pass (zero regressions) | SATISFIED | 9 V1 tests in test_query_router.py pass. Full suite at 190 passed. V1 generator block verified unmodified in source. All new QueryRequest fields are Optional with None defaults — no 422 risk. |
| TST-09 | 24-02-PLAN.md | All V2 agent tests use mock LLM + mock graph (no live API calls in test suite) | SATISFIED | 8 tests in test_query_router_v2.py pass in 0.35s. All external calls mocked via monkeypatch and patch(). No environment variables required. No live API calls confirmed by fast runtime and offline architecture of all patches. |

**Orphaned requirements check:** REQUIREMENTS.md traceability table maps TST-08 and TST-09 to Phase 24. Both plans claim exactly these IDs. No orphaned requirements.

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| None found | — | — | — | No TODOs, FIXMEs, empty returns, placeholders, or stub implementations found in any phase 24 modified/created file. |

Checks run:
- `TODO/FIXME/XXX/HACK/PLACEHOLDER` — none found in schemas.py, query_router.py, test_query_router_v2.py
- `return null / return {} / return []` — none found in modified files
- Empty generators or stub implementations — none found; v2_event_generator yields actual SSE events based on graph.invoke result

---

## Human Verification Required

### 1. Live V2 Request End-to-End

**Test:** Start the backend with a fully indexed repo, POST /query with `intent_hint=debug` and a `question` about a real function, observe the SSE stream.
**Expected:** SSE stream contains `event: result` with a JSON payload having `"intent": "debug"` and a `result` object with `suspects`, `traversal_path`, `impact_radius`, `diagnosis` keys.
**Why human:** Test suite mocks the orchestrator. Real orchestrator invocation through `asyncio.to_thread` with SqliteSaver and a live LangGraph graph cannot be confirmed from static analysis alone.

### 2. `data/checkpoints.db` Creation at Runtime

**Test:** Start backend from a clean state (no `data/` directory or empty `data/`), then fire a POST /query with `intent_hint=debug`.
**Expected:** `data/checkpoints.db` is created automatically by sqlite3.connect before the request fails (or alternatively the `data/` directory must pre-exist).
**Why human:** The code calls `_sqlite3.connect("data/checkpoints.db", ...)` but does not create the directory. If `data/` does not exist, the connect call will raise FileNotFoundError. Needs runtime confirmation of directory handling.

---

## Notable Findings

### Patch Target Deviation (Documented and Correct)

Plan 02's `key_links` specified `patch("app.api.query_router.build_graph")` as the intercept target. The actual implementation uses `patch("app.agent.orchestrator.build_graph")`. This is a correct deviation: `build_graph` is lazily imported inside `v2_event_generator`'s body, so at patch time it does not exist in `query_router`'s `__dict__`. Patching at the source module (`app.agent.orchestrator`) intercepts the binding correctly. The SUMMARY-02 documents this deviation explicitly. All 8 tests pass, confirming correctness.

The test file docstring at lines 12-16 contains slightly misleading text (says `app.api.query_router.build_graph intercepts that binding`) that contradicts the actual `patch()` calls, which all use `app.agent.orchestrator.build_graph`. This is a documentation-only inconsistency with no functional impact.

### V1 Test Count: 9, Not 8

The PLAN-01 stated "All 8 existing V1 tests in test_query_router.py pass" but the actual V1 test file contains 9 tests. The SUMMARY-01 correctly records "9 V1 tests". All 9 pass. This was a plan authoring discrepancy, not a defect.

### Full Suite: 190 Tests

Full backend suite runs 190 tests (confirmed by pytest output: `190 passed in 3.62s`). This matches SUMMARY-02's claim of "182 pre-existing + 8 new". TST-08 and TST-09 are both satisfied.

---

_Verified: 2026-03-22_
_Verifier: Claude (gsd-verifier)_
