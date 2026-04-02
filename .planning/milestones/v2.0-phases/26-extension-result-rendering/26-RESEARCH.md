# Phase 26: extension-result-rendering - Research

**Researched:** 2026-03-22
**Domain:** VS Code webview React UI — structured result rendering for debug/review/test intents
**Confidence:** HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| EXT-04 | Debug response renders suspects panel: ranked list with file:line, anomaly score bar, and traversal breadcrumb chain | DebugResult shape confirmed; SuspectNode has file_path, line_start, anomaly_score; traversal_path is list of node_ids |
| EXT-05 | Debug response renders impact radius as collapsible list; suspect references clickable (opens file at line via HighlightService pattern) | impact_radius is list[str] node_ids; openFile message already wired in SidebarProvider; same postMessage pattern as citations |
| EXT-06 | Review response renders findings list with severity badges (critical=red, warning=amber, info=blue), category label, description, expandable suggestion | Finding has severity literal ("critical"/"warning"/"info"), category, description, file_path, line_start, line_end, suggestion |
| EXT-07 | Review response shows "Post to GitHub PR" button when github_token is configured | github_token is backend env var; extension must query backend for config presence; requires new backend /config endpoint OR backend includes has_github_token in the result payload |
| EXT-08 | Test response renders generated code block with syntax highlighting | TestResult has test_code (string), test_file_path, framework; syntax highlighting must be pure CSS in WebKit/Electron — no external libs |
| EXT-09 | Test response shows "File written to: {path}" badge in green when Filesystem MCP succeeded, or "Copy to clipboard" button otherwise | write_test_file returns {"success": bool, "path": str|None, "error": str|None}; need to determine if orchestrator calls write_test_file and surfaces result in SSE payload |
</phase_requirements>

---

## Summary

Phase 26 adds structured rendering panels for the three V2 specialist agents (debug, review, test). The backend already emits a single SSE `result` event carrying `{type: "result", intent: str, result: dict}` — the serialized Pydantic model via `model_dump(mode="json")`. The webview currently only handles `token`, `citations`, `done`, and `error` events; it must gain a `result` handler and three intent-specific panel components.

All rendering happens inside the existing React App in `extension/src/webview/App.tsx`. The CSS patterns are already established (VS Code CSS variables, `!important` on buttons, `panel-section` layout). New components must follow these conventions exactly — they run in a WebKit/Electron renderer without access to npm packages beyond React 18.

The most architecturally significant gap is EXT-07 (github_token button). The `github_token` is a backend environment variable; the extension has no direct access. The cleanest solution is to include a `has_github_token: bool` field in the SSE result payload when intent is `review`. This requires a one-line addition to `query_router.py`'s `v2_event_generator` — well within this phase's scope.

**Primary recommendation:** Add `result` SSE event handling to `SseStream.ts` + `App.tsx`; implement `DebugPanel`, `ReviewPanel`, `TestPanel` as pure React components; thread `has_github_token` through the result payload for EXT-07.

---

## Standard Stack

### Core (already installed — no new dependencies)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| React | 18.x | Component rendering | Already in extension/package.json |
| TypeScript | 5.x | Type safety | Already in extension/package.json |
| esbuild | 0.20.x | Bundle webview | Already in esbuild.js |

### No New Dependencies
All rendering is pure React + CSS. The webview runs in VS Code's WebKit sandbox — adding external npm packages requires bundling them and increases extension size. The existing CSS patterns (VS Code CSS variables, `@keyframes`, flexbox) are sufficient for all required UI elements including the score bar (a `<div>` with `width: ${score * 100}%`).

**Installation:** No new packages required.

---

## Architecture Patterns

### Existing SSE Event Flow (must extend, not replace)

```
Backend v2_event_generator
  → event: result  data: {type:"result", intent:"debug"|"review"|"test", result:{...}}
  → event: done    data: {type:"done"}

SseStream.ts (extension host)
  → currently handles: token, citations, done, error
  → MUST ADD: "result" case → postMessage({type:"result", intent, result})

SidebarProvider.ts (extension host)
  → passes webview.postMessage through from SseStream
  → no change needed

App.tsx (webview React)
  → currently handles: token, citations, done, error, indexStatus, log
  → MUST ADD: "result" case in window message handler
  → stores {intent, result} in message state
  → renders panel based on intent
```

