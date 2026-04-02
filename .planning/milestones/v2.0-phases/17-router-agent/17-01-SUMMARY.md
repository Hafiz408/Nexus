---
phase: 17-router-agent
plan: 01
subsystem: agent
tags: [langchain, pydantic, intent-classification, llm, router, lcel]

# Dependency graph
requires:
  - phase: 16-config-v2
    provides: Settings with V2 fields (critic_threshold, etc.) and get_llm() factory via model_factory.py

provides:
  - route(question, intent_hint=None) -> IntentResult — gateway function for all V2 specialist agents
  - IntentResult Pydantic model — typed router output with intent, confidence, reasoning
  - CONFIDENCE_THRESHOLD constant (0.6)
  - _VALID_HINTS frozenset for hint bypass guard

affects: [18-debugger-agent, 19-reviewer-agent, 20-tester-agent, 21-explainer-agent, all V2 specialist agents]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Lazy get_llm() import inside function body (not module level) to prevent ValidationError during test collection when API keys absent"
    - "Pydantic with_structured_output() for LLM-driven schema enforcement"
    - "Three-path routing: hint bypass, normal LLM, low-confidence fallback"
    - "Immutable Pydantic v2 pattern: construct new IntentResult instead of mutating result.intent"

key-files:
  created:
    - backend/app/agent/router.py
  modified: []

key-decisions:
  - "get_llm() imported inside route() body (not module level) to prevent import-time ValidationError when MISTRAL_API_KEY is absent — mirrors explorer.py's _get_chain() lazy pattern but more direct"
  - "CONFIDENCE_THRESHOLD set to 0.6 — below this, fallback to explain intent regardless of LLM choice"
  - "ChatPromptTemplate.from_messages() is safe at module level (no API calls); only get_llm() requires lazy import"
  - "Low-confidence fallback constructs a new IntentResult (preserves original confidence) rather than mutating the result — Pydantic v2 models are immutable"

patterns-established:
  - "Lazy provider import pattern: from app.core.model_factory import get_llm inside function body, never at module level"
  - "Hint bypass guard: check both truthy (intent_hint) and membership (intent_hint in _VALID_HINTS) — empty string and 'auto' fall through to LLM"
  - "Low-confidence fallback: preserve original confidence value, override intent to safe default"

requirements-completed: [ROUT-01, ROUT-03, ROUT-04]

# Metrics
duration: 2min
completed: 2026-03-22
---

# Phase 17 Plan 01: Router Agent Summary

**Self-contained intent classifier with three-path routing (hint bypass, LLM, low-confidence fallback) importable without live API keys**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-22T04:48:30Z
- **Completed:** 2026-03-22T04:50:30Z
- **Tasks:** 1/1
- **Files modified:** 1

## Accomplishments

- Created `backend/app/agent/router.py` — the V2 pipeline gateway, importable without MISTRAL_API_KEY
- IntentResult Pydantic model enforces Literal intent and float confidence bounds via Pydantic validation
- Three classification paths implemented: hint bypass (confidence=1.0), normal LLM return, low-confidence fallback (override to "explain")
- 93 V1 tests still passing — zero regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Create backend/app/agent/router.py with IntentResult model and route() function** - `dc6ba3c` (feat)

## Files Created/Modified

- `backend/app/agent/router.py` — Router agent module: IntentResult model, route() function, ROUTER_PROMPT, CONFIDENCE_THRESHOLD, _VALID_HINTS

## Decisions Made

- get_llm() is imported inside route() body only — this prevents ValidationError during pytest collection when API keys are absent. This directly mirrors the lazy init pattern seen in explorer.py's _get_chain().
- ChatPromptTemplate.from_messages() is built at module level (safe — no API calls), keeping ROUTER_PROMPT reusable without re-building it on every call.
- Low-confidence fallback constructs a new IntentResult instance (preserving original confidence) rather than mutating result.intent — Pydantic v2 models are immutable by design.
- Hint bypass guard checks both truthiness and _VALID_HINTS membership so that empty string and "auto" correctly fall through to the LLM path.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- router.py is the gateway for all V2 specialist agents — Phase 18 (debugger-agent) can import and use route() directly
- Phase 18's accuracy gate tests (test_router_agent.py) can now be authored; the module is importable without live API keys
- V2 router accuracy gate: 100% on 12 labelled queries required before Phase 18 proceeds (test file will be created in the accuracy-gate test phase)

---
*Phase: 17-router-agent*
*Completed: 2026-03-22*

## Self-Check: PASSED

- backend/app/agent/router.py: FOUND
- .planning/phases/17-router-agent/17-01-SUMMARY.md: FOUND
- Commit dc6ba3c: FOUND
