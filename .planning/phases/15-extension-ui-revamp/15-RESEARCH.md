# Phase 15: Extension UI Revamp — Research

**Researched:** 2026-03-21
**Domain:** VS Code Webview UI polish — React 18, CSS variables, sidebar layout
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **Polish & coherence focus**: All four sidebar sections need attention (Index, Chat, Citations, Activity)
- **Textarea auto-grow**: Expand from 1 row up to ~5 rows as user types, then scroll
- **Citation overflow**: Show first 5 chips; "+N more" chip expands inline on click
- **Index progress bar**: Show `files_processed` count AND a thin progress bar during indexing (determinate if total known, else animated/indeterminate bar)
- **Theme compatibility**: Target both dark and light VS Code themes; use VS Code CSS variables only — no hardcoded colors except where VS Code provides none (e.g., green status dot)

### Claude's Discretion

No explicit discretion areas listed in CONTEXT.md. All visual decisions not explicitly locked (exact heights, gap values, animation timing) are at implementation discretion, provided they feel native to VS Code.

### Deferred Ideas (OUT OF SCOPE)

Not explicitly listed. Based on CONTEXT.md scope, out of scope: animations beyond spinner/progress-bar, dark-mode-only features, new message types, backend changes, configuration changes.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| EXT-04 | On activation with open workspace, automatically triggers `IndexerService.indexWorkspace()` | Already implemented; progress bar display improvement is the delta |
| CHAT-01 | React 18 Webview shows chat messages with `user` and `assistant` roles | Already working; polish is styling/layout only |
| CHAT-02 | Streaming: tokens append to last assistant message in real-time | Already working; no logic changes needed |
| CHAT-03 | Citations rendered as clickable chips; click opens file at correct line | Already working; overflow collapse pattern is the delta |
| CHAT-04 | Index status bar shows spinner/ready/not-indexed + Index Workspace button | Already working; progress bar + count display is the delta |
| CHAT-05 | Styling uses VS Code CSS variables (`--vscode-*`); no external CSS frameworks | Locking and extending current approach; research confirms safe variable set |
</phase_requirements>

---

## Summary

The codebase already has a solid structural skeleton: section headers with chevrons, inline icon buttons, spinner, status dot, citation chips, log rows, and markdown rendering. The CSS resets are correctly applied (`-webkit-appearance: none`, `border: 0 solid transparent`). The work in Phase 15 is entirely **within `App.tsx` and `index.css`** — no extension host changes, no backend changes.

Three concrete gaps exist vs. the target design. First, the textarea currently has a fixed `rows={1}` and a `max-height: 100px` CSS clamp but no JavaScript to actually grow it — it will just scroll internally above one line. Second, the citations render all chips unconditionally — there is no collapse/expand logic. Third, the Activity section's live progress row shows a spinner and text but no thin progress bar element.

All changes are pure React state + CSS. No new npm packages are required: the auto-grow textarea uses `scrollHeight` measurement via a `useRef`, the "+N more" pattern uses `useState`, and the progress bar is a pure CSS `div` with `@keyframes` animation and `--vscode-progressBar-background`.

**Primary recommendation:** Implement all three features directly in `App.tsx` and `index.css` using only VS Code CSS variables and standard React patterns — no library additions, no DOM framework changes.

---

## Standard Stack

### Core (already in use — no additions needed)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| React | 18.x | UI rendering | Already installed, webview bootstrap intact |
| TypeScript | 5.x | Type safety | Already configured in tsconfig |
| esbuild | current | Bundle webview to `out/webview/index.js` | Already wired in esbuild.js |

### No New Dependencies

This phase introduces zero new npm packages. All features are achievable with:
- Native DOM `scrollHeight` measurement for textarea auto-grow
- React `useState` for citation collapse toggle
- CSS `@keyframes` + `width` percentage for progress bar

**Installation:** None required.

---

## Architecture Patterns

### Recommended File Structure (unchanged)

```
extension/src/webview/
├── App.tsx          — all UI logic changes go here
├── index.css        — all CSS changes go here
└── index.tsx        — entry point, untouched
```

All work in this phase is isolated to `App.tsx` and `index.css`.

---

### Pattern 1: Textarea Auto-Grow via scrollHeight

**What:** On every `onChange`, set `style.height = 'auto'` to reset, then set `style.height = element.scrollHeight + 'px'`. Cap at a max via CSS `max-height`. The textarea uses `resize: none` (already set).