### Data Shapes (confirmed from source)

**DebugResult** (from `backend/app/agent/debugger.py`):
```typescript
interface SuspectNode {
  node_id: string;
  file_path: string;
  line_start: number;
  anomaly_score: number;   // 0.0–1.0
  reasoning: string;
}

interface DebugResult {
  suspects: SuspectNode[];      // ranked desc, max 5
  traversal_path: string[];     // node_ids in BFS order
  impact_radius: string[];      // node_ids that call top suspect
  diagnosis: string;            // LLM narrative
}
```

**ReviewResult** (from `backend/app/agent/reviewer.py`):
```typescript
interface Finding {
  severity: 'critical' | 'warning' | 'info';
  category: string;
  description: string;
  file_path: string;
  line_start: number;
  line_end: number;
  suggestion: string;
}

interface ReviewResult {
  findings: Finding[];
  retrieved_nodes: string[];   // node_ids in context
  summary: string;
}
```

**TestResult** (from `backend/app/agent/tester.py`):
```typescript
interface TestResult {
  test_code: string;
  test_file_path: string;    // e.g. "tests/test_foo.py"
  framework: string;         // "pytest" | "jest" | "vitest" | "junit" | "unknown"
}
```

**SSE result payload shape** (from `backend/app/api/query_router.py` line 101):
```typescript
// Received from SseStream as postMessage to webview
interface ResultMessage {
  type: 'result';
  intent: 'debug' | 'review' | 'test' | 'explain';
  result: DebugResult | ReviewResult | TestResult | ExplainResult;
  // EXT-07: need to add has_github_token: boolean for review intent
}
```

### Recommended Project Structure (additions only)

```
extension/src/webview/
├── App.tsx                  # extend: add result handler + panel dispatch
├── index.css                # extend: add panel component styles
├── types.ts                 # extend: add HostToWebviewMessage result variant
└── (no new files needed — all panels inline in App.tsx for webview bundle simplicity)
```

Keep all panel components as functions within `App.tsx` — the webview is a single-bundle build via esbuild and splitting into separate files adds no structural benefit given the WebKit sandbox constraint.

### Pattern 1: Result Message Handling in SseStream.ts

```typescript
// Source: existing SseStream.ts switch statement (line 71–87)
// ADD this case alongside token/citations/done/error:
case 'result': {
  void webview.postMessage({
    type: 'result',
    intent: data['intent'] as string,
    result: data['result'] as Record<string, unknown>,
  });
  break;
}
```

### Pattern 2: Result State in App.tsx

```typescript
// New state alongside existing messages/isStreaming/etc.
const [structuredResult, setStructuredResult] = useState<{
  intent: string;
  result: Record<string, unknown>;
} | null>(null);

// In the message handler switch:
case 'result':
  setStructuredResult({ intent: msg.intent, result: msg.result });
  break;

// Clear on new query (in handleSend):
setStructuredResult(null);
```

### Pattern 3: Anomaly Score Bar (pure CSS, no library)

```tsx
// Score bar: a track div with a fill div — same pattern as existing progress-bar-track
<div className="score-bar-track">
  <div
    className="score-bar-fill"
    style={{ width: `${Math.round(suspect.anomaly_score * 100)}%` }}
  />
</div>
```

Color the fill based on score range using CSS classes or inline style. Score >= 0.7 → red, 0.4–0.7 → amber, < 0.4 → green.

### Pattern 4: Collapsible Section (existing SectionHeader pattern)

The `SectionHeader` component with `expanded`/`onToggle` is already proven in the codebase (Index and Activity sections). Use the same `useState<boolean>` + chevron pattern for impact_radius collapsible and finding suggestion expandable.

### Pattern 5: openFile for Suspect/Finding Clicks

```typescript
// Source: App.tsx line 271–273 (handleCitationClick)
// Same pattern — postMessage openFile with file_path and line_start:
vscode.postMessage({
  type: 'openFile',
  filePath: suspect.file_path,
  lineStart: suspect.line_start,
});
```

`SidebarProvider.ts` already handles `openFile` messages (lines 72–88) via `vscode.workspace.openTextDocument` + `vscode.window.showTextDocument`. No host changes needed.

