---
phase: 27-wire-review-test-e2e
plan: 01
subsystem: extension
tags: [vscode, typescript, sse, review-agent, test-agent]

# Dependency graph
requires:
  - phase: 26-extension-panels
    provides: SidebarProvider, SseStream, types — extension host message plumbing and SSE stream established
provides:
  - Four context fields (target_node_id, selected_file, selected_range, repo_root) threaded from webview message through SseStream to backend POST body
  - Active editor capture (fsPath + 1-indexed selection range) in SidebarProvider case 'query'
affects:
  - 27-02 onwards — Review and Test E2E flows can now reach backend with non-None target context

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Conditional spread into POST body: ...(field ? { key: field } : {}) — omits undefined/falsy fields from request"
    - "1-indexed line range conversion: sel.start.line + 1, sel.end.line + 1 from 0-indexed VS Code Selection"
    - "Editor capture at query time (not at registration time) — avoids stale reference to closed editors"

key-files:
  created: []
  modified:
    - extension/src/types.ts
    - extension/src/SseStream.ts
    - extension/src/SidebarProvider.ts

key-decisions:
  - "selectedRange derived as undefined when selection is empty (sel.isEmpty) — avoids sending [N, N] single-line collapse as a range"
  - "repo_root forwarded as this._repoPath (same as repoPath arg) — repo_root and repoPath are identical in single-workspace setup; avoids a separate lookup"
  - "msg.target_node_id forwarded as-is from webview — future plan (27-02) populates it from citation clicks; for now always undefined"

patterns-established:
  - "Conditional POST body spread pattern for optional extension→backend fields"
  - "Active editor context captured inside case handler, not stored as instance state"

requirements-completed: [REVW-01, REVW-02, REVW-03, TEST-01, TEST-02, TEST-03, TEST-04, TEST-05, EXT-06, EXT-08]

# Metrics
duration: 3min
completed: 2026-03-25
---

# Phase 27 Plan 01: Wire Review/Test E2E Context Fields Summary

**Four context fields (target_node_id, selected_file, selected_range, repo_root) threaded from WebviewToHostMessage through SseStream POST body, with active editor capture in SidebarProvider, unblocking all Review and Test E2E backend flows**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-25T10:01:16Z
- **Completed:** 2026-03-25T10:01:40Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Added four optional fields (target_node_id?, selected_file?, selected_range?, repo_root?) to the `query` union variant of WebviewToHostMessage in types.ts
- Extended streamQuery() signature with four optional params and conditional POST body spreads (field omitted if undefined/falsy)
- SidebarProvider case 'query' now reads vscode.window.activeTextEditor at query time to capture fsPath and 1-indexed selection range, forwarding all four fields to streamQuery

## Task Commits

Each task was committed atomically:

1. **Task 1: Extend WebviewToHostMessage query type and streamQuery() signature** - `e2209c4` (feat)
2. **Task 2: Capture active editor context in SidebarProvider.ts case 'query'** - `918021d` (feat)

**Plan metadata:** _(docs commit below)_

## Files Created/Modified

- `extension/src/types.ts` - query variant extended with target_node_id?, selected_file?, selected_range?, repo_root?
- `extension/src/SseStream.ts` - streamQuery() gains 4 new optional params; POST body spreads them conditionally
- `extension/src/SidebarProvider.ts` - case 'query' reads activeTextEditor, derives selectedRange (1-indexed, undefined if empty), passes all 4 context args to streamQuery

## Decisions Made

- selectedRange set to undefined when selection is empty (sel.isEmpty) to avoid sending a degenerate [N, N] range to the backend
- repo_root forwarded as this._repoPath (same value as the existing repoPath argument) since single-workspace VS Code setups have a single root
- msg.target_node_id forwarded unchanged from webview — citation-click population is a future plan concern

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - TypeScript compiled with zero errors after both tasks.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- INT-01 is resolved: extension now sends target_node_id, selected_file, selected_range, repo_root in the POST body when the fields are available
- Review and Test backend agents will receive non-None target context, unblocking all 10 requirements listed in the plan frontmatter
- Plan 27-02 can now wire citation-click → target_node_id population in the webview UI

## Self-Check: PASSED

- FOUND: extension/src/types.ts
- FOUND: extension/src/SseStream.ts
- FOUND: extension/src/SidebarProvider.ts
- FOUND: .planning/phases/27-wire-review-test-e2e/27-01-SUMMARY.md
- FOUND: commit e2209c4 (feat: extend query type and streamQuery)
- FOUND: commit 918021d (feat: capture active editor context in SidebarProvider)

---
*Phase: 27-wire-review-test-e2e*
*Completed: 2026-03-25*
