---
phase: 12-highlighter
plan: 01
subsystem: ui
tags: [vscode, TextEditorDecorationType, ThemeColor, SSE, citations, highlighting]

# Dependency graph
requires:
  - phase: 11-vs-code-extension
    provides: SidebarProvider, SseStream, extension.ts wiring, Citation type in types.ts

provides:
  - HighlightService class managing a single TextEditorDecorationType with findMatchHighlightBackground
  - highlightCitations groups by file_path, opens docs with preserveFocus, decorates line ranges
  - clearHighlights empties decorations and cancels auto-clear timer
  - dispose frees TextEditorDecorationType on extension deactivation
  - streamQuery extended with optional onCitations callback
  - SidebarProvider wired to clear + apply highlights per query lifecycle
  - extension.ts registers provider.dispose() in subscriptions

affects: [13-any-future-phase-using-SidebarProvider, citation-ui]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Single TextEditorDecorationType created once in constructor, reused across all queries
    - onCitations callback pattern for decoupled SSE-to-UI wiring
    - preserveFocus + preview:false for non-disruptive file opening
    - Guard (editor.document) before setDecorations to avoid vscode#18797 race condition

key-files:
  created:
    - extension/src/HighlightService.ts
  modified:
    - extension/src/SseStream.ts
    - extension/src/SidebarProvider.ts
    - extension/src/extension.ts

key-decisions:
  - "Single TextEditorDecorationType created in constructor (never per-query) — per-query creation causes memory leak (HIGH-02)"
  - "clearHighlights() called at the top of highlightCitations() so a new query always replaces old decorations before opening files"
  - "setTimeout 10_000ms scheduled after all file groups processed — timer starts only after all decoration calls complete"
  - "preserveFocus: true + preview: false in showTextDocument — avoids stealing user focus and prevents disposable preview tabs"
  - "Guard if (editor.document) before setDecorations — prevents 'setDecorations on invisible editor' warning (vscode#18797 race)"
  - "onCitations callback passed as 5th optional param to streamQuery — keeps SseStream free of HighlightService dependency"
  - "provider.dispose() pushed to context.subscriptions — guarantees TextEditorDecorationType.dispose() runs on extension deactivation"

patterns-established:
  - "Decoration lifecycle: create once in constructor, clear before each use, dispose on deactivation"
  - "Callback injection via optional function param for cross-service wiring without tight coupling"

requirements-completed: [HIGH-01, HIGH-02]

# Metrics
duration: 2min
completed: 2026-03-19
---

# Phase 12 Plan 01: Citation Highlighting Summary

**HighlightService with single TextEditorDecorationType (findMatchHighlightBackground) wired into SseStream onCitations callback — highlights cited file:line ranges, auto-clears after 10 seconds, clears on new query, disposes cleanly on deactivation**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-19T11:29:20Z
- **Completed:** 2026-03-19T11:31:56Z
- **Tasks:** 3 (2 auto + 1 checkpoint auto-approved)
- **Files modified:** 4

## Accomplishments

- Created `HighlightService.ts` with TextEditorDecorationType using findMatchHighlightBackground theme color (adapts to dark/light/high-contrast)
- Wired `onCitations` callback into `streamQuery` in SseStream.ts, routed through SidebarProvider to trigger highlighting after each query
- Registered `provider.dispose()` in `context.subscriptions` so HighlightService.dispose() is guaranteed to run on extension deactivation

## Task Commits

Each task was committed atomically:

1. **Task 1: Create HighlightService.ts** - `4490918` (feat)
2. **Task 2: Wire HighlightService into SseStream, SidebarProvider, extension.ts** - `1550423` (feat)
3. **Task 3: Checkpoint — auto-approved** - (no separate commit; all checks passed, no code changes)

**Plan metadata:** (docs commit — see below)

## Files Created/Modified

- `extension/src/HighlightService.ts` - New: TextEditorDecorationType management — highlightCitations, clearHighlights, dispose
- `extension/src/SseStream.ts` - Added optional `onCitations` callback param; invoked in `case 'citations'` branch
- `extension/src/SidebarProvider.ts` - Added HighlightService field + constructor init; clearHighlights before query; onCitations callback to streamQuery; public dispose() method
- `extension/src/extension.ts` - Added `context.subscriptions.push({ dispose: () => provider.dispose() })`

## Decisions Made

- Single `TextEditorDecorationType` created in the constructor (not per-query) to avoid the memory leak that would occur if a new decoration type was created for each query (HIGH-02).
- `clearHighlights()` is the first call inside `highlightCitations()` so any pending timer is cancelled and old decorations are cleared before new file groups are processed.
- `setTimeout(10_000)` is scheduled after the full file-group loop so the timer begins only after all decorations are applied.
- `preserveFocus: true, preview: false` in `showTextDocument` — avoids stealing user focus from the chat panel and prevents the file opening in a disposable preview tab that would be replaced on the next navigation.
- Guard `if (editor.document)` before `setDecorations` to avoid VS Code warning in microsoft/vscode#18797.
- `onCitations` added as optional 5th parameter to `streamQuery` (not a required change to the function signature's consumers) — keeps SseStream decoupled from HighlightService.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Citation highlighting is fully wired end-to-end; the next phase can build on this or refine the UX (e.g., showing a "jump to highlight" button in the chat panel).
- No blockers.

## Self-Check

Files exist:
- extension/src/HighlightService.ts: FOUND
- extension/src/SseStream.ts: FOUND (modified)
- extension/src/SidebarProvider.ts: FOUND (modified)
- extension/src/extension.ts: FOUND (modified)

Commits:
- 4490918: FOUND (Task 1)
- 1550423: FOUND (Task 2)

TypeScript: 0 errors (npx tsc --noEmit passed)

## Self-Check: PASSED

---
*Phase: 12-highlighter*
*Completed: 2026-03-19*
