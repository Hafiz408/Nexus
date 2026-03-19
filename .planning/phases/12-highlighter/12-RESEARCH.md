# Phase 12: Highlighter - Research

**Researched:** 2026-03-19
**Domain:** VS Code TextEditorDecorationType API — editor line highlighting from extension host
**Confidence:** HIGH

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| HIGH-01 | `highlightCitations(citations)` groups citations by file path, opens documents, applies `TextEditorDecorationType` to cited line ranges | `vscode.window.createTextEditorDecorationType` + `editor.setDecorations(type, ranges)` with `vscode.Range` per line. Open documents with `vscode.workspace.openTextDocument` + `vscode.window.showTextDocument`. |
| HIGH-02 | Uses `editor.findMatchHighlightBackground` theme color; clears after 10 seconds or next query | `new vscode.ThemeColor('editor.findMatchHighlightBackground')` in `backgroundColor`. `setTimeout(clearHighlights, 10_000)` pattern; cancel on next query call. |
</phase_requirements>

---

## Summary

Phase 12 adds a `HighlightService` to the VS Code extension host. When the backend streams citations after a query, the extension host must open every cited file, apply a line-range background decoration using the editor's built-in find-match color, and automatically clear those decorations after 10 seconds (or when the next query starts). All decoration work happens entirely within the extension host using the `vscode.window` and `vscode.workspace` APIs — no changes to the React webview are needed for the highlight behavior itself.

The VS Code API for this is mature and well-documented. `vscode.window.createTextEditorDecorationType` accepts a `DecorationRenderOptions` with a `backgroundColor` of type `ThemeColor`, which enables the highlight to adapt when users switch themes. The `TextEditorDecorationType` instance is created once and reused across queries; each new call to `editor.setDecorations(type, [])` with an empty array effectively clears previous highlights. Because the same `TextEditorDecorationType` is reused, calling `setDecorations` with a new set of ranges on the same editor overwrites the previous set for that type — this is the standard clear-and-replace pattern.

The principal integration point is `SidebarProvider.ts`. It already handles `citations` messages from the SSE stream (in `SseStream.ts` at the `case 'citations':` branch) and forwards them to the webview. The planner needs to wire a `HighlightService` call from `SidebarProvider` when citations arrive — before or after posting them to the webview.

**Primary recommendation:** Create `extension/src/HighlightService.ts` as a standalone class. Instantiate it in `SidebarProvider`. Call `highlightCitations(citations)` when a `citations` SSE event arrives in `SseStream.ts` (passed via callback). Clear on `query` start.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `vscode` (built-in) | `^1.74.0` (project minimum) | `createTextEditorDecorationType`, `setDecorations`, `ThemeColor`, `openTextDocument`, `showTextDocument` | It is the only API for editor decoration in VS Code extensions — no alternative library exists |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| TypeScript (project) | `^5.0.0` | Type safety for `vscode.Range`, `Citation[]`, decoration options | Already in use; no addition needed |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `new vscode.ThemeColor(id)` | Hardcoded hex color string | ThemeColor adapts to user's active theme; hex string breaks in high-contrast and dark themes |
| Reusing one `TextEditorDecorationType` | Creating a new one per query | One instance is correct: reuse avoids a known memory leak from never calling `.dispose()` on abandoned types |

**Installation:**
No new packages needed. Everything uses the `vscode` built-in module already present.

---

## Architecture Patterns

### Recommended Project Structure
```
extension/src/
├── HighlightService.ts    # new — encapsulates decoration type, apply, clear
├── SidebarProvider.ts     # existing — instantiates HighlightService, calls it on citations
├── SseStream.ts           # existing — add onCitations callback parameter
├── extension.ts           # existing — no changes needed
└── types.ts               # existing — Citation interface already defined
```

### Pattern 1: HighlightService Class

**What:** A class that owns one `TextEditorDecorationType` instance, applies decorations to all cited line ranges grouped by file, and auto-clears after a timeout.

**When to use:** Any time `citations` SSE event arrives with a non-empty array.