### Pattern 6: Copy to Clipboard

VS Code webview does NOT allow `navigator.clipboard.writeText()` — the Content Security Policy blocks it. Use `document.execCommand('copy')` via a textarea trick, or use the VS Code API via postMessage:

```typescript
// Option A: execCommand (works in WebKit, deprecated but functional):
const textarea = document.createElement('textarea');
textarea.value = text;
document.body.appendChild(textarea);
textarea.select();
document.execCommand('copy');
document.body.removeChild(textarea);

// Option B: postMessage to host → vscode.env.clipboard.writeText()
// Requires new WebviewToHostMessage variant: { type: 'copyToClipboard', text: string }
// And a case in SidebarProvider.ts onDidReceiveMessage
```

Option A is simpler (no host changes). Option B is more correct per VS Code guidance. Given the project's existing pattern of minimal host changes, Option A is acceptable for this phase.

### Anti-Patterns to Avoid

- **Adding npm syntax-highlight libraries (Prism, highlight.js):** The webview bundle is built by esbuild — adding highlight.js adds ~50KB. The existing `<pre><code>` pattern in `renderMarkdown` is sufficient. CSS-only token coloring (background on the `<pre>`) is enough for EXT-08 per the requirement text.
- **Modifying SidebarProvider.ts for the openFile path:** It already handles `openFile`. Do not duplicate the handler.
- **Using `innerHTML` for code blocks:** `renderMarkdown` already avoids this; maintain that pattern.
- **Assuming the node name in traversal_path:** `traversal_path` contains `node_id` strings (e.g. `"path/to/file.py::function_name"`), not display names. The graph node attributes are NOT in the frontend payload. Display the node_id directly or parse the `::` suffix for a display name.
- **Blocking the result render on github_token without a backend change:** The extension has no access to backend env vars. Without threading `has_github_token` through the payload, EXT-07 cannot be implemented.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Severity color mapping | Custom CSS theme system | Hardcoded CSS vars with existing VS Code color pattern | Three values only: red/amber/blue — a switch/object lookup + inline style suffices |
| Collapsible disclosure | Custom animation library | Existing `useState` boolean + chevron character pattern | Already proven in Index/Activity sections |
| Syntax highlighting | Prism.js or highlight.js integration | `<pre><code>` with monospace font + code background color | Requirement is "syntax highlighting" but the scope is a webview panel, not a full IDE editor; a visually distinct code block satisfies EXT-08 |
| Clipboard access | Custom clipboard abstraction | `document.execCommand('copy')` textarea trick | Works in WebKit/Electron; no CSP violation |
| Score visualization | SVG chart library | `<div>` width bar with CSS | Single percentage value — a bar div is exactly right |

**Key insight:** The VS Code webview is a constrained environment (WebKit, CSP, no CDN access). Every external dependency must be bundled. The existing codebase deliberately avoids dependencies beyond React. Follow this pattern.

---

## Common Pitfalls

### Pitfall 1: github_token visibility (EXT-07)

**What goes wrong:** The extension sends queries to the backend but never reads `GITHUB_TOKEN` env var — that is server-side only. Attempting to read it from VS Code configuration (`vscode.workspace.getConfiguration`) will fail because `nexus.githubToken` is not a registered configuration property.

**Why it happens:** EXT-07 says "when github_token is configured" — this is a backend configuration, not a frontend one.

**How to avoid:** Add `has_github_token: bool` to the SSE result payload for the review intent. In `query_router.py`'s `v2_event_generator`, before yielding the result event, do:
```python
from app.config import get_settings
settings = get_settings()
payload = json.dumps({
    "type": "result",
    "intent": intent,
    "result": result_dict,
    "has_github_token": bool(settings.github_token),
})
```
Then the webview can read `msg.has_github_token` in the result handler.

**Warning signs:** If you see the "Post to GitHub PR" button trying to read a VS Code setting that doesn't exist in `package.json`'s `contributes.configuration`, this pitfall has been hit.

### Pitfall 2: Button global reset and !important

**What goes wrong:** Any new `<button>` element without explicit `!important` on background/border will have its styles overridden by the global reset at the top of `index.css`:
```css
button, button:focus, button:active {
  background: transparent !important;
  border: none !important;
  ...
}
```

