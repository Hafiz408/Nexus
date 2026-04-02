# Phase 25: extension-intent-selector - Research

**Researched:** 2026-03-22
**Domain:** VS Code Webview (React 18, TypeScript), extension host message protocol
**Confidence:** HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| EXT-01 | Sidebar shows intent selector with 5 options: Auto, Explain, Debug, Review, Test (pill-style segmented control) | React `useState` for active intent; CSS pill/segmented-control pattern using VS Code CSS variables |
| EXT-02 | Selected intent is sent as `intent_hint` in query request body (`auto` → omit field) | `streamQuery` signature must be extended to accept `intentHint`; `SseStream.ts` body construction logic; `WebviewToHostMessage` union must include `intent_hint` field |
| EXT-03 | Send button label changes per selected intent: Ask / Explain / Debug / Review / Test | Derived string map from intent value; button label reads from map keyed on current state |
</phase_requirements>

---

## Summary

Phase 25 adds an intent selector UI to the existing React sidebar. The webview is built with React 18 and compiled via esbuild; the host side is TypeScript with the VS Code extension API. The codebase has a clean separation: App.tsx owns all UI state, SseStream.ts owns the HTTP request, and types.ts defines the message contract between webview and host.

The change touches three layers: (1) App.tsx gains a new `selectedIntent` state driving the pill UI and button label, (2) the `query` message payload gains an optional `intent_hint` field, and (3) SseStream.ts / SidebarProvider.ts pass that field through to the backend POST body. No new libraries are required — the pill control is pure CSS + React state.

The backend contract is already defined: `intent_hint` must be one of `"explain" | "debug" | "review" | "test"` to trigger the V2 path; `"auto"` and `null`/`undefined` both fall through to the V1 SSE path. The extension only omits the field when Auto is selected (not sends `"auto"`), which is equivalent to `null` on the backend.

**Primary recommendation:** Add `selectedIntent` state to App.tsx, render five pill buttons above the textarea, derive button label from a constant map, and thread `intent_hint` through the message → SidebarProvider → SseStream chain.

---

## Standard Stack

### Core (already in project)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| React | 18.x | Webview UI framework | Already bundled; pill state = `useState` |
| TypeScript | 5.x | Type safety for message contract | Already configured |
| esbuild | 0.20.x | Bundles webview + host | Already configured via `esbuild.js` |
| VS Code Webview API | N/A | Host↔webview message passing | Only available mechanism |

### No new dependencies needed

All requirements are satisfied by existing React + CSS + VS Code CSS variables. Do not add external component libraries — the current codebase uses bespoke CSS following VS Code design tokens.

---

## Architecture Patterns

### Existing Project Structure (relevant files)

```
extension/
├── src/
│   ├── SidebarProvider.ts        # Host: handles 'query' messages, calls streamQuery()
│   ├── SseStream.ts              # Host: HTTP POST to /query, streams SSE back
│   ├── types.ts                  # Shared: WebviewToHostMessage, HostToWebviewMessage
│   └── webview/
│       ├── App.tsx               # Webview: all UI state, renders intent pills + send btn
│       └── index.css             # Webview: all styles (VS Code CSS variable tokens)
```

### Pattern 1: React State for Exclusive Selection

**What:** A single `useState<IntentOption>` stores the active pill. Clicking a pill calls the setter. No external library needed.

**When to use:** Exactly one option active at a time, with immediate UI feedback.

```typescript
// In App.tsx
type IntentOption = 'auto' | 'explain' | 'debug' | 'review' | 'test';

const INTENT_LABELS: Record<IntentOption, string> = {
  auto:    'Ask',
  explain: 'Explain',
  debug:   'Debug',
  review:  'Review',
  test:    'Test',
};

const INTENT_OPTIONS: IntentOption[] = ['auto', 'explain', 'debug', 'review', 'test'];

const [selectedIntent, setSelectedIntent] = useState<IntentOption>('auto');
```

### Pattern 2: Pill/Segmented Control via CSS Variables

**What:** A row of buttons styled as pills. The active pill gets a filled VS Code button background. Inactive pills use a subtle border.