**Example:**
```typescript
// Source: VS Code API official docs + decorator-sample
// https://code.visualstudio.com/api/references/vscode-api#TextEditorDecorationType
import * as vscode from 'vscode';
import { Citation } from './types';

export class HighlightService {
  private readonly _decorationType: vscode.TextEditorDecorationType;
  private _clearTimer: ReturnType<typeof setTimeout> | undefined;

  constructor() {
    this._decorationType = vscode.window.createTextEditorDecorationType({
      backgroundColor: new vscode.ThemeColor('editor.findMatchHighlightBackground'),
      isWholeLine: true,
    });
  }

  async highlightCitations(citations: Citation[]): Promise<void> {
    // Cancel any pending auto-clear from a previous query
    this.clearHighlights();

    // Group by file_path
    const byFile = new Map<string, Citation[]>();
    for (const c of citations) {
      const list = byFile.get(c.file_path) ?? [];
      list.push(c);
      byFile.set(c.file_path, list);
    }

    for (const [filePath, fileCitations] of byFile) {
      try {
        const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(filePath));
        // showTextDocument is only called for the first cited file to avoid
        // hijacking user focus across many files. Decorations apply to all.
        const editor = await vscode.window.showTextDocument(doc, {
          preserveFocus: true,
          preview: false,
        });
        const ranges = fileCitations.map((c) => {
          const startLine = Math.max(0, c.line_start - 1); // 1-indexed to 0-indexed
          const endLine = Math.max(startLine, c.line_end - 1);
          return new vscode.Range(
            new vscode.Position(startLine, 0),
            new vscode.Position(endLine, Number.MAX_SAFE_INTEGER)
          );
        });
        editor.setDecorations(this._decorationType, ranges);
      } catch {
        // File may not exist on disk or editor may have closed — skip silently
      }
    }

    // Auto-clear after 10 seconds (HIGH-02)
    this._clearTimer = setTimeout(() => this.clearHighlights(), 10_000);
  }

  clearHighlights(): void {
    if (this._clearTimer !== undefined) {
      clearTimeout(this._clearTimer);
      this._clearTimer = undefined;
    }
    // Passing empty array to setDecorations clears all decorations of this type
    for (const editor of vscode.window.visibleTextEditors) {
      if (editor.document) { // guard against invisible/detached editors (see pitfalls)
        editor.setDecorations(this._decorationType, []);
      }
    }
  }

  dispose(): void {
    this.clearHighlights();
    this._decorationType.dispose();
  }
}
```

### Pattern 2: Integration in SidebarProvider

**What:** `HighlightService` is instantiated in `SidebarProvider` constructor. `clearHighlights()` is called when a new `query` message arrives (before `streamQuery`). `highlightCitations()` is called when citations arrive from the SSE stream.

**When to use:** Modify the existing `streamQuery` call site and the `'citations'` branch in `SseStream.ts`.

**Example — SseStream.ts change:**
```typescript
// Source: existing SseStream.ts pattern, extended with citations callback
export async function streamQuery(
  question: string,
  repoPath: string,
  webview: vscode.Webview,
  backendUrl: string,
  onCitations?: (citations: Citation[]) => void   // <-- add this
): Promise<void> {
  // ... existing fetch and reader logic ...
  case 'citations': {
    const citations = data['citations'] as Citation[];
    void webview.postMessage({ type: 'citations', citations });
    onCitations?.(citations);    // <-- call the callback
    break;
  }
}
```

**Example — SidebarProvider.ts change:**
```typescript
// In constructor, add:
private readonly _highlight: HighlightService;

// constructor body:
this._highlight = new HighlightService();

// In 'query' case handler, before streamQuery:
this._highlight.clearHighlights();   // clear on new query (HIGH-02)

// streamQuery call:
await streamQuery(
  msg.question,
  this._repoPath,
  webviewView.webview,
  backendUrl,
  (citations) => { void this._highlight.highlightCitations(citations); }
);
```

**dispose:** Register `this._highlight` via `context.subscriptions.push` in `extension.ts` (or expose a `dispose()` on `SidebarProvider` and push it).

### Anti-Patterns to Avoid