**Why it happens:** Established project pattern documented in STATE.md (Phase 25 decision) and CSS comments. All buttons in this webview need `!important`.

**How to avoid:** Every styled button must use classes (like `.send-btn`, `.citation-chip`, `.intent-pill`) that override with `!important` on background and border. Add new CSS classes for severity badges, the "Post to GitHub PR" button, and the "Copy to clipboard" button.

### Pitfall 3: impact_radius contains node_ids, not display-friendly names

**What goes wrong:** `impact_radius: list[str]` from `DebugResult` contains graph node IDs (e.g. `"backend/app/agent/debugger.py::debug"`), not human-readable function names.

**Why it happens:** The orchestrator returns `specialist_result` directly — no post-processing. The node name attribute (`G.nodes[n].get("name", "")`) is NOT serialized into the result.

**How to avoid:** Parse the node_id string to extract a display name. The convention used in the codebase is `file_path::function_name`. Split on `::` and display the suffix. For the traversal breadcrumb, the same applies to `traversal_path`.

### Pitfall 4: HostToWebviewMessage type union in types.ts must be extended

**What goes wrong:** `types.ts` defines `HostToWebviewMessage` as a discriminated union. TypeScript will show errors if the webview code handles a `result` message type that isn't in the union.

**How to avoid:** Add the result variant to `types.ts`:
```typescript
| { type: 'result'; intent: string; result: Record<string, unknown>; has_github_token?: boolean }
```
And extend the `IncomingMessage` union inside `App.tsx` (which has its own local copy of this type).

### Pitfall 5: result and done arrive in order — don't race

**What goes wrong:** V2 SSE emits `result` then `done` in sequence. If the `done` handler clears streaming state before the `result` handler has set structured state, there may be a render flash.

**Why it happens:** Both events arrive close together. React batches state updates within a single synchronous event, but these come from separate `postMessage` calls.

**How to avoid:** The `done` handler sets `isStreaming: false`. The `result` handler sets `structuredResult`. These are independent state keys — both can be set in the same render cycle without conflict. No special ordering logic needed. Test by verifying the panel appears after the streaming indicator disappears.

### Pitfall 6: write_test_file is called in MCP layer — orchestrator does NOT call it

**What goes wrong:** Looking at the orchestrator code, `_test_node` calls `test()` and returns a `TestResult`. It does NOT call `write_test_file()`. The MCP tools are side-effect functions — they are called separately (e.g., as a post-processing step after the graph completes).

**Why it matters for EXT-09:** The current `v2_event_generator` in `query_router.py` invokes the graph, gets `specialist_result` (a `TestResult`), and immediately serializes it. `write_test_file` is never called in this code path. Therefore `TestResult.test_file_path` is a derived path but the file has NOT been written.

**How to avoid:** To implement EXT-09 correctly:
- Option A (minimal): Call `write_test_file()` inside `v2_event_generator` after the graph completes, when `intent == "test"`. Include `{"file_written": bool, "file_path": str|None}` in the SSE result payload.
- Option B (correct arch): Add an MCP node to the orchestrator graph that runs after `test_node`. This is more work but keeps the graph self-contained.

Option A is the right choice for this phase — it's confined to `query_router.py` and doesn't require graph refactoring.

---

## Code Examples

### result event handling in SseStream.ts

```typescript
// Source: existing switch in SseStream.ts (extend the switch at line 71)
case 'result': {
  void webview.postMessage({
    type: 'result',
    intent: data['intent'] as string,
    result: data['result'] as Record<string, unknown>,
    has_github_token: data['has_github_token'] as boolean | undefined,
  });
  break;
}
```

### DebugPanel component skeleton