**When to use:** Compact horizontal selector fitting inside the sidebar's narrow (~200–300px) width.

```css
/* index.css additions */
.intent-selector {
  display: flex;
  flex-flow: row nowrap;
  gap: 3px;
  padding: 6px 12px 4px;
  flex-shrink: 0;
}

.intent-pill {
  flex: 1;
  padding: 3px 0;
  font-size: 10px;
  font-weight: 500;
  text-align: center;
  border-radius: 3px;
  border: 1px solid var(--vscode-button-secondaryBackground,
                        rgba(128,128,128,0.3)) !important;
  color: var(--vscode-foreground);
  background: transparent !important;
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.1s, color 0.1s;
}

.intent-pill.active {
  background: var(--vscode-button-background) !important;
  color: var(--vscode-button-foreground) !important;
  border-color: transparent !important;
}

.intent-pill:hover:not(.active) {
  background: var(--vscode-toolbar-hoverBackground,
               rgba(128,128,128,0.15)) !important;
}
```

**Important:** The project's global button reset in index.css uses `!important` to strip all native button chrome (`-webkit-appearance: none !important; background: transparent !important; border: none !important`). Pill styles must also use `!important` on `background` and `border` to override that reset, exactly as `send-btn` and `citation-chip` already do.

### Pattern 3: Extending the Message Contract

**What:** Add `intent_hint` to the `'query'` message shape in types.ts and App.tsx's local `IncomingMessage` / postMessage call.

**When to use:** Any time the webview needs to pass new data to the host on send.

```typescript
// types.ts — extend WebviewToHostMessage
export type WebviewToHostMessage =
  | { type: 'query'; question: string; intent_hint?: string }  // NEW: optional field
  | { type: 'openFile'; filePath: string; lineStart: number }
  | { type: 'indexWorkspace' }
  | { type: 'clearIndex' };
```

```typescript
// App.tsx — postMessage on send
vscode.postMessage({
  type: 'query',
  question,
  intent_hint: selectedIntent !== 'auto' ? selectedIntent : undefined,
});
```

### Pattern 4: Threading intent_hint Through the Host

**What:** SidebarProvider receives the `'query'` message and forwards `intent_hint` to `streamQuery()`. `streamQuery()` includes it in the JSON body only when defined.

```typescript
// SidebarProvider.ts — update case 'query' handler
case 'query':
  if (this._repoPath) {
    // ... existing config reads ...
    await streamQuery(
      msg.question,
      this._repoPath,
      webviewView.webview,
      backendUrl,
      (citations) => { void this._highlight.highlightCitations(citations); },
      msg.intent_hint,  // NEW: pass through
    );
  }
```

```typescript
// SseStream.ts — extend streamQuery signature and body construction
export async function streamQuery(
  question: string,
  repoPath: string,
  webview: vscode.Webview,
  backendUrl: string,
  onCitations?: (citations: Citation[]) => void,
  intentHint?: string,   // NEW
): Promise<void> {
  // ...
  body: JSON.stringify({
    question,
    repo_path: repoPath,
    max_nodes: maxNodes,
    hop_depth: hopDepth,
    ...(intentHint ? { intent_hint: intentHint } : {}),  // NEW: omit when undefined
  }),
```

### Anti-Patterns to Avoid

- **Sending `"auto"` as `intent_hint`**: The backend treats `"auto"` as the V1 sentinel and falls through to the V1 SSE path (same as `null`). The correct behavior for Auto is to omit the field entirely, not to send the string `"auto"`. The EXT-02 requirement says "auto → omit field."
- **Inline styles for pill state**: The existing codebase uses CSS class names (`dotClass`, `className` + conditional string). Follow the same pattern: toggle `"intent-pill active"` vs `"intent-pill"` via className string, not inline `style=` attributes.
- **Separate component file for pills**: The existing App.tsx defines all sub-components (`SectionHeader`) inline as arrow functions within the component. Follow this pattern; do not create a new file.
- **Using `!important`-free styles for pills**: The global button reset strips `background` and `border` with `!important`. Pill active/hover styles must use `!important` on those properties to win the cascade, consistent with `send-btn`, `citation-chip`, and `icon-btn` in the existing CSS.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead |
|---------|-------------|-------------|
| Exclusive selection state | Custom selection manager | React `useState<IntentOption>` |
| VS Code-themed pill colors | Custom color values | `var(--vscode-button-background)`, `var(--vscode-toolbar-hoverBackground)` |
| Message type narrowing | Custom discriminator | TypeScript discriminated union already on `WebviewToHostMessage` |