- **Creating a new `TextEditorDecorationType` per query:** Causes a memory leak if `.dispose()` is never called on abandoned instances. One instance, reused across queries.
- **Calling `showTextDocument` for every cited file:** Opens N editor tabs, hijacking focus. Open only the first file (or use `preserveFocus: true`). Decorations apply to all editors regardless of whether `showTextDocument` is called — but `setDecorations` requires a `TextEditor` object, and `openTextDocument` alone does not produce one. Solution: call `showTextDocument` with `preserveFocus: true` to get the editor without stealing focus, or filter to already-visible editors using `vscode.window.visibleTextEditors`.
- **Calling `setDecorations` without a null-check on `editor.document`:** VS Code may return detached editors in `visibleTextEditors`. Always guard: `if (editor.document) { ... }`.
- **Using a hardcoded hex color instead of `ThemeColor`:** Breaks in high-contrast and custom themes.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Line background highlight | Custom webview rendering overlay | `vscode.window.createTextEditorDecorationType` + `setDecorations` | The native decoration API handles all theme variants, zoom levels, font scaling, and overview ruler placement automatically |
| Theme-aware color lookup | Reading theme JSON at runtime | `new vscode.ThemeColor('editor.findMatchHighlightBackground')` | VS Code resolves the color token per active theme; manual lookup breaks on theme change |
| 10-second auto-clear timer | Custom timer class | `setTimeout` / `clearTimeout` (built-in) | This is a simple JS timer — nothing to abstract |
| Clearing decorations | Re-creating and disposing the decoration type | `editor.setDecorations(type, [])` with empty array | Calling `setDecorations` with `[]` clears without destroying the type; disposing the type requires re-creating it on the next query |

**Key insight:** The VS Code decoration API is purpose-built for exactly this use case. There is no npm library that adds value here.

---

## Common Pitfalls

