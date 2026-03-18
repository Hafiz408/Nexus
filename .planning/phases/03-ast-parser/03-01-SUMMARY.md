---
phase: 03-ast-parser
plan: "01"
subsystem: api
tags: [pydantic, tree-sitter, code-parsing, schemas]

# Dependency graph
requires:
  - phase: 01-infrastructure
    provides: FastAPI app with pydantic v2 already installed
  - phase: 02-file-walker
    provides: walk_repo() which discovers files that ast_parser will receive
provides:
  - CodeNode Pydantic v2 model with 11 fields (node_id, name, type, file_path, line_start, line_end, signature, docstring, body_preview, complexity, embedding_text)
  - CodeEdge Pydantic v2 model with 3 fields (source_id, target_name, edge_type)
  - tree-sitter==0.25.2 + tree-sitter-python==0.25.0 + tree-sitter-typescript==0.23.2 pinned in requirements.txt
  - backend/app/models/ package with schemas.py
affects: [03-ast-parser, 04-graph-builder, 05-embedder, 06-query-engine, 07-api-routes, 08-retriever, 09-explorer-agent]

# Tech tracking
tech-stack:
  added:
    - tree-sitter==0.25.2
    - tree-sitter-python==0.25.0
    - tree-sitter-typescript==0.23.2
  patterns:
    - "Pydantic v2 models using str | None union syntax (Python 3.10+ idiom)"
    - "Pinned dependency versions to prevent API-breaking pip updates"

key-files:
  created:
    - backend/app/models/__init__.py
    - backend/app/models/schemas.py
  modified:
    - backend/requirements.txt

key-decisions:
  - "Used str | None union syntax (not Optional[str]) — idiomatic Pydantic v2 / Python 3.11 target"
  - "Pinned tree-sitter to exact versions (==) not >= — tree-sitter API changed significantly at 0.21; pinning prevents silent breakage from pip updates"
  - "tree-sitter-typescript 0.23.2 uses language_typescript() and language_tsx() (not .language()) — documented in schemas to prevent downstream pitfall"
  - "embedding_text field is a plain str default empty — populated by ast_parser.py (Plan 03-02), not auto-computed in the model"

patterns-established:
  - "Pattern 1: CodeNode.node_id format is relative_file_path::name (forward-slash normalized)"
  - "Pattern 2: All consumer phases import from app.models.schemas, never define their own CodeNode"

requirements-completed: [PARSE-04, PARSE-05, PARSE-06]

# Metrics
duration: 1min
completed: 2026-03-18
---

# Phase 3 Plan 01: CodeNode/CodeEdge Schemas and tree-sitter Dependencies Summary

**CodeNode (11 fields) and CodeEdge (3 fields) Pydantic v2 models created as shared data contract; tree-sitter 0.25.2 + tree-sitter-python 0.25.0 + tree-sitter-typescript 0.23.2 pinned and verified importable**

## Performance

- **Duration:** 1 min
- **Started:** 2026-03-18T11:37:13Z
- **Completed:** 2026-03-18T11:38:11Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Created `backend/app/models/schemas.py` with `CodeNode` (11 fields) and `CodeEdge` (3 fields) using Pydantic v2; importable from `app.models.schemas`
- Pinned all three tree-sitter packages at exact versions in `requirements.txt` and verified installation with Language object construction for Python, TypeScript, and TSX grammars
- Established shared data contract for Phases 3-9 — all AST parser, graph builder, embedder, and query phases consume `CodeNode`

## Task Commits

Each task was committed atomically:

1. **Task 1: Create CodeNode and CodeEdge Pydantic models** - `c08a547` (feat)
2. **Task 2: Add tree-sitter dependencies to requirements.txt** - `43792db` (chore)

**Plan metadata:** _(docs commit — see below)_

## Files Created/Modified

- `backend/app/models/__init__.py` - Package marker for models module
- `backend/app/models/schemas.py` - CodeNode and CodeEdge Pydantic v2 models
- `backend/requirements.txt` - Added three pinned tree-sitter dependencies

## Decisions Made

- Used `str | None` union syntax (not `Optional[str]`) — idiomatic for Pydantic v2 + Python 3.11 project target
- Pinned tree-sitter to exact versions with `==` rather than `>=` — the library had major breaking API changes at 0.21 (captures() return type, Parser constructor, Language construction) and pinning prevents silent future breakage
- `embedding_text` field is stored as a plain `str` with default `""` — it is computed and populated by `ast_parser.py` (Plan 03-02), not auto-computed inside the model itself

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required. tree-sitter packages are installed via pip into the local Python environment.

## Next Phase Readiness

- `app.models.schemas` is importable; `CodeNode` and `CodeEdge` are ready for consumption by `ast_parser.py` (Plan 03-02)
- All three tree-sitter Language objects construct without error (`PY_LANGUAGE`, `TS_LANGUAGE`, `TSX_LANGUAGE` pattern is ready)
- No blockers for Phase 3 Plan 02 (ast_parser.py implementation)

---
*Phase: 03-ast-parser*
*Completed: 2026-03-18*

## Self-Check: PASSED

- FOUND: backend/app/models/__init__.py
- FOUND: backend/app/models/schemas.py
- FOUND: 03-01-SUMMARY.md
- FOUND commit: c08a547 (feat: CodeNode and CodeEdge models)
- FOUND commit: 43792db (chore: tree-sitter dependencies)
