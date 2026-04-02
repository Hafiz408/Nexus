---
phase: 23-mcp-tools
plan: 01
subsystem: api
tags: [httpx, tenacity, mcp, github, filesystem, retry]

# Dependency graph
requires:
  - phase: 22-orchestrator
    provides: NexusState and agent pipeline that MCP tools serve
  - phase: 19-reviewer-agent
    provides: Finding model used by post_review_comments()
  - phase: 20-tester-agent
    provides: TestResult model with test_file_path used by write_test_file()
  - phase: 16-config-v2
    provides: github_token setting (defaults to "" empty string)
provides:
  - backend/app/mcp/__init__.py — MCP package marker
  - backend/app/mcp/tools.py — post_review_comments() and write_test_file() public API
  - httpx and tenacity in requirements.txt
affects: [24-api-integration, 25-end-to-end]

# Tech tracking
tech-stack:
  added: [httpx>=0.27.0, tenacity>=8.2.0]
  patterns: [tenacity-5xx-only-retry, httpx-context-manager, path-traversal-guard-before-path-ops, falsy-token-guard]

key-files:
  created:
    - backend/app/mcp/__init__.py
    - backend/app/mcp/tools.py
  modified:
    - backend/requirements.txt

key-decisions:
  - "httpx.Client used as context manager (with httpx.Client() as client) so tests can patch app.mcp.tools.httpx.Client consistently"
  - "tenacity _is_server_error predicate checks 500 <= status_code < 600 ONLY — 422 is permanent client error, never retried"
  - "Path traversal guard checks '..' in str(test_file_path) BEFORE any Path() construction — Path.resolve() strips '..' making check ineffective after resolution"
  - "github_token guard uses 'if not github_token' (falsy), not 'is None' — setting defaults to empty string per Phase 16 decision"
  - "post_review_comments() 10-comment cap: first 10 as inline review, overflow as single issue comment"
  - "422 batch fallback: retry each finding individually, skip per-finding 422 with warning, raise on other status codes"
  - "httpx and tenacity imported at module top (not lazy) — MCP tools have no get_llm()/get_settings() at module level; no ValidationError risk"

patterns-established:
  - "MCP layer pattern: side-effect I/O functions in app/mcp/ separate from agent logic — no circular imports"
  - "Retry predicate pattern: _is_server_error checks isinstance + status range, passed to retry_if_exception()"
  - "Path safety pattern: string check BEFORE Path construction, extension allowlist BEFORE filesystem ops"

requirements-completed: [MCP-01, MCP-02, MCP-03, MCP-04, MCP-05, MCP-06]

# Metrics
duration: 1min
completed: 2026-03-22
---

# Phase 23 Plan 01: MCP Tools Summary

**MCP tool layer with GitHub PR inline comment posting (10-cap + overflow, 5xx retry, 422 per-finding fallback) and safe filesystem test writer (path traversal guard, extension allowlist, overwrite protection) using httpx context manager and tenacity**

## Performance

- **Duration:** 1 min
- **Started:** 2026-03-21T21:06:25Z
- **Completed:** 2026-03-21T21:07:53Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Created `backend/app/mcp/` package with `post_review_comments()` and `write_test_file()` public API
- Implemented tenacity-backed retry for 5xx only (not 422) with exponential backoff up to 3 attempts
- Implemented 422 batch fallback: retry per-finding individually, skip invalid line positions with warning
- Path traversal guard checks raw string before any Path() construction; extension allowlist enforced before filesystem ops
- All 164 existing tests remain green after adding the new package

## Task Commits

Each task was committed atomically:

1. **Task 1: Add httpx and tenacity to requirements.txt** - `70c9113` (chore)
2. **Task 2: Implement backend/app/mcp/tools.py with both MCP functions** - `9c9f13e` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified
- `backend/app/mcp/__init__.py` — Empty package marker for mcp module
- `backend/app/mcp/tools.py` — post_review_comments(), write_test_file(), ALLOWED_EXTENSIONS, _post_with_retry(), _is_server_error()
- `backend/requirements.txt` — Added httpx>=0.27.0 and tenacity>=8.2.0

## Decisions Made
- httpx.Client used as context manager so test patches against `app.mcp.tools.httpx.Client` are consistent
- tenacity _is_server_error: `500 <= status_code < 600` exclusively — 422 is a permanent client error for invalid line position, must not be retried
- Path traversal check on raw string before any Path() call — Path.resolve() normalizes ".." making the guard ineffective if applied after
- github_token falsy check (`if not github_token`) per Phase 16 decision that the setting defaults to `""` not `None`
- Module-level httpx/tenacity imports (not lazy) — safe because MCP tools have no get_settings()/get_llm() at import time

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required. GitHub token is optional; functions no-op when empty.

## Next Phase Readiness
- MCP tool layer complete; post_review_comments() and write_test_file() are ready for wiring into the orchestrator API
- Phase 24 (API integration) can import from app.mcp.tools directly
- No blockers

---
*Phase: 23-mcp-tools*
*Completed: 2026-03-22*