**Why scrollHeight:** `scrollHeight` equals the full content height including invisible overflow. Resetting to `auto` first forces reflow to correct intrinsic height; without this, the element retains its old height during measurement and the value only ever grows.

**Critical WebKit/VS Code note:** This approach uses only standard DOM APIs and is safe in the VS Code Electron WebKit renderer. ResizeObserver is NOT needed and should NOT be used for this — it fires asynchronously and can cause a feedback loop (height change triggers ResizeObserver, which triggers height change). Direct `scrollHeight` read on `onChange` is synchronous and reliable.

**Row cap calculation:** At `font-size: 13px` and `line-height: 1.4`, one row ≈ 20px. Five rows ≈ 100px (already matching the existing `max-height: 100px` in CSS). The `min-height: 32px` (existing) handles the 1-row minimum with padding.

**React pattern:**

```typescript
// In App.tsx — replace the static textarea with:
const textareaRef = useRef<HTMLTextAreaElement>(null);

const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>): void => {
  setInputValue(e.target.value);
  const el = e.target;
  el.style.height = 'auto';           // reset first
  el.style.height = `${el.scrollHeight}px`;  // grow to content
};

// In JSX — add ref, remove rows={1}, use handleInputChange:
<textarea
  ref={textareaRef}
  value={inputValue}
  onChange={handleInputChange}
  onKeyDown={handleKeyDown}
  placeholder="Ask about your codebase…"
  disabled={isStreaming}
/>
```

**CSS adjustment needed:** Remove `min-height: 32px` from `.input-area textarea` (it fights auto-grow on reset). Use `rows` attribute instead of min-height for the initial size OR set `min-height` to exactly one computed row height. `max-height: 100px` and `overflow-y: auto` must stay.

**Anti-pattern:** Do NOT use `useEffect` with a `ResizeObserver` to drive height — causes async feedback loop. Do NOT use `useEffect([inputValue])` either — the DOM mutation must happen synchronously in the event handler before React re-renders.

---

### Pattern 2: Citation Collapse (+N More)

**What:** Show first 5 chips always. If `citations.length > 5`, render a "+N more" chip as the 6th element. Clicking it sets a per-message expanded flag to true, revealing all chips inline.

**State location:** The expanded state is per-message, not global. Use a `Set<string>` of expanded message IDs stored in a `useState` at the App level. This avoids adding state to the `ChatMessage` interface (which is also posted via the message bus).

**React pattern:**

```typescript
// In App.tsx — add at component level:
const [expandedCitations, setExpandedCitations] = useState<Set<string>>(new Set());

// In citation render block:
const isExpanded = expandedCitations.has(msg.id);
const visibleCitations = isExpanded ? msg.citations : msg.citations.slice(0, 5);
const hiddenCount = msg.citations.length - 5;

// Render visibleCitations.map(...) then:
{!isExpanded && hiddenCount > 0 && (
  <button
    className="citation-chip citation-chip-more"
    onClick={() => setExpandedCitations(prev => {
      const next = new Set(prev);
      next.add(msg.id);
      return next;
    })}
  >
    +{hiddenCount} more
  </button>
)}
```

**CSS:** `.citation-chip-more` gets a distinct visual treatment — slightly lower opacity, dotted or no background, acts as affordance that it's interactive rather than a file reference.

---

### Pattern 3: Thin Progress Bar (Determinate + Indeterminate)

**What:** A 2-3px tall bar below the spinner/text row in the Activity section's live progress row. Uses `--vscode-progressBar-background` (confirmed available in VS Code webview CSS variables). Determinate when `files_processed` total is knowable; indeterminate (animated shimmer/sweep) otherwise.

**VS Code CSS variable:** `--vscode-progressBar-background` is a first-class theme variable confirmed in VS Code's Theme Color reference. It maps to the same blue/accent used in VS Code's native loading bars. This variable is safe in both dark and light themes.

**Current state of indexStatus:** The `IndexStatus` type has `files_processed?: number` but NO total file count. The backend returns count of files processed so far, not a total. Therefore the bar must be indeterminate (animated sweep) — width cannot be calculated as a percentage.

**If total becomes available** (future): the bar becomes `width: (files_processed / total * 100)%` and the animation stops. For now: indeterminate only.

**CSS implementation:**