```tsx
// Inline in App.tsx — consistent with project pattern of no separate component files

function DebugPanel({ result }: { result: Record<string, unknown> }): React.JSX.Element {
  const suspects = result.suspects as Array<{
    node_id: string; file_path: string; line_start: number;
    anomaly_score: number; reasoning: string;
  }>;
  const impactRadius = result.impact_radius as string[];
  const traversalPath = result.traversal_path as string[];
  const diagnosis = result.diagnosis as string;

  const [impactExpanded, setImpactExpanded] = useState(false);

  const openSuspect = (filePath: string, lineStart: number): void => {
    vscode.postMessage({ type: 'openFile', filePath, lineStart });
  };

  return (
    <div className="result-panel result-panel-debug">
      <div className="result-diagnosis">{diagnosis}</div>

      <div className="suspects-list">
        {suspects.map((s, i) => (
          <button
            key={s.node_id}
            className="suspect-row"
            onClick={() => openSuspect(s.file_path, s.line_start)}
          >
            <span className="suspect-rank">#{i + 1}</span>
            <span className="suspect-location">
              {s.file_path.split('/').pop()}:{s.line_start}
            </span>
            <div className="score-bar-track">
              <div
                className={`score-bar-fill score-${s.anomaly_score >= 0.7 ? 'high' : s.anomaly_score >= 0.4 ? 'mid' : 'low'}`}
                style={{ width: `${Math.round(s.anomaly_score * 100)}%` }}
              />
            </div>
            <span className="suspect-score">{s.anomaly_score.toFixed(2)}</span>
          </button>
        ))}
      </div>

      {/* Traversal breadcrumb */}
      <div className="traversal-breadcrumb">
        {traversalPath.map((nid, i) => (
          <React.Fragment key={nid}>
            <span className="traversal-node">{nid.split('::').pop() ?? nid}</span>
            {i < traversalPath.length - 1 && <span className="traversal-sep"> → </span>}
          </React.Fragment>
        ))}
      </div>

      {/* Impact radius collapsible */}
      <button
        className="collapsible-header"
        onClick={() => setImpactExpanded(v => !v)}
      >
        <span className="section-chevron">{impactExpanded ? '▾' : '▸'}</span>
        Impact radius ({impactRadius.length})
      </button>
      {impactExpanded && (
        <ul className="impact-list">
          {impactRadius.map(nid => (
            <li key={nid}>{nid.split('::').pop() ?? nid}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
```

### Severity badge color mapping

```tsx
// Object lookup — no switch needed
const SEVERITY_CLASS: Record<string, string> = {
  critical: 'badge-critical',
  warning:  'badge-warning',
  info:     'badge-info',
};

// CSS (extends index.css):
// .badge-critical { background: rgba(244,67,54,0.18); color: var(--vscode-errorForeground, #f44336); }
// .badge-warning  { background: rgba(255,152,0,0.22); color: #ff9800; }
// .badge-info     { background: rgba(33,150,243,0.18); color: #2196f3; }
// These match the existing .log-badge pattern in index.css
```

### v2_event_generator patch for EXT-07 and EXT-09

