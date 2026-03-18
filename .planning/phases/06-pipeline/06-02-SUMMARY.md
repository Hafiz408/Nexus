---
phase: 06-pipeline
plan: "02"
subsystem: ingestion
tags: [tree-sitter, ast-parser, thread-safety, concurrency, python]

# Dependency graph
requires:
  - phase: 06-pipeline
    provides: pipeline.py using asyncio.to_thread with 10 concurrent workers calling parse_file()
provides:
  - Thread-safe parse_file() with per-call Parser construction (no shared mutable state)
affects: [06-pipeline, ingestion-pipeline, concurrent-parsing]

# Tech tracking
tech-stack:
  added: []
  patterns: [per-call Parser construction for thread safety, Language singletons at module level]

key-files:
  created: []
  modified:
    - backend/app/ingestion/ast_parser.py

key-decisions:
  - "Parser instances constructed per parse_file() call — each thread gets its own Parser, no shared mutable state"
  - "Language singletons (PY_LANGUAGE, TS_LANGUAGE, TSX_LANGUAGE) remain at module level — read-only, safe to share"
  - "_parse_python() and _parse_typescript() accept parser as explicit parameter — keeps helpers pure, no global state dependency"

patterns-established:
  - "Thread-safety pattern: Language (read-only) at module level, Parser (mutable) at call site"

requirements-completed: [PIPE-02]

# Metrics
duration: 45min
completed: 2026-03-18
---

# Phase 6 Plan 02: AST Parser Thread Safety Summary

**Parser construction moved inside parse_file() so each asyncio.to_thread worker gets its own mutable Parser instance, eliminating shared state between 10 concurrent threads**

## Performance

- **Duration:** 45 min
- **Started:** 2026-03-18T13:07:25Z
- **Completed:** 2026-03-18T13:53:02Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- Removed module-level `py_parser`, `ts_parser`, `tsx_parser` instantiations from ast_parser.py
- Added per-call Parser construction at the top of `parse_file()` for thread isolation
- Updated `_parse_python()` and `_parse_typescript()` to accept parser as explicit parameter
- All 17 ast_parser tests pass; full suite (54 of 57 tests) passes with no regressions introduced

## Task Commits

Each task was committed atomically:

1. **Task 1: Move Parser construction inside parse_file() for thread safety** - `ed2bc50` (fix)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `backend/app/ingestion/ast_parser.py` - Removed module-level Parser singletons; added per-call construction inside parse_file(); updated helper function signatures to accept parser parameter

## Decisions Made

- Parser instances constructed per parse_file() call — each asyncio.to_thread worker gets its own Parser, preventing data corruption or segfaults under 10-way concurrency
- Language singletons remain at module level — Language objects are read-only and safe to share; keeping them module-level preserves the original performance design
- Helper functions `_parse_python()` and `_parse_typescript()` accept parser as an explicit positional parameter — keeps helpers pure (no global state dependency) and makes the data flow explicit

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

Three pre-existing test failures in `test_embedder.py` (pydantic ValidationError for `postgres_db` field) were confirmed pre-existing before this change. Not caused by or related to this plan's changes.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- parse_file() is now safe for concurrent use from asyncio.to_thread with any level of parallelism
- pipeline.py can proceed to implement the full ingestion pipeline using asyncio.to_thread(parse_file, ...) with 10 concurrent workers
- No blockers for remaining 06-pipeline plans

---
*Phase: 06-pipeline*
*Completed: 2026-03-18*

## Self-Check: PASSED

- FOUND: backend/app/ingestion/ast_parser.py
- FOUND: .planning/phases/06-pipeline/06-02-SUMMARY.md
- FOUND: commit ed2bc50