```css
/* In index.css */
.progress-bar-track {
  width: 100%;
  height: 2px;
  background: var(--vscode-sideBar-background, transparent);
  overflow: hidden;
  margin-top: 4px;
  flex-shrink: 0;
}

.progress-bar-fill {
  height: 100%;
  width: 40%;
  background: var(--vscode-progressBar-background, #0078d4);
  border-radius: 1px;
  animation: progress-sweep 1.4s ease-in-out infinite;
}

@keyframes progress-sweep {
  0%   { transform: translateX(-100%); }
  50%  { transform: translateX(150%); }
  100% { transform: translateX(150%); }
}
```

**Placement in JSX:** Add `.progress-bar-track > .progress-bar-fill` inside the `.log-progress` div, below the spinner+text span. The `log-progress` div already has `flex-direction: row` — change to `flex-direction: column` or wrap the text row in a nested flex container.

---

### Pattern 4: Index Section Progress Count

**Current:** During indexing, `nodeLabel` shows "Indexing — N nodes" (using `nodes_indexed`).

**Target:** Show "Indexing — 42 files…" using `files_processed` when available, with the thin progress bar below it in the Index body (not Activity).

**Decision:** The progress bar should appear in the Index section body (where the status dot lives), not only in Activity. This gives the user an at-a-glance view without needing to open Activity.

**Implementation:** In the Index body `{indexExpanded && ...}` block, add the progress bar track + fill `div` when `isIndexing` is true.

---

### Anti-Patterns to Avoid

- **ResizeObserver for textarea height:** Fires asynchronously, causes height feedback loops in WebKit. Use synchronous `scrollHeight` on `onChange` instead.
- **Hardcoded colors for progress bar:** Use `--vscode-progressBar-background`, not `#0078d4` directly (which would break light themes with a different accent).
- **Adding state to ChatMessage for citation expand:** The message interface is also used in the postMessage bus between extension host and webview. Mutating it adds type complexity. Use a separate `Set<string>` at component level.
- **useEffect for textarea resize:** Deferred execution means the textarea flashes at the wrong size on first render. The `onChange` handler approach is immediate.
- **`rows` attribute without removing CSS min-height:** If both are set, the CSS `min-height` overrides the `rows` attribute in WebKit. Remove `min-height` or set it to match 1 row exactly.
- **Indeterminate via `<progress>` HTML element:** Styling `<progress>` with WebKit pseudo-elements (`-webkit-progress-bar`) is fragile and inconsistent. Pure CSS `div` + `@keyframes` is more reliable.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Markdown rendering | New renderer | Existing `renderMarkdown()` in App.tsx | Already handles bold, italic, code, headings, lists — complete for this use case |
| Theme detection | JS theme polling | VS Code body classes + CSS `--vscode-*` variables | Variables update automatically on theme switch; no JS needed |
| Spinner | Custom animation | Existing `.spinner` CSS class | Already implemented with correct 9px size and timing |
| Icon font | Codicon imports | Unicode characters already in use (↺, ▾, ▸, ⊘) | Adding Codicons requires font asset registration in package.json; current approach works |

**Key insight:** This phase is about CSS and state wiring — no structural rewrites, no new abstractions, no library additions. The existing architecture handles all patterns.

---

## Common Pitfalls

### Pitfall 1: Textarea scrollHeight Measured Before DOM Update

