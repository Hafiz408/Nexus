---
phase: 09-explorer-agent
plan: "01"
subsystem: agent
tags: [langchain, lcel, streaming, langsmith, openai]
dependency_graph:
  requires:
    - "08-graph-rag (CodeNode type, graph_rag_retrieve)"
    - "app.config.Settings (openai_api_key, langchain_project)"
    - "app.models.schemas.CodeNode"
  provides:
    - "explore_stream(nodes, question) async generator — consumed by Phase 10 Query Endpoint"
    - "format_context_block(nodes) pure formatter — PRD-specified code context string"
    - "SYSTEM_PROMPT constant — anti-fabrication citation rules"
  affects:
    - "Phase 10 (Query Endpoint) — will import explore_stream directly"
tech_stack:
  added:
    - "langchain-openai>=0.3.0"
    - "langsmith>=0.7.0"
  patterns:
    - "LCEL prompt | llm chain with astream() for token streaming"
    - "tracing_v2_enabled context manager wrapping astream() — one trace per invocation"
    - "Module-level _chain=None sentinel with lazy _get_chain() — prevents ValidationError on import"
key_files:
  created:
    - "backend/app/agent/__init__.py"
    - "backend/app/agent/prompts.py"
    - "backend/app/agent/explorer.py"
  modified:
    - "backend/requirements.txt"
    - "backend/app/config.py"
decisions:
  - "Lazy _get_chain() init — same pattern as embedder.py and graph_rag.py; prevents ValidationError when OPENAI_API_KEY absent at import time"
  - "tracing_v2_enabled wraps entire astream() call, not individual yield statements — avoids per-token trace explosion in LangSmith"
  - "if chunk.content: guard — first chunk from astream() is always empty string; emitting it causes malformed SSE events downstream"
  - "filter(None, [...]) in format_context_block — drops empty docstring/body_preview silently rather than emitting blank lines"
metrics:
  duration: "2 min"
  completed_date: "2026-03-19"
  tasks_completed: 2
  files_created: 3
  files_modified: 2
---

# Phase 09 Plan 01: Explorer Agent — LangChain LCEL streaming chain with LangSmith tracing

## One-liner

LangChain LCEL streaming chain (ChatOpenAI + tracing_v2_enabled) converting retrieved CodeNode context into token-streamed, citation-grounded answers via explore_stream async generator.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add dependencies and extend Settings with model_name | 2408d41 | requirements.txt, config.py, agent/__init__.py |
| 2 | Implement prompts.py and explorer.py | 597edc9 | agent/prompts.py, agent/explorer.py |

## What Was Built

### backend/app/agent/prompts.py
Contains `SYSTEM_PROMPT` constant with 5 citation rules: file:line format mandate, fabrication prohibition, uncertainty acknowledgment, conciseness requirement, and no invented names.

### backend/app/agent/explorer.py
- `format_context_block(nodes)` — pure function producing PRD-specified `--- [file_path:line_start-line_end] name (type) ---` headers per CodeNode
- `explore_stream(nodes, question)` — async generator using `prompt | llm` LCEL chain with `chain.astream()` wrapped in `tracing_v2_enabled` for LangSmith per-invocation tracing
- `_get_chain()` — lazy init returning cached chain; ChatOpenAI constructed only on first call to prevent ValidationError when OPENAI_API_KEY absent

### requirements.txt and config.py
- Added `langchain-openai>=0.3.0` and `langsmith>=0.7.0`
- Added `model_name: str = "gpt-4o-mini"` to Settings (overridable via .env)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] langchain_core not installed in environment**
- **Found during:** Task 2 verification
- **Issue:** `ModuleNotFoundError: No module named 'langchain_core'` when running import verification
- **Fix:** Ran `pip install "langchain-openai>=0.3.0" "langsmith>=0.7.0"` to install packages
- **Files modified:** None (environment-level install, not code change)
- **Commit:** N/A (environment fix, no code change needed)

## Verification Results

All plan verification steps passed:
1. `python -c "from app.agent.prompts import SYSTEM_PROMPT; assert 'fabricate' in SYSTEM_PROMPT"` — PASSED
2. `format_context_block([n])` produces `--- [/repo/a.py:1-5] f (function) ---\ndef f():` — PASSED
3. `grep langchain-openai backend/requirements.txt` — PASSED
4. `grep model_name backend/app/config.py` — PASSED
5. Import of explorer.py does not raise ValidationError without OPENAI_API_KEY — PASSED

## Self-Check: PASSED