```python
# In query_router.py v2_event_generator, after result_dict is built:

# EXT-07: surface has_github_token for review intent
from app.config import get_settings as _get_settings  # noqa: PLC0415
_settings = _get_settings()
has_github_token = bool(_settings.github_token)

# EXT-09: call write_test_file for test intent
file_written = False
written_path = None
if intent == "test" and hasattr(specialist, "test_code"):
    from app.mcp.tools import write_test_file  # noqa: PLC0415
    mcp_result = write_test_file(
        specialist.test_code,
        specialist.test_file_path,
        base_dir=request_body.repo_path or ".",
    )
    file_written = mcp_result["success"]
    written_path = mcp_result.get("path")

payload = json.dumps({
    "type": "result",
    "intent": intent,
    "result": result_dict,
    "has_github_token": has_github_token,
    "file_written": file_written,
    "written_path": written_path,
})
yield f"event: result\ndata: {payload}\n\n"
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| V1: streaming tokens only | V2: single `result` SSE event with full structured payload | Phase 24 | Webview must handle both token-streaming (V1/explain path) and result-panel (V2 debug/review/test) rendering |
| No intent selector | Intent pills (auto/explain/debug/review/test) | Phase 25 | `selectedIntent` state already tracks which specialist was invoked — can use it to pre-select which panel to show |

**Note on explain intent:** The V2 explain path still uses `specialist_result = _ExplainResult(answer, nodes, stats)` but the SSE `result` event carries it as `{answer: str, nodes: [...], stats: {...}}`. The current webview handles explain via the V1 token-streaming path. If `intent_hint` is set to `explain`, it goes through V2 graph — so the result event will arrive with `intent: "explain"` and an `_ExplainResult` shape. The webview should fall back to rendering `result.answer` via `renderMarkdown` for explain intent.

---

## Open Questions

1. **Does the "Post to GitHub PR" button need to actually trigger the GitHub API call?**
   - What we know: EXT-07 says "shows button when github_token configured" — it does not say the button must be functional in the webview.
   - What's unclear: Does clicking the button need to call `post_review_comments` via the backend, or is the button purely decorative/informational for V2?
   - Recommendation: Implement as a working button that posts a new `postReviewToPR` webview message, handled in `SidebarProvider.ts` by calling a new `POST /review/post-pr` backend endpoint — BUT this may be scope creep. For Phase 26, show the button and wire it to a `vscode.window.showInformationMessage("GitHub PR posting not yet wired")` placeholder. The requirement only says "shows button when configured."

2. **Traversal breadcrumb: show all node_ids or just top N?**
   - What we know: `traversal_path` can contain up to ~20 nodes (6 nodes in tests, but production graphs can be larger with max_hops=4).
   - What's unclear: The requirement says "traversal breadcrumb chain" — no length constraint specified.
   - Recommendation: Show max 8 nodes in the breadcrumb with a "... +N more" truncation if longer, using the same pattern as citation chips.

3. **Does the explain V2 path need a panel?**
   - What we know: `intent_hint = 'explain'` → V2 graph → `_ExplainResult` → `result` SSE event. But V1 explain path still uses token streaming.
   - What's unclear: EXT-04 through EXT-09 only cover debug/review/test. The explain path rendering is not a requirement for Phase 26.
   - Recommendation: Add a fallback in the `result` handler: if `intent === 'explain'`, render `result.answer` via `renderMarkdown` in the existing message bubble format. This preserves V2 explain compatibility without building a dedicated panel.

---

## Sources

### Primary (HIGH confidence)
- `backend/app/agent/debugger.py` — `SuspectNode`, `DebugResult` Pydantic models; field names and types confirmed directly from source
- `backend/app/agent/reviewer.py` — `Finding`, `ReviewResult` Pydantic models; severity literal type (`'critical' | 'warning' | 'info'`) confirmed from source
- `backend/app/agent/tester.py` — `TestResult` model; `test_code`, `test_file_path`, `framework` fields confirmed
- `backend/app/api/query_router.py` — SSE event format; `event: result` payload structure (`type`, `intent`, `result`); `model_dump(mode="json")` serialization
- `backend/app/mcp/tools.py` — `write_test_file` return shape `{"success": bool, "path": str|None, "error": str|None}` confirmed; orchestrator does NOT call it
- `backend/app/agent/orchestrator.py` — Confirmed `write_test_file` is not called in the graph; `_test_node` returns `TestResult` directly
- `backend/app/config.py` — `github_token: str = ""` confirmed as backend env var; extension has no direct access
- `extension/src/SseStream.ts` — Current SSE event handling; confirmed `result` case is missing
- `extension/src/webview/App.tsx` — React state patterns; existing `IncomingMessage` union; `openFile` message pattern
- `extension/src/webview/index.css` — CSS conventions; global button reset with `!important`; existing badge, chip, bar patterns
- `extension/src/webview/types.ts` — `HostToWebviewMessage` union; `WebviewToHostMessage` union; `openFile` already defined
- `extension/src/SidebarProvider.ts` — `openFile` handler at lines 72–88; confirms no host changes needed for file navigation

### Secondary (MEDIUM confidence)
- VS Code webview CSP constraints — `navigator.clipboard` unavailable in WebKit webview; `execCommand('copy')` is the accepted workaround (documented in VS Code extension development guides)

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all existing; no new dependencies needed
- Architecture: HIGH — all data shapes confirmed directly from source files; SSE format confirmed from query_router.py
- Pitfalls: HIGH for button reset (!important), github_token gap, write_test_file not called — all confirmed from source; MEDIUM for clipboard approach (WebKit-specific behavior)
- EXT-07 has_github_token approach: HIGH — design is clear; implementation is a one-line backend addition

**Research date:** 2026-03-22
**Valid until:** 2026-04-22 (stable domain — no fast-moving dependencies)
