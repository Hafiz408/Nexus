---
phase: 27-wire-review-test-e2e
plan: "03"
subsystem: api, ui, extension
tags: [react, typescript, fastapi, pydantic, github, mcp, sse]

# Dependency graph
requires:
  - phase: 27-01
    provides: Context fields threaded from webview through SseStream to backend
  - phase: 26-03
    provides: ReviewPanel component + postReviewToPR stub in SidebarProvider
  - phase: 23-01
    provides: post_review_comments() MCP tool fully implemented and unit-tested

provides:
  - Full end-to-end GitHub PR commenting flow: button click -> inline form -> backend call -> GitHub
  - Extended postReviewToPR union type carrying findings/repo/pr_number/commit_sha
  - Inline PR context form in ReviewPanel (3 inputs + submit/cancel)
  - SidebarProvider case 'postReviewToPR' posting to /review/post-pr endpoint
  - Backend POST /review/post-pr endpoint calling post_review_comments() with server-side token

affects:
  - Phase 28+ integration tests
  - Any future GitHub PR flow enhancements

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Inline form pattern for collecting context in webview before postMessage (avoids message round-trip)"
    - "Server-side token pattern: extension never receives github_token; backend uses settings.github_token"
    - "Pydantic BaseModel for FastAPI request body with private underscore-prefixed class name"

key-files:
  created: []
  modified:
    - extension/src/types.ts
    - extension/src/webview/App.tsx
    - extension/src/SidebarProvider.ts
    - backend/app/api/query_router.py

key-decisions:
  - "Inline form in ReviewPanel (showPrForm/prRepo/prNumber/prSha state) avoids a new message round-trip through SidebarProvider for collecting PR context"
  - "HTTPException already imported at module level in query_router.py — no lazy import needed for it inside endpoint body"
  - "_PostPRRequest uses pydantic BaseModel imported as _BaseModel with underscore prefix for private-style naming"
  - "Lazy imports for get_settings and post_review_comments inside endpoint body — consistent with all V2 agent patterns"

patterns-established:
  - "Inline form pattern: when webview needs multi-field input before postMessage, render state-controlled form directly rather than adding a new message round-trip"

requirements-completed:
  - MCP-01
  - MCP-03
  - EXT-07
  - EXT-09

# Metrics
duration: 3min
completed: 2026-03-25
---

# Phase 27 Plan 03: Wire Review-to-PR E2E Summary

**Full GitHub PR commenting path operational: inline form collects repo/PR/SHA, SidebarProvider POSTs to /review/post-pr, backend calls post_review_comments() with server-side GITHUB_TOKEN**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-25T12:19:27Z
- **Completed:** 2026-03-25T12:22:47Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Extended `postReviewToPR` type union to carry `findings`, `repo`, `pr_number`, `commit_sha`
- Added 3-field inline PR form in `ReviewPanel` (owner/repo, PR number, commit SHA) with Submit/Cancel; form validates all inputs before dispatching `postMessage`
- Replaced TODO stub in `SidebarProvider` with real `fetch POST` to `/review/post-pr`; shows success count or error message to user
- Added `_PostPRRequest` Pydantic model and `POST /review/post-pr` endpoint to `query_router.py`; endpoint calls `post_review_comments()` using `settings.github_token` — token never exposed to extension
- INT-02 closed: `post_review_comments()` now has a production call site

## Task Commits

Each task was committed atomically:

1. **Task 1: Extend postReviewToPR type + ReviewPanel inline form** - `931ac60` (feat)
2. **Task 2: Wire SidebarProvider + backend POST /review/post-pr** - `a22e614` (feat)

**Plan metadata:** (docs commit below)

## Files Created/Modified

- `extension/src/types.ts` - `postReviewToPR` union extended with findings/repo/pr_number/commit_sha
- `extension/src/webview/App.tsx` - `ReviewPanel` inline PR form with 4 new state variables + submit handler
- `extension/src/SidebarProvider.ts` - `case 'postReviewToPR'` replaced TODO stub with fetch POST to `/review/post-pr`
- `backend/app/api/query_router.py` - `_PostPRRequest` Pydantic model + `POST /review/post-pr` endpoint

## Decisions Made

- Inline form approach chosen over message round-trip (`requestPRContext` / response) — simpler, fewer moving parts, no new message types required
- `HTTPException` already at module level in `query_router.py` — no lazy import needed for it inside the endpoint body
- Lazy imports for `get_settings` and `post_review_comments` inside endpoint body — consistent with established V2 agent pattern (STATE.md Phases 17-24)
- `_PostPRRequest` uses underscore-prefixed name to signal internal use; inherits from `_BaseModel` alias for clean separation from project's main `BaseModel` usage

## Deviations from Plan

None — plan executed exactly as written. The note in the plan about `HTTPException` already being at module level was correctly applied.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required for this plan. GitHub token must be set in server environment (`GITHUB_TOKEN`) for the endpoint to function at runtime, but that was already a prerequisite from Phase 16/23.

## Next Phase Readiness

- INT-02 resolved: end-to-end GitHub PR commenting is production-ready
- Plan 04 can add CSS for `.pr-form`, `.pr-form-input`, `.pr-form-actions`, `.pr-form-submit`, `.pr-form-cancel` classes referenced in App.tsx
- 191 backend tests passing; TypeScript compiles clean

---
*Phase: 27-wire-review-test-e2e*
*Completed: 2026-03-25*