---

## Common Pitfalls

### Pitfall 1: Global Button Reset Overrides Pill Styles

**What goes wrong:** The `index.css` global reset applies `background: transparent !important; border: none !important` to ALL buttons. Pill active state (filled background, border) has no effect.

**Why it happens:** The reset uses `!important` which wins against normal specificity. This is intentional for VS Code native-feel buttons elsewhere in the UI.

**How to avoid:** Apply `!important` to `background` and `border` on `.intent-pill.active` and `.intent-pill` (border for inactive). This is the established pattern — `send-btn`, `citation-chip` all do this.

**Warning signs:** Pill looks flat/unstyled despite correct className; DevTools shows the reset winning.

### Pitfall 2: Sending "auto" Instead of Omitting intent_hint

**What goes wrong:** Backend receives `intent_hint: "auto"`, which is the V1 fall-through sentinel — query goes to V1 SSE path, not the router. This silently degrades behavior.

**Why it happens:** Treating `selectedIntent === 'auto'` as a passthrough string rather than an omit signal.

**How to avoid:** `selectedIntent !== 'auto' ? selectedIntent : undefined` — only include the field when it is a named intent.

**Warning signs:** Debug/Review/Test queries appear to work but the backend logs show the V1 path executing; no `intent: debug` in response.

### Pitfall 3: TypeScript Narrowing Breaks on Untyped `msg`

**What goes wrong:** `SidebarProvider.ts` receives `msg: WebviewToHostMessage`; accessing `msg.intent_hint` fails TypeScript if only the `'query'` variant carries it.

**Why it happens:** Discriminated unions only expose fields common to all variants, or fields on the specific narrowed type. Accessing before narrowing causes TS error.

**How to avoid:** The existing code already does `switch (msg.type)` which narrows. Access `msg.intent_hint` inside the `case 'query':` branch — TypeScript will have narrowed `msg` to the `query` variant by that point.

### Pitfall 4: Pill Layout Breaking in Narrow Sidebar

**What goes wrong:** Five pills in a row overflow the sidebar width (~200px), truncating "Explain" or "Review."

**Why it happens:** `flex: 1` divides space equally but 10-character labels at 10px font may still be tight on very small sidebars.

**How to avoid:** Use `font-size: 10px`, `padding: 3px 0`, minimal horizontal padding, and `flex: 1` so all pills share space equally. Labels are short (3–7 characters). "Explain" at 10px is ~42px; five pills with 3px gaps fits in 200px. Avoid `min-width` constraints.

### Pitfall 5: Button Label Not Updating During Streaming

**What goes wrong:** User selects Debug, sends a query, then while streaming the button shows "…" (existing streaming state) which is correct — but after streaming ends, the label returns to whatever the intent is. This is already handled: the send button renders `isStreaming ? '…' : INTENT_LABELS[selectedIntent]`.

**Why it happens:** N/A — just ensure the label expression reads from both `isStreaming` and `selectedIntent` simultaneously.

**How to avoid:** `{isStreaming ? '…' : INTENT_LABELS[selectedIntent]}` — one expression, always current.

---

## Code Examples

### Pill Selector Render (App.tsx)

```typescript
{/* Intent selector — placed above the textarea, inside .input-area or as sibling */}
<div className="intent-selector">
  {INTENT_OPTIONS.map((intent) => (
    <button
      key={intent}
      className={`intent-pill${selectedIntent === intent ? ' active' : ''}`}
      onClick={() => setSelectedIntent(intent)}
      disabled={isStreaming}
      title={INTENT_LABELS[intent]}
    >
      {intent === 'auto' ? 'Auto' : INTENT_LABELS[intent]}
    </button>
  ))}
</div>
```