**What goes wrong:** Reading `scrollHeight` before the value is flushed to DOM gives stale height.
**Why it happens:** React batches state updates; if height read happens after `setInputValue` in the same tick, React may not have updated the DOM yet.
**How to avoid:** Read `scrollHeight` from `e.target` (the event's native element) directly in the `onChange` handler — NOT from a ref after `setInputValue`. The native element is already at the correct value before React's state reconciliation.
**Warning signs:** Textarea height lags one keystroke behind.

### Pitfall 2: CSS `box-sizing` Fight with Auto-Grow

**What goes wrong:** Textarea grows on every keystroke without stabilizing.
**Why it happens:** If `box-sizing` is not `border-box`, setting `style.height = scrollHeight` includes padding in content height, causing an additive loop.
**How to avoid:** The existing global `*, *::before, *::after { box-sizing: border-box; }` in `index.css` already covers this. Verify `.input-area textarea` doesn't override it.
**Warning signs:** Textarea height increments by 2px on each keystroke.

### Pitfall 3: Progress Bar Width Transition Jank

**What goes wrong:** Animated `translateX` causes sub-pixel rendering artifacts at 2px height in WebKit.
**Why it happens:** 2px elements with `overflow: hidden` on the parent plus GPU compositing can produce rendering gaps.
**How to avoid:** Add `will-change: transform` to `.progress-bar-fill`. Use `height: 3px` if 2px shows gaps. Ensure `.progress-bar-track` has `border-radius: 1px` to contain the fill.
**Warning signs:** Progress bar appears dotted or has hairline gaps at edges.

### Pitfall 4: Citation Expand State Persists After Clear

**What goes wrong:** User clears chat (sets `messages` to `[]`), then sends new messages, but old expanded citation IDs remain in the `expandedCitations` Set.
**Why it happens:** `expandedCitations` is independent state from `messages`.
**How to avoid:** Reset `expandedCitations` to `new Set()` in the clear chat handler alongside `setMessages([])`.
**Warning signs:** First N messages after a clear have their citations pre-expanded if they happen to reuse the same counter-based IDs.

### Pitfall 5: VS Code CSS Variables Missing in Light Themes

**What goes wrong:** Sidebar background appears white/transparent in Light+ because `--vscode-sideBar-background` is unset (Light+ uses default white, variable may be undefined).
**Why it happens:** Some VS Code CSS variables are only defined when the theme explicitly sets them. Light themes often rely on the VS Code default and don't emit the variable.
**How to avoid:** Always provide a fallback: `var(--vscode-sideBar-background, transparent)`. The body background already handles the base color; the fallback can be `transparent` for overlay elements.
**Warning signs:** A section has a mismatched background in Light+ mode.

### Pitfall 6: `--vscode-progressBar-background` Contrast on Light Themes

**What goes wrong:** Progress bar is invisible in Light+ because the background is white and the bar is a light blue that doesn't contrast.
**Why it happens:** Light themes use a lighter accent color for `progressBar`.
**How to avoid:** No special handling needed — `--vscode-progressBar-background` is defined in both Light+ and Dark+ by VS Code. Use it directly. The `.progress-bar-track` background should be `rgba(128,128,128,0.1)` as a neutral track color visible in both themes.

---

## Code Examples

### Auto-Grow Textarea (synchronous onChange approach)

```typescript
// Source: Standard React DOM pattern, verified against VS Code WebKit renderer behavior

// Add to App component imports: useRef already imported
// Add ref alongside messagesEndRef:
const textareaRef = useRef<HTMLTextAreaElement>(null);

// Replace handleSend's inputValue access (unchanged)
// Replace only the onChange handler:
const handleInputChange = useCallback(
  (e: React.ChangeEvent<HTMLTextAreaElement>): void => {
    setInputValue(e.target.value);
    // Synchronous height update — do NOT defer to useEffect
    const el = e.target;
    el.style.height = 'auto';
    el.style.height = `${el.scrollHeight}px`;
  },
  []
);

// Also reset height when textarea is cleared after send:
// In handleSend, after setInputValue(''):
if (textareaRef.current) {
  textareaRef.current.style.height = 'auto';
}
```

### Progress Bar (indeterminate CSS)

```css
/* Source: Standard CSS animation pattern using verified VS Code CSS variable */

.progress-bar-track {
  width: 100%;
  height: 2px;
  background: rgba(128, 128, 128, 0.15);
  overflow: hidden;
  border-radius: 1px;
  flex-shrink: 0;
}

.progress-bar-fill {
  height: 100%;
  width: 35%;
  background: var(--vscode-progressBar-background, #0078d4);
  border-radius: 1px;
  animation: progress-sweep 1.5s ease-in-out infinite;
  will-change: transform;
}

@keyframes progress-sweep {
  0%   { transform: translateX(-250%); }
  100% { transform: translateX(400%); }
}
```

### Citation Collapse State

```typescript
// Source: Standard React pattern — per-message expanded tracking

// Add at component level (alongside other useState calls):
const [expandedCitations, setExpandedCitations] = useState<Set<string>>(new Set());

// In clear handler:
const handleClear = useCallback(() => {
  setMessages([]);
  setExpandedCitations(new Set());
}, []);

// In citation render block (replace the unconditional .map):
const CITATION_PREVIEW = 5;
const isExpanded = expandedCitations.has(msg.id);
const shownCitations = isExpanded ? msg.citations : msg.citations.slice(0, CITATION_PREVIEW);
const hiddenCount = msg.citations.length - CITATION_PREVIEW;

return (
  <div className="citations-chips">
    {shownCitations.map((c) => (
      <button key={c.node_id} className="citation-chip" onClick={() => handleCitationClick(c)} title={...}>
        {label}
      </button>
    ))}
    {!isExpanded && hiddenCount > 0 && (
      <button
        className="citation-chip citation-chip-more"
        onClick={() => setExpandedCitations(prev => new Set([...prev, msg.id]))}
        title={`Show ${hiddenCount} more citations`}
      >
        +{hiddenCount} more
      </button>
    )}
  </div>
);
```

### VS Code Body Theme Classes for CSS Overrides

```css
/* Use these only for exceptions where a variable has different behavior by theme */
/* Source: VS Code official webview docs — body element receives theme class */

body.vscode-light .status-dot.complete { background: #2e7d32; }  /* darker green for light bg */
body.vscode-dark  .status-dot.complete { background: #4caf50; }  /* existing green */
```

---

## Current Code Analysis: Gaps vs. Target

### Gap 1: Textarea Does Not Auto-Grow

- **Current `App.tsx` line 414:** `<textarea ... rows={1} />`
- **Current `index.css` line 413:** `min-height: 32px; max-height: 100px;`
- **Gap:** No `onChange` height mutation; `rows={1}` is just the HTML hint; WebKit respects it but CSS `min-height` takes precedence. Text beyond 1 row scrolls inside the textarea rather than growing it.
- **Fix:** Add `onChange={handleInputChange}` with synchronous `scrollHeight` mutation; reset height in `handleSend`.

### Gap 2: Citations Not Collapsed

- **Current `App.tsx` lines 386-403:** `msg.citations.map(...)` renders all chips unconditionally.
- **Gap:** 20-chip answers flood the chat area.
- **Fix:** Add `expandedCitations` Set state; slice at 5; render "+N more" chip.

### Gap 3: No Progress Bar in Index or Activity

- **Current `App.tsx` lines 456-464:** Live progress row has `<span className="spinner">` and text only.
- **Current `index.css` lines 506-517:** `.log-progress` styled but no bar child.
- **Gap:** No visual progress indication beyond spinner.
- **Fix:** Add `.progress-bar-track/.progress-bar-fill` elements to both the Index body (when `isIndexing`) and the Activity log-progress row.

### Gap 4: Status Dot Green Color Hardcoded Correctly

- **Current `index.css` line 209:** `.status-dot.complete { background: #4caf50; }`
- **Status:** This is acceptable per CONTEXT.md ("no hardcoded colors EXCEPT where VS Code provides none, e.g., green status dot"). Keep as is but add light-theme override if contrast is insufficient.

### Gap 5: files_processed vs nodes_indexed in Indexing Label

- **Current `App.tsx` line 277-281:** Shows `nodes_indexed` count during indexing.
- **Target (CONTEXT.md):** Show `files_processed` count during indexing ("Indexing — 42 files…").
- **Fix:** Switch `nodeLabel` during `isIndexing` state to use `files_processed` instead of `nodes_indexed`. Both are optional on `IndexStatus`; handle both undefined gracefully.

---

## VS Code CSS Variable Reference

Safe variables confirmed in both Dark+ and Light+ themes (HIGH confidence, from official Theme Color docs):

| Variable | Purpose | Light+ Safe | Dark+ Safe |
|----------|---------|-------------|------------|
| `--vscode-progressBar-background` | Progress bar fill color | YES | YES |
| `--vscode-sideBar-background` | Panel background | YES (may be undefined, use fallback) | YES |
| `--vscode-sideBarSectionHeader-background` | Section header bg | YES | YES |
| `--vscode-sideBarSectionHeader-foreground` | Section header text | YES | YES |
| `--vscode-sideBarSectionHeader-border` | Section header border | YES | YES |
| `--vscode-foreground` | Primary text color | YES | YES |
| `--vscode-descriptionForeground` | Secondary/muted text | YES | YES |
| `--vscode-errorForeground` | Error text/icons | YES | YES |
| `--vscode-focusBorder` | Focus ring color | YES | YES |
| `--vscode-icon-foreground` | Icon color | YES | YES |
| `--vscode-button-background` | Primary button bg | YES | YES |
| `--vscode-button-foreground` | Primary button text | YES | YES |
| `--vscode-button-hoverBackground` | Primary button hover | YES | YES |
| `--vscode-badge-background` | Badge/chip bg | YES | YES |
| `--vscode-badge-foreground` | Badge/chip text | YES | YES |
| `--vscode-input-background` | Input field bg | YES | YES |
| `--vscode-input-foreground` | Input field text | YES | YES |
| `--vscode-input-border` | Input field border | YES (may be transparent) | YES |
| `--vscode-input-placeholderForeground` | Placeholder text | YES | YES |
| `--vscode-list-hoverBackground` | Row hover bg | YES | YES |
| `--vscode-toolbar-hoverBackground` | Toolbar icon hover | YES | YES |
| `--vscode-panel-border` | Divider lines | YES | YES |
| `--vscode-textCodeBlock-background` | Code block bg | YES | YES |
| `--vscode-editor-font-family` | Monospace font | YES | YES |

**Variables with no VS Code equivalent (hardcode with fallback):**
- Green status dot: `#4caf50` — no `--vscode-testing-iconPassed` equivalent guaranteed in webview
- Warning orange: `#ff9800` — no standard variable; keep hardcoded with comment

---

## State of the Art

| Old Approach | Current Approach | Notes |
|--------------|------------------|-------|
| vscode-webview-ui-toolkit components | Custom CSS with `--vscode-*` variables | Toolkit archived Jan 2025; custom CSS is now the recommended path |
| EventSource for SSE | `fetch` + `ReadableStream` | Already implemented (POST requires fetch; this is the current correct approach) |
| `<progress>` HTML element for bars | Pure CSS `div` + `@keyframes` | WebKit pseudo-element styling for `<progress>` is fragile; CSS divs are reliable |

---

## Open Questions

1. **Total file count for determinate bar**
   - What we know: `IndexStatus` has `files_processed` but no `total_files` field. Backend pipeline doesn't expose total.
   - What's unclear: Would the backend need a new field to enable a determinate bar?
   - Recommendation: Implement indeterminate bar for now. The bar is visually complete and the design spec says "at minimum" indeterminate is acceptable. Determinate can be a future enhancement.

2. **Progress bar in Index section vs Activity section only**
   - What we know: CONTEXT.md says "show thin progress bar" during indexing. Activity section already has the live progress row.
   - Recommendation: Show bar in Index section body (visible without opening Activity) AND in the Activity live progress row. Both locations give different user value.

3. **Light theme green dot contrast**
   - What we know: `#4caf50` is medium green; light themes have a white/near-white background.
   - Recommendation: Test in Light+. If contrast is insufficient (< 3:1), add `.vscode-light .status-dot.complete { background: #2e7d32; }`.

---

## Sources

### Primary (HIGH confidence)
- VS Code Theme Color Reference — `https://code.visualstudio.com/api/references/theme-color` — CSS variable names for progressBar, sideBar, badge, button, input, panel
- VS Code Webview API docs — `https://code.visualstudio.com/api/extension-guides/webview` — Body theme classes (`vscode-light`, `vscode-dark`), CSS variable injection mechanism
- VS Code UX Guidelines — `https://code.visualstudio.com/api/ux-guidelines/sidebars` — Sidebar structural guidance
- Project source files: `App.tsx`, `index.css`, `SidebarProvider.ts`, `types.ts` — Direct gap analysis

### Secondary (MEDIUM confidence)
- Standard React textarea auto-grow pattern (multiple Medium/dev.to sources) — `scrollHeight` approach verified against WebKit behavior; no VS Code-specific source but DOM behavior is standard
- Elio Struyf — "A code-driven approach to theme your VS Code webview" — confirmed CSS variable injection and `MutationObserver` pattern for theme switching

### Tertiary (LOW confidence — not relied upon)
- vscode-webview-ui-toolkit README for text-area — archived Jan 2025; used only to confirm no built-in auto-grow exists
- GitHub issue microsoft/vscode-docs#2060 — confirmed `--vscode-progressBar-background` is available but no complete list was in the issue

---

## Metadata

**Confidence breakdown:**
- Gap analysis (current vs. target): HIGH — from direct source code reading
- VS Code CSS variables: HIGH — from official Theme Color Reference
- Auto-grow textarea pattern: HIGH — standard DOM behavior, multiple verified sources
- Progress bar CSS: HIGH — confirmed `--vscode-progressBar-background` exists; indeterminate animation is standard CSS
- Citation collapse: HIGH — pure React state, no external dependencies
- WebKit pitfalls: MEDIUM — Electron WebKit issues sourced from issue trackers, not official docs

**Research date:** 2026-03-21
**Valid until:** 2026-06-21 (VS Code CSS variables are stable; React 18 patterns stable)
