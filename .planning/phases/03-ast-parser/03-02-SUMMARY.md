---
phase: 03-ast-parser
plan: "02"
subsystem: parsing
tags: [tree-sitter, ast, python, typescript, code-nodes, TDD]

# Dependency graph
requires:
  - phase: 03-01
    provides: CodeNode and CodeEdge Pydantic v2 models, tree-sitter 0.25.x dependencies pinned
  - phase: 01-infrastructure
    provides: FastAPI app structure and app.models module layout

provides:
  - parse_file() dispatcher for python and typescript source files
  - _parse_python() extracting function/class/method nodes with docstrings, complexity, CALLS/IMPORTS edges
  - _parse_typescript() extracting function_declaration, class_declaration, method_definition, and arrow_function nodes
  - Full test suite (17 tests) covering Python parsing, TypeScript parsing, edge cases
  - Updated conftest.py with python_sample_file and typescript_sample_file fixtures

affects:
  - 04-graph-builder
  - 05-embedder
  - 06-semantic-search
  - 09-api-layer

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "QueryCursor(Query).captures(node) — tree-sitter 0.25.x API for running queries (query.captures() removed)"
    - "Module-level language+parser singletons — created once at import time, reused for all parse_file() calls"
    - "Raw edge tuples (source_id, target_name, edge_type) — unresolved; Graph Builder (Phase 4) resolves to node_ids"
    - "class_ranges list for method detection — Python classes detected first, functions checked against ranges"
    - "_first_name_for() helper — finds name node within a definition node's byte range across all capture lists"

key-files:
  created:
    - backend/app/ingestion/ast_parser.py
    - backend/tests/test_ast_parser.py
  modified:
    - backend/tests/conftest.py

key-decisions:
  - "QueryCursor(Query).captures() used instead of query.captures() — tree-sitter 0.25.x removed the old API"
  - "Query() constructor used (not lang.query()) — lang.query() is deprecated in 0.25.x"
  - "raw_edges returned as (source_id, target_name, edge_type) tuples not CodeEdge objects — Graph Builder resolves targets"
  - "IMPORTS edges attached to file-level 'rel_path::__module__' source_id — avoids requiring a module node in graph"
  - "TypeScript query re-compiled per call with correct dialect language — ensures TSX vs TS correctness"

patterns-established:
  - "TDD: RED commit (test) then GREEN commit (feat) — two atomic commits per TDD feature"
  - "parse_file() returns ([], []) for unsupported languages and empty files — explicit guard pattern"

requirements-completed: [PARSE-01, PARSE-02, PARSE-03, PARSE-07, PARSE-08, TEST-03]

# Metrics
duration: 4min
completed: 2026-03-18
---

# Phase 3 Plan 02: AST Parser Summary

**parse_file() with full Python + TypeScript AST parsing via tree-sitter 0.25.x, returning CodeNode objects and raw CALLS/IMPORTS edge tuples**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-18T11:40:27Z
- **Completed:** 2026-03-18T11:44:14Z
- **Tasks:** 2 (RED + GREEN)
- **Files modified:** 3

## Accomplishments

- parse_file() correctly returns 4 CodeNode objects for a Python file with 2 functions + 1 class + 1 method
- Docstrings extracted without delimiter characters via string_content child node inspection
- TypeScript parser extracts all 4 node types: function_declaration, class_declaration, method_definition, arrow_function
- CALLS edges detected for function calls within method bodies; IMPORTS edges for import statements
- 17 tests pass (test_ast_parser.py) plus 12 regression tests (test_file_walker.py) — 29/29 total

## Task Commits

Each task was committed atomically:

1. **Task 1: RED — conftest fixtures + failing tests** - `978fa37` (test)
2. **Task 2: GREEN — ast_parser.py implementation** - `9df576f` (feat)

_Note: TDD tasks have two commits (test RED then feat GREEN)_

## Files Created/Modified

- `backend/app/ingestion/ast_parser.py` - parse_file() dispatcher + _parse_python() + _parse_typescript() implementations (357 lines)
- `backend/tests/test_ast_parser.py` - 17-test suite covering Python parsing, TypeScript parsing, and edge cases
- `backend/tests/conftest.py` - Added python_sample_file and typescript_sample_file fixtures (preserves sample_repo_path)

## Decisions Made

- QueryCursor(Query).captures() used instead of query.captures() — tree-sitter 0.25.x removed captures() from the Query object; QueryCursor wraps it
- Query() constructor preferred over lang.query() — lang.query() is deprecated in 0.25.x (emits DeprecationWarning)
- Raw edge tuples (source_id, target_name, edge_type) returned instead of CodeEdge objects — target_name is unresolved at parse time; Graph Builder (Phase 4) resolves to full node_ids
- IMPORTS edges attached to synthetic "rel_path::__module__" source_id — no need for a file-level node in the graph
- TypeScript query re-compiled per dialect inside _parse_typescript() — ensures TS vs TSX queries run against correct Language instance

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed tree-sitter 0.25.x QueryCursor API**
- **Found during:** Task 2 (GREEN — ast_parser.py implementation), first test run
- **Issue:** Plan specified `query.captures(node)` but tree-sitter 0.25.x removed `captures()` from the `Query` object entirely; the method moved to `QueryCursor`
- **Fix:** Replaced all `query.captures(node)` calls with `QueryCursor(query).captures(node)`; replaced `lang.query(...)` with `Query(lang, ...)` constructor to avoid deprecation warnings
- **Files modified:** backend/app/ingestion/ast_parser.py
- **Verification:** All 17 tests pass after fix
- **Committed in:** 9df576f (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 — API bug)
**Impact on plan:** Required fix to match installed tree-sitter 0.25.x API. No scope creep; same behavior, different call site.

## Issues Encountered

- tree-sitter 0.25.x changed `Query.captures()` to require a `QueryCursor` wrapper. The plan's docstring noted "captures() returns dict[str, list[Node]]" which was correct for the return format but the call site changed. Discovered on first test run, fixed immediately per Rule 1.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- ast_parser.py is ready; parse_file() API is stable and fully tested
- Graph Builder (Phase 4) can import parse_file() and process raw edge tuples
- TypeScript constructor nodes (not in scope for this plan) can be added later without API changes
- No blockers

---
*Phase: 03-ast-parser*
*Completed: 2026-03-18*