### Send Button Label (App.tsx)

```typescript
// Replace existing: {isStreaming ? '…' : 'Ask'}
{isStreaming ? '…' : INTENT_LABELS[selectedIntent]}
```

### Backend Body Construction (SseStream.ts)

```typescript
body: JSON.stringify({
  question,
  repo_path: repoPath,
  max_nodes: maxNodes,
  hop_depth: hopDepth,
  ...(intentHint ? { intent_hint: intentHint } : {}),
}),
```

---

## Implementation Checklist (files to touch)

| File | Change |
|------|--------|
| `extension/src/webview/App.tsx` | Add `IntentOption` type + `INTENT_LABELS` + `INTENT_OPTIONS` constants; add `selectedIntent` state; render `.intent-selector` div with pills; update `postMessage` call to include `intent_hint`; update send button label |
| `extension/src/webview/index.css` | Add `.intent-selector`, `.intent-pill`, `.intent-pill.active`, `.intent-pill:hover:not(.active)` CSS blocks |
| `extension/src/types.ts` | Add `intent_hint?: string` to the `{ type: 'query'; ... }` variant of `WebviewToHostMessage` |
| `extension/src/SidebarProvider.ts` | Pass `msg.intent_hint` as last argument to `streamQuery()` in `case 'query':` handler |
| `extension/src/SseStream.ts` | Add `intentHint?: string` parameter to `streamQuery()`; conditionally include `intent_hint` in POST body |

---

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| V1: single `'query'` message with no intent | V2: `'query'` message with optional `intent_hint` | Backend routes to specialist agent when hint present |
| V1: button always reads "Ask" | V2: button label reflects selected intent | User gets clear feedback on which mode is active |

---

## Open Questions

1. **Pill placement: above textarea or above the send button row?**
   - What we know: The `.input-area` contains textarea + send button as a flex row. Adding pills inside `.input-area` would require making it `flex-direction: column`. Alternatively, a `.intent-selector` div sits as a sibling above `.input-area` inside `.chat-body`.
   - What's unclear: Designer preference. Both work technically.
   - Recommendation: Sibling `div.intent-selector` above `.input-area` — cleaner DOM structure, no surgery to existing `.input-area` flex layout.

2. **Should intent reset to Auto after each send?**
   - What we know: Requirements do not specify reset behavior.
   - What's unclear: UX preference — sticky intent (user stays in Debug mode) vs. per-query intent.
   - Recommendation: Sticky. User explicitly chose an intent; resetting it silently breaks their workflow. They can click Auto to reset.

---

## Sources

### Primary (HIGH confidence)

- `extension/src/webview/App.tsx` — Full React component; state patterns, message protocol, CSS class conventions verified by direct read
- `extension/src/webview/index.css` — Full stylesheet; global button reset, `!important` usage, VS Code CSS variable tokens verified by direct read
- `extension/src/types.ts` — `WebviewToHostMessage` union definition verified by direct read
- `extension/src/SidebarProvider.ts` — Host message handler, `streamQuery` call site verified by direct read
- `extension/src/SseStream.ts` — HTTP POST body construction, parameter signature verified by direct read
- `backend/app/models/schemas.py` — `intent_hint: Optional[str] = None` confirmed by grep
- `backend/app/api/query_router.py` — V2 gate: `intent_hint not None and != "auto"` confirmed by grep
- `.planning/REQUIREMENTS.md` — EXT-01, EXT-02, EXT-03 definitions read directly

### Secondary (MEDIUM confidence)

- `backend/app/agent/router.py` — `_VALID_HINTS` = `{"explain", "debug", "review", "test"}` confirmed by grep; "auto" is NOT a valid hint, it falls through

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all files read directly, no speculation
- Architecture patterns: HIGH — derived from direct code analysis of existing patterns
- Pitfalls: HIGH — `!important` cascade and `"auto"` omit rule verified from source code
- Message contract: HIGH — `types.ts` and backend schema both read directly

**Research date:** 2026-03-22
**Valid until:** 2026-04-22 (stable domain — VS Code webview API + React patterns change slowly)
