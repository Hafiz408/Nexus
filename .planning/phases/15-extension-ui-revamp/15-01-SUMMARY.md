---
phase: 15-extension-ui-revamp
plan: 01
subsystem: ui
tags: [react, typescript, webview, vscode-extension, css]

# Dependency graph
requires:
  - phase: 11-vs-code-extension
    provides: App.tsx webview component and index.css stylesheet
provides:
  - Textarea that auto-grows from 1 row to max 100px as user types, then scrolls internally
  - Citation chips capped at 5 with "+N more" expand affordance per message
  - Clear chat resets expanded citation state
affects: [16-e2e-sign-off]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Synchronous scrollHeight read from e.target in onChange (not from ref after setState) to avoid stale DOM"
    - "Immutable Set update pattern for expandedCitations: new Set([...prev, msg.id])"
    - "IIFE inside JSX map callback to scope CITATION_PREVIEW / isExpanded / hiddenCount per message"

key-files:
  created: []
  modified:
    - extension/src/webview/App.tsx
    - extension/src/webview/index.css

key-decisions:
  - "scrollHeight read synchronously from e.target (not from textareaRef after setInputValue) — React batches state updates so ref DOM is stale after setState"
  - "min-height: 32px removed from .input-area textarea — fights auto-grow reset: when height is set to auto, min-height prevents collapse causing additive growth loop"
  - "expandedCitations stored as Set<string> at component level (not per-message local state) — Set approach handles clear correctly in one reset"
  - "CITATION_PREVIEW = 5 scoped inside messages.map callback as const — plan specified no module-level constant"
  - "IIFE used inside JSX to scope citation collapse vars without extracting sub-component — matches plan's inline approach"

patterns-established:
  - "Auto-grow textarea: reset to auto then set to scrollHeight synchronously in onChange"
  - "Citation collapse: slice + hiddenCount chip pattern for any list with a preview cap"

requirements-completed: [CHAT-01, CHAT-02, CHAT-03, CHAT-05]

# Metrics
duration: 2min
completed: 2026-03-21
---

# Phase 15 Plan 01: Textarea Auto-grow and Citation Collapse Summary

**Auto-growing textarea via synchronous scrollHeight mutation and citation chips capped at 5 with "+N more" per-message expand toggle**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-21T11:45:43Z
- **Completed:** 2026-03-21T11:47:55Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Textarea now grows from 1 row up to 100px (approx 5 rows) as the user types, then scrolls internally
- Textarea resets to 1 row after a message is sent (height reset to 'auto' in handleSend)
- Shift+Enter newline behavior preserved (existing handleKeyDown unchanged)
- Citation chips limited to first 5; messages with more show a "+N more" dashed chip
- Clicking "+N more" expands that specific message's citations inline
- Clearing chat resets expandedCitations so subsequent messages start collapsed

## Task Commits

Each task was committed atomically:

1. **Task 1: Textarea auto-grow** - `88333cb` (feat)
2. **Task 2: Citation collapse with +N more** - `616e6bc` (feat)

**Plan metadata:** (docs commit — final)

## Files Created/Modified

- `extension/src/webview/App.tsx` - Added textareaRef, handleInputChange, handleClear, expandedCitations state, and collapsed citation render block
- `extension/src/webview/index.css` - Removed min-height: 32px from .input-area textarea; added .citation-chip-more and .citation-chip-more:hover rules

## Decisions Made

- scrollHeight read synchronously from `e.target` in `handleInputChange` (not from `textareaRef.current` after `setInputValue`) — React batches state, ref DOM would be stale
- `min-height: 32px` removed — it prevents the `height: auto` reset from collapsing the textarea, causing additive growth on each keystroke
- `expandedCitations` as `Set<string>` at component level — correct single-reset on clear, no per-message component needed
- Build script is `npm run build` (not `npm run compile` as plan specified) — detected via `npm run` listing, confirmed `node esbuild.js` is the correct invocation

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Build script name differs from plan specification**
- **Found during:** Task 1 verification
- **Issue:** Plan specified `npm run compile` but extension package.json defines `npm run build` (maps to `node esbuild.js`)
- **Fix:** Used `npm run build` and `npm run typecheck` for verification; all checks passed
- **Files modified:** None — no code change required
- **Verification:** `npm run build` exits 0; `npm run typecheck` exits 0 with zero errors
- **Committed in:** 88333cb (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking — wrong build script name in plan)
**Impact on plan:** Trivial — correct build script discovered via `npm run` listing. No scope creep, no code changes beyond plan spec.

## Issues Encountered

None beyond the build script name difference above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Textarea auto-grow and citation collapse complete; extension UI ready for Phase 16 E2E smoke test
- No blockers

## Self-Check: PASSED

- extension/src/webview/App.tsx: FOUND
- extension/src/webview/index.css: FOUND
- .planning/phases/15-extension-ui-revamp/15-01-SUMMARY.md: FOUND
- Commit 88333cb (Task 1): FOUND
- Commit 616e6bc (Task 2): FOUND
- Build exits 0: VERIFIED
- scrollHeight in bundle: VERIFIED
- citation-chip-more in bundle: VERIFIED

---
*Phase: 15-extension-ui-revamp*
*Completed: 2026-03-21*
