---
phase: 23-mcp-tools
plan: 02
subsystem: testing
tags: [httpx, tenacity, mcp, github, pytest, mock, tmp_path, retry]

# Dependency graph
requires:
  - phase: 23-01
    provides: post_review_comments() and write_test_file() implementation in backend/app/mcp/tools.py

provides:
  - backend/tests/test_mcp_tools.py — 18 offline tests covering all TST-06 behaviours

affects: [24-api-integration, 25-end-to-end]

# Tech tracking
tech-stack:
  added: []
  patterns: [patch-at-module-import-path, tmp_path-filesystem-isolation, httpx-HTTPStatusError-construction, tenacity-call-count-assertion]

key-files:
  created:
    - backend/tests/test_mcp_tools.py
  modified: []

key-decisions:
  - "Patch target is 'app.mcp.tools.httpx.Client' (module-level binding), not 'httpx.Client' directly — patching at the import site intercepts the already-bound name"
  - "httpx.HTTPStatusError constructed with message + request + response args; response mock must have .status_code for _is_server_error predicate"
  - "mock_client.__enter__ and __exit__ set as MagicMock so 'with httpx.Client() as client:' context manager works in tests"
  - "Incorrect negative assertion 'acme/backend not in url' fixed inline (Rule 1 bug): URL correctly contains the substring as joined path segments; test verifies the positive pattern only"
  - "SimpleNamespace used as Finding test double to avoid importing full reviewer agent — keeps tests isolated"

patterns-established:
  - "MCP test pattern: _finding() builder + _mock_client() builder keep test bodies concise and readable"
  - "Tenacity call-count assertion: mock returns immediately so no real wait occurs; assert call_count == N verifies retry behaviour"

requirements-completed: [TST-06]

# Metrics
duration: 3min
completed: 2026-03-22
---

# Phase 23 Plan 02: MCP Tools Test Suite Summary

**18 offline tests covering all TST-06 behaviours: 10-cap/overflow, 5xx tenacity retry, 422 per-finding fallback (not retried), empty-token/None-pr no-ops, path traversal guard, extension allowlist, overwrite protection — all mocked, zero live HTTP calls**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-21T21:09:00Z
- **Completed:** 2026-03-21T21:12:12Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- Created `backend/tests/test_mcp_tools.py` with 18 offline tests covering all TST-06 requirements
- Verified 10-comment inline cap: exactly 10 findings in review batch; 12 findings produce 1 review call + 1 issues comment call
- Verified tenacity 5xx retry fires 3 times total before raising; 422 is NOT retried (call_count == 2 for batch + per-finding)
- Verified 422 batch fallback: per-finding retry loop; per-finding 422 skipped with skipped counter incremented
- Verified empty github_token and None pr_number both return early with zero API calls
- Verified path traversal ('..' in path) rejected before any Path operations
- Verified extension allowlist blocks .sh; all 7 ALLOWED_EXTENSIONS accepted
- Verified overwrite=False returns error without modifying existing file; overwrite=True replaces it
- Full suite grew from 164 to 182 tests with zero regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Write test_mcp_tools.py covering all TST-06 behaviours** - `fd6f530` (test)

**Plan metadata:** (docs commit follows)

## Files Created/Modified
- `backend/tests/test_mcp_tools.py` — 18 tests across 8 test classes: TestPostReviewCommentsHappyPath, TestPostReviewCommentsOverflowCap, TestPostReviewCommentsNoOp, TestPostReviewComments5xxRetry, TestPostReviewComments422Handling, TestWriteTestFileHappyPath, TestWriteTestFilePathTraversal, TestWriteTestFileExtensionFilter, TestWriteTestFileOverwriteProtection

## Decisions Made
- Used `SimpleNamespace` as Finding test double instead of importing the full reviewer agent — keeps tests isolated from agent module circular-import risk
- Patch target confirmed as `"app.mcp.tools.httpx.Client"` (the bound name in tools.py module), not the global `"httpx.Client"`
- `mock_client.__enter__` and `__exit__` manually set to MagicMock so the context manager protocol works without a real httpx.Client

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed incorrect negative URL assertion in test_review_url_contains_owner_and_repo**
- **Found during:** Task 1 (initial test run)
- **Issue:** The plan's assertion `assert "acme/backend" not in url` was wrong — the URL `https://api.github.com/repos/acme/backend/pulls/7/reviews` naturally contains the substring `acme/backend` as correct path segments. The test failed on a correct implementation.
- **Fix:** Removed the incorrect negative assertion; kept the positive assertion that the full correct URL path `/repos/acme/backend/pulls/7/reviews` is present; added a structural check that the URL has sufficient path segments.
- **Files modified:** backend/tests/test_mcp_tools.py
- **Verification:** Test now passes on correct URL structure
- **Committed in:** fd6f530 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug in test assertion)
**Impact on plan:** Auto-fix necessary for correctness — the test was asserting incorrect negative condition. No scope creep.

## Issues Encountered
- Test assertion in plan was logically incorrect (asserting URL does NOT contain `acme/backend` when the correct URL does contain it as path segments). Fixed inline per Rule 1.

## User Setup Required
None - no external service configuration required. All tests are fully offline.

## Next Phase Readiness
- TST-06 complete; all MCP tool behaviours verified offline
- Phase 24 (API integration) can import from app.mcp.tools with confidence all behaviours are tested
- No blockers

---
*Phase: 23-mcp-tools*
*Completed: 2026-03-22*