### Pitfall 1: setDecorations on Invisible/Detached Editor
**What goes wrong:** Calling `editor.setDecorations(type, [])` on an editor that has since been closed logs a warning ("setDecorations on invisible editor") and in some VS Code versions can throw.
**Why it happens:** `vscode.window.visibleTextEditors` is a snapshot; editors can close between the snapshot and the `setDecorations` call (race condition documented in microsoft/vscode#18797).
**How to avoid:** Guard with `if (editor.document) { editor.setDecorations(...) }` — after the fix in that issue, detached editors return `undefined` for `.document`.
**Warning signs:** Console warning "setDecorations on invisible editor" in Extension Development Host output.

### Pitfall 2: Line Index Off-by-One
**What goes wrong:** Highlighted line is one line off from the actual citation.
**Why it happens:** The `Citation` type uses 1-indexed `line_start`/`line_end` (matching source file display convention), but VS Code `Position` is 0-indexed.
**How to avoid:** Always subtract 1: `const startLine = Math.max(0, c.line_start - 1)`.
**Warning signs:** Highlight appears on the line above the cited symbol.

### Pitfall 3: `openTextDocument` Does Not Return a `TextEditor`
**What goes wrong:** `openTextDocument` returns a `TextDocument`, not a `TextEditor`. `setDecorations` requires a `TextEditor`. If you skip `showTextDocument`, you have no editor object to decorate.
**Why it happens:** This is the VS Code API split: documents can be open (in memory) without being shown in an editor tab.
**How to avoid:** Call `vscode.window.showTextDocument(doc, { preserveFocus: true, preview: false })` to get the editor. Use `preserveFocus: true` so the editor doesn't steal focus from the user's current view.
**Warning signs:** TypeScript error "Property 'setDecorations' does not exist on type 'TextDocument'".

### Pitfall 4: Memory Leak from Abandoned Decoration Types
**What goes wrong:** Each `createTextEditorDecorationType` call allocates resources in the extension host. If a new instance is created per query without disposing the previous one, the extension leaks.
**Why it happens:** Decoration types are disposable resources — the extension host does not garbage-collect them automatically.
**How to avoid:** Create exactly one `TextEditorDecorationType` in the `HighlightService` constructor. Reuse it across all queries. Dispose it only in `HighlightService.dispose()` when the extension deactivates.
**Warning signs:** VS Code extension memory usage grows steadily with each query.

### Pitfall 5: Timer Not Cleared on Next Query
**What goes wrong:** The 10-second auto-clear fires after a second query has already applied new highlights, wiping valid decorations.
**Why it happens:** `setTimeout` callback holds a reference to `clearHighlights` without knowing that new highlights have replaced the old ones.
**How to avoid:** Always call `clearHighlights()` at the start of `highlightCitations()`. This cancels any pending timer and clears old decorations before applying new ones.
**Warning signs:** Highlights from the second query disappear 10 seconds after the first query, not 10 seconds after the second.

---

## Code Examples

Verified patterns from official sources:

### Creating a ThemeColor Decoration Type
```typescript
// Source: https://code.visualstudio.com/api/references/vscode-api#window.createTextEditorDecorationType
const decorationType = vscode.window.createTextEditorDecorationType({
  backgroundColor: new vscode.ThemeColor('editor.findMatchHighlightBackground'),
  isWholeLine: true,
});
```

### Applying Decorations to a Range
```typescript
// Source: https://code.visualstudio.com/api/references/vscode-api#TextEditor.setDecorations
// Range is 0-indexed; Citation.line_start is 1-indexed
const range = new vscode.Range(
  new vscode.Position(citation.line_start - 1, 0),
  new vscode.Position(citation.line_end - 1, Number.MAX_SAFE_INTEGER)
);
editor.setDecorations(decorationType, [range]);
```

### Clearing Decorations
```typescript
// Source: VS Code API docs — setDecorations with empty array clears all for that type
editor.setDecorations(decorationType, []);
```

### Opening a Document and Getting an Editor
```typescript
// Source: https://code.visualstudio.com/api/references/vscode-api#window.showTextDocument
const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(filePath));
const editor = await vscode.window.showTextDocument(doc, {
  preserveFocus: true,   // do not steal focus from current editor
  preview: false,        // do not open in preview (reusable) tab
});
```

### Registering HighlightService for Disposal
```typescript
// In extension.ts activate():
// If SidebarProvider.dispose() is exposed, push it to context.subscriptions
context.subscriptions.push({ dispose: () => provider.dispose() });
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Hardcoded hex `backgroundColor: '#ffff0033'` | `new vscode.ThemeColor('editor.findMatchHighlightBackground')` | ThemeColor added in VS Code 1.12 | Decorations now adapt to all themes automatically |
| Registering custom theme colors in `contributes.colors` | Using built-in editor token `editor.findMatchHighlightBackground` | N/A | No manifest registration needed for built-in tokens |
| `TextEditorDecorationType.dispose()` to clear | `setDecorations(type, [])` to clear without disposing | N/A | Reuse the same type across queries; only dispose on extension deactivate |

**Deprecated/outdated:**
- Calling `dispose()` to "clear" decorations mid-session: Incorrect — dispose frees the type permanently. Use `setDecorations(type, [])` to clear and then re-apply later.

---

## Open Questions

1. **Should `showTextDocument` be called for every cited file or only the first?**
   - What we know: Each `showTextDocument` call switches the active editor tab. `preserveFocus: true` mitigates focus stealing but still opens tabs.
   - What's unclear: Whether citations in Phase 12 will commonly span multiple files or typically reference one file.
   - Recommendation: For Phase 12, call `showTextDocument` with `preserveFocus: true` for only the first cited file. Apply decorations to all already-visible editors for other files via `vscode.window.visibleTextEditors` filtering. This avoids tab explosion.

2. **Disposing `HighlightService` when the extension deactivates**
   - What we know: `context.subscriptions` accepts any `{ dispose(): void }` object. If `SidebarProvider` does not expose `dispose()`, the `HighlightService` instance created inside it will not be cleaned up on deactivation.
   - What's unclear: Whether the extension currently exposes any disposal path from `SidebarProvider` to `extension.ts`.
   - Recommendation: Add a `dispose()` method to `SidebarProvider` that calls `this._highlight.dispose()`, and register it via `context.subscriptions.push({ dispose: () => provider.dispose() })` in `extension.ts`.

---

## Sources

### Primary (HIGH confidence)
- https://code.visualstudio.com/api/references/vscode-api#TextEditorDecorationType — `createTextEditorDecorationType`, `setDecorations`, `ThemeColor`, method signatures verified
- https://code.visualstudio.com/api/references/theme-color — exact key `editor.findMatchHighlightBackground` confirmed
- https://github.com/microsoft/vscode-extension-samples/blob/main/decorator-sample/src/extension.ts — official Microsoft decorator sample pattern

### Secondary (MEDIUM confidence)
- https://github.com/microsoft/vscode/issues/18797 — "setDecorations on invisible editor" race condition; confirmed fix is `if (editor.document)` guard
- https://vscode.rocks/decorations/ — VS Code Rocks decorations guide, corroborates official docs patterns

### Tertiary (LOW confidence)
- WebSearch result re: multiple-file openTextDocument async issues (github.com/microsoft/vscode/issues/113729) — not directly read; note to sequence `showTextDocument` calls serially if needed

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — VS Code API is stable, official docs verified
- Architecture: HIGH — patterns verified against official decorator-sample and API reference
- Pitfalls: HIGH (pitfall 1-3) / MEDIUM (pitfall 4-5) — pitfall 1 verified against GitHub issue; pitfalls 4-5 from API design knowledge corroborated by docs

**Research date:** 2026-03-19
**Valid until:** 2026-06-19 (VS Code API is very stable; ThemeColor identifiers rarely change)
