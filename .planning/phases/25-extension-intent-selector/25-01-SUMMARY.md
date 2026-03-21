---
phase: 25-extension-intent-selector
plan: 01
subsystem: ui
tags: [vscode-extension, react, typescript, intent-selector, sse]

# Dependency graph
requires:
  - phase: 24-query-endpoint-v2
    provides: V2 /query endpoint gated on intent_hint field in POST body; None/"auto" fall-through to V1
provides:
  - Five intent-selector pill buttons (Auto/Explain/Debug/Review/Test) in VS Code sidebar
  - intent_hint field threaded from webview postMessage through SidebarProvider to SseStream POST body
  - INTENT_LABELS map driving dynamic send button label (Ask/Explain/Debug/Review/Test)
affects:
  - 26-extension-v2-context (if any — depends on sidebar UX additions)
  - End-to-end V2 agent routing from extension UI to backend

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "intent_hint omit-vs-send: Auto sends undefined (field absent), named intents send the string; never send 'auto'"
    - "CSS !important cascade override: pill background/border use !important to override global button reset"
    - "useCallback dependency array extended with selectedIntent to avoid stale-closure bug"

key-files:
  created: []
  modified:
    - extension/src/types.ts
    - extension/src/SseStream.ts
    - extension/src/SidebarProvider.ts
    - extension/src/webview/App.tsx
    - extension/src/webview/index.css

key-decisions:
  - "Auto intent sends undefined (not the string 'auto') — backend V2 gate is `intent_hint not None and not 'auto'`; sending 'auto' would silently degrade to V1 path"
  - "CSS !important required on pill background and border — global button reset at file top applies background:transparent !important and border:none !important to ALL buttons, winning by specificity otherwise"
  - "Pill selection is sticky (not reset after send) — selectedIntent state persists across queries; user changes intent explicitly"
  - "INTENT_LABELS['auto'] = 'Ask' so the send button reads Ask by default with no special-casing needed"

patterns-established:
  - "Intent selector pattern: type IntentOption union + INTENT_LABELS record + INTENT_OPTIONS array as constants outside component"
  - "Conditional spread pattern: ...(intentHint ? { intent_hint: intentHint } : {}) — field absent when falsy"

requirements-completed: [EXT-01, EXT-02, EXT-03]

# Metrics
duration: 3min
completed: 2026-03-22
---

# Phase 25 Plan 01: Extension Intent Selector Summary

**Five-pill intent selector (Auto/Explain/Debug/Review/Test) wired from sidebar UI through SidebarProvider and SseStream into the V2 /query POST body as intent_hint**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-03-21T21:46:56Z
- **Completed:** 2026-03-21T21:49:00Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- Extended `WebviewToHostMessage` 'query' variant with `intent_hint?: string` in types.ts
- Added `intentHint?: string` parameter to `streamQuery()` with conditional spread into POST body — field absent when Auto, value sent when named intent
- Forwarded `msg.intent_hint` from `SidebarProvider` case 'query' to `streamQuery()` as last argument
- Added `IntentOption` type, `INTENT_LABELS`, `INTENT_OPTIONS` constants, `selectedIntent` state, pill JSX, and dynamic send button label to `App.tsx`
- Appended `intent-selector`, `intent-pill`, `.active`, `:hover`, `:disabled` CSS with `!important` overrides to `index.css`

## Task Commits

Each task was committed atomically:

1. **Task 1: Extend message contract and thread intent_hint through host** - `e261d1e` (feat)
2. **Task 2: Add intent selector UI state, pill JSX, and pill CSS** - `4f4c8b3` (feat)

**Plan metadata:** pending docs commit

## Files Created/Modified
- `extension/src/types.ts` - Added `intent_hint?: string` to 'query' variant of WebviewToHostMessage
- `extension/src/SseStream.ts` - Added `intentHint?: string` parameter; conditional spread `...(intentHint ? { intent_hint: intentHint } : {})` into POST body
- `extension/src/SidebarProvider.ts` - Added `msg.intent_hint` as last argument to `streamQuery()` call in case 'query'
- `extension/src/webview/App.tsx` - IntentOption type + INTENT_LABELS + INTENT_OPTIONS; selectedIntent state; updated postMessage with intent_hint guard; intent-selector JSX; dynamic button label
- `extension/src/webview/index.css` - Appended intent-selector, intent-pill, .active, :hover, :disabled rules with !important on background/border

## Decisions Made
- **Auto omits field, not sends "auto":** When `selectedIntent === 'auto'`, `intent_hint` is `undefined` — JSON.stringify omits it. The backend V2 gate checks `intent_hint not None and not 'auto'`; sending the string "auto" would silently fall through to V1. The guard `selectedIntent !== 'auto' ? selectedIntent : undefined` enforces this.
- **!important on pill CSS:** The global button reset at the top of index.css applies `background: transparent !important` and `border: none !important` to all buttons, winning specificity contests. Pill styles need `!important` on the same properties to take effect.
- **Sticky pill selection:** `selectedIntent` is not reset after a send. Users can ask multiple follow-up queries under the same intent without re-clicking. Consistent with the plan's "Pill selection is sticky" truth.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- EXT-01, EXT-02, EXT-03 complete: Five pills render, exactly one active, Auto omits intent_hint, named intents send intent_hint, button label reflects selection
- V2 multi-agent routing is now reachable from the extension UI for the first time
- Backend /query V2 branch (Phase 24) receives intent_hint and routes to debug/review/test/explain agents accordingly
- No blockers for Phase 26 if planned

---
*Phase: 25-extension-intent-selector*
*Completed: 2026-03-22*
