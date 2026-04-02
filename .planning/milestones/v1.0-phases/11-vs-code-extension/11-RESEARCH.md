# Phase 11: VS Code Extension - Research

**Researched:** 2026-03-19
**Domain:** VS Code Extension API — WebviewViewProvider, React 18 sidebar, SSE streaming, TypeScript
**Confidence:** HIGH (core VS Code API), MEDIUM (build tooling patterns), HIGH (SSE architecture)

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| EXT-01 | Extension activates on VS Code startup; registers `nexus.sidebar` WebviewViewProvider | Activation event `onStartupFinished`; `vscode.window.registerWebviewViewProvider` API documented |
| EXT-02 | Registers commands: `nexus.indexWorkspace`, `nexus.clearIndex` | `vscode.commands.registerCommand` API; commands declared in package.json `contributes.commands` |
| EXT-03 | `package.json` contributes activity bar icon `$(circuit-board)`, sidebar view, commands, configuration (`backendUrl`, `hopDepth`, `maxNodes`) | Full package.json schema for `viewsContainers`, `views`, `commands`, `configuration` documented |
| EXT-04 | On activation with open workspace, automatically triggers `IndexerService.indexWorkspace()` | `vscode.workspace.workspaceFolders` API; check in `activate()` after registration |
| CHAT-01 | React 18 Webview shows chat messages with `user` and `assistant` roles | React 18 + `createRoot` bundled via esbuild into webview; dual-bundle architecture documented |
| CHAT-02 | Streaming: tokens append to last assistant message in real-time | Extension host fetches SSE, forwards tokens via `webview.postMessage()`; webview React state updates on `window.addEventListener('message')` |
| CHAT-03 | Citations rendered as clickable chips; click opens file at correct line | Webview posts citation click message to extension host; host calls `vscode.window.showTextDocument` with `selection` Range (0-indexed) |
| CHAT-04 | Index status bar shows spinner / `Ready — N nodes` / `Not indexed` + Index Workspace button | `vscode.window.createStatusBarItem`; status bar text updated from `BackendClient` polling results |
| CHAT-05 | Styling uses VS Code CSS variables (`--vscode-*`); no external CSS frameworks | VS Code injects all theme colors as `--vscode-*` CSS variables into webview `<html>`; naming: `editor.foreground` → `var(--vscode-editor-foreground)` |
| SSE-01 | `BackendClient.ts` sends `POST /index` and polls `GET /index/status` every 2 seconds | Extension host Node.js `fetch()` (no CORS restriction); `setInterval` polling; cancel on complete/failed |
| SSE-02 | `SseStream.ts` parses native EventSource stream; forwards token/citations/done/error events | Extension host uses `fetch()` + `response.body.getReader()` + `TextDecoder`; NOT browser EventSource (POST not supported by EventSource); parse lines manually |
| SSE-03 | SidebarProvider forwards events to Webview via `webview.postMessage()` | `webviewView.webview.postMessage({ type, content })` — called from extension host after receiving SSE token |
</phase_requirements>

---

## Summary

Phase 11 builds a VS Code sidebar extension that surfaces Nexus chat in the editor. The extension has two distinct runtime contexts that must not be confused: the **extension host** (Node.js process, full filesystem/network access, runs `extension.ts`) and the **webview** (sandboxed browser-like context, runs the React bundle). All HTTP calls — including the SSE stream from the backend — MUST be made from the extension host, never from the webview. The webview cannot fetch `http://localhost:8000` directly due to CORS restrictions enforced by VS Code's webview security sandbox.

The correct data flow is: extension host `fetch()` → SSE stream consumed line-by-line → each token forwarded to webview via `webviewView.webview.postMessage()` → React state update appends token to last message. Citation chip clicks flow in reverse: webview `vscode.postMessage({ type: 'openFile', ... })` → extension host handles `webview.onDidReceiveMessage` → `vscode.window.showTextDocument` opens file at line.

The build system requires **two separate esbuild bundles**: one for the extension host (`src/extension.ts`, platform: node, externals: vscode) and one for the webview React app (`src/webview/index.tsx`, platform: browser). The webview bundle is injected into the HTML via `webview.asWebviewUri()` with a CSP nonce.

**Primary recommendation:** Implement extension host as the sole HTTP client; webview is pure UI state machine receiving postMessage events. Use esbuild with two entry points. Use `onStartupFinished` activation event.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `@types/vscode` | `^1.74.0` | VS Code API TypeScript types | WebviewViewProvider + view-type without activationEvent requires 1.74+ |
| `vscode` (engine) | `^1.74.0` | Minimum VS Code engine version | `onView` auto-activation for contributed views added in 1.74 |
| `typescript` | `^5.x` | Extension host + webview type checking | Both bundles use TypeScript |
| `esbuild` | `^0.20.x` | Dual-bundle builder (extension host + webview) | Fastest bundler; simple two-entry-point config; official VS Code docs recommend it |
| `react` | `^18.x` | Webview UI | `createRoot` API; concurrent rendering; required by CHAT-01 |
| `react-dom` | `^18.x` | Webview DOM rendering | Paired with react 18 |
| `@types/react` | `^18.x` | TypeScript types for React | devDependency |
| `@types/react-dom` | `^18.x` | TypeScript types for ReactDOM | devDependency |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `@vscode/codicons` | `^0.0.35` | Codicon font for extension icons | Use `$(circuit-board)` icon in activitybar; loaded via webview URI |
| No external CSS framework | — | Styling | CHAT-05 requires `--vscode-*` CSS variables only; no Tailwind, no MUI |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Manual SSE parsing with `fetch` | `EventSource` browser API | EventSource does not support POST requests; backend `/query` is POST; use `fetch` + `getReader()` |
| `EventSource` from `eventsource` npm package | Native `fetch` + ReadableStream | `eventsource` package adds a dependency; Node.js 18+ `fetch` is built-in |
| `vite` for webview bundling | `esbuild` directly | Vite adds complexity; esbuild two-entry-point config is simpler for this use case |
| External CSS framework (Tailwind) | VS Code CSS variables | CHAT-05 explicitly prohibits external CSS frameworks |

**Installation:**
```bash
# In extension/ directory
npm install react react-dom
npm install --save-dev typescript esbuild @types/vscode @types/react @types/react-dom
```

---

## Architecture Patterns

### Recommended Project Structure
```
extension/
├── package.json               # Extension manifest — engines, contributes, activationEvents
├── tsconfig.json              # TypeScript config for extension host (target: ES2022, module: commonjs)
├── tsconfig.webview.json      # TypeScript config for webview (jsx: react-jsx, lib: ES2022 DOM)
├── esbuild.js                 # Build script — two entry points
├── src/
│   ├── extension.ts           # activate() — registers provider, commands, status bar
│   ├── SidebarProvider.ts     # WebviewViewProvider — resolveWebviewView, postMessage bridge
│   ├── BackendClient.ts       # HTTP client — POST /index, GET /index/status polling
│   ├── SseStream.ts           # SSE consumer — fetch() + ReadableStream line parser
│   └── webview/
│       ├── index.tsx          # React entry — createRoot, mounts <App />
│       ├── App.tsx            # Chat UI — message list, input, citation chips
│       ├── types.ts           # Shared message types (WebviewMessage union)
│       └── index.css          # CSS using --vscode-* variables only
├── media/
│   └── nexus.svg              # Activity bar icon (SVG, monochrome)
└── out/                       # Compiled output (gitignored)
    ├── extension.js           # Bundled extension host
    └── webview/
        └── index.js           # Bundled React webview app
```

### Pattern 1: Two-Context Mental Model
**What:** Extension host (Node.js) and webview (browser sandbox) are completely separate processes. They communicate only via `postMessage`.
**When to use:** Always — this is the fundamental VS Code webview architecture.
**Example:**
```typescript
// Source: https://code.visualstudio.com/api/extension-guides/webview

// Extension host side — send to webview
webviewView.webview.postMessage({ type: 'token', content: 'Hello' });

// Webview side — receive from extension host
window.addEventListener('message', (event) => {
  const msg = event.data; // { type: 'token', content: 'Hello' }
});

// Webview side — send to extension host
const vscode = acquireVsCodeApi();
vscode.postMessage({ type: 'query', question: 'What does auth do?' });

// Extension host side — receive from webview
webviewView.webview.onDidReceiveMessage((msg) => {
  if (msg.type === 'query') { /* start SSE stream */ }
});
```

### Pattern 2: WebviewViewProvider Registration
**What:** Implement `vscode.WebviewViewProvider` to provide the sidebar webview content.
**When to use:** Required for EXT-01 — registering the `nexus.sidebar` view.
**Example:**
```typescript
// Source: https://code.visualstudio.com/api/references/vscode-api
import * as vscode from 'vscode';

export class SidebarProvider implements vscode.WebviewViewProvider {
  public static readonly viewType = 'nexus.sidebar';

  constructor(private readonly _extensionUri: vscode.Uri) {}

  resolveWebviewView(
    webviewView: vscode.WebviewView,
    _context: vscode.WebviewViewResolveContext,
    _token: vscode.CancellationToken
  ): void {
    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [this._extensionUri],
    };
    webviewView.webview.html = this._getHtmlForWebview(webviewView.webview);

    // Listen for messages from webview
    webviewView.webview.onDidReceiveMessage(async (msg) => {
      if (msg.type === 'query') {
        await this._handleQuery(msg.question, webviewView.webview);
      }
    });
  }

  private _getHtmlForWebview(webview: vscode.Webview): string {
    const scriptUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this._extensionUri, 'out', 'webview', 'index.js')
    );
    const nonce = getNonce(); // random 32-char hex
    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="Content-Security-Policy"
    content="default-src 'none'; script-src 'nonce-${nonce}'; style-src ${webview.cspSource} 'unsafe-inline';">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body>
  <div id="root"></div>
  <script nonce="${nonce}" src="${scriptUri}"></script>
</body>
</html>`;
  }
}
```

### Pattern 3: SSE Consumption in Extension Host (NOT Webview)
**What:** Use Node.js `fetch()` with `response.body.getReader()` to consume the SSE stream. Forward each token to the webview via `postMessage`.
**When to use:** Required for SSE-02, SSE-03 — the webview CANNOT fetch localhost due to CORS.
**Example:**
```typescript
// Source: verified pattern; Node.js fetch + ReadableStream

async function consumeSseStream(
  question: string,
  repoPath: string,
  webview: vscode.Webview,
  backendUrl: string
): Promise<void> {
  const response = await fetch(`${backendUrl}/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, repo_path: repoPath }),
  });

  if (!response.ok || !response.body) {
    webview.postMessage({ type: 'error', message: `HTTP ${response.status}` });
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE events are separated by \n\n
    const parts = buffer.split('\n\n');
    buffer = parts.pop() ?? ''; // last incomplete chunk stays in buffer

    for (const part of parts) {
      const eventLine = part.split('\n').find(l => l.startsWith('event: '));
      const dataLine = part.split('\n').find(l => l.startsWith('data: '));
      if (!eventLine || !dataLine) continue;

      const eventType = eventLine.slice(7).trim(); // "token", "citations", "done", "error"
      const data = JSON.parse(dataLine.slice(6));

      // Forward parsed event to webview
      webview.postMessage({ type: eventType, ...data });
    }
  }
}
```

### Pattern 4: Dual esbuild Configuration
**What:** Two separate build targets — extension host (Node.js commonjs) and webview (browser ESM).
**When to use:** Required because extension host needs `vscode` external and Node.js globals; webview needs browser APIs and React JSX transform.
**Example:**
```javascript
// esbuild.js — Source: https://www.kenmuse.com/blog/using-react-in-vs-code-webviews/ (verified 2024)
const esbuild = require('esbuild');

const baseConfig = {
  bundle: true,
  minify: process.env.NODE_ENV === 'production',
  sourcemap: process.env.NODE_ENV !== 'production',
};

// Extension host bundle
esbuild.build({
  ...baseConfig,
  platform: 'node',
  entryPoints: ['src/extension.ts'],
  outfile: 'out/extension.js',
  external: ['vscode'],
  format: 'cjs',
});

// Webview React bundle
esbuild.build({
  ...baseConfig,
  platform: 'browser',
  entryPoints: ['src/webview/index.tsx'],
  outfile: 'out/webview/index.js',
  format: 'iife', // IIFE for webview script tag injection
});
```

### Pattern 5: Opening a File at Specific Line (Citation Click)
**What:** Webview sends citation click message; extension host opens file at the cited line.
**When to use:** Required for CHAT-03 — citation chip click navigates to file:line.
**Example:**
```typescript
// Source: https://code.visualstudio.com/api/references/vscode-api
// NOTE: VS Code Position is 0-indexed; backend line_start is 1-indexed

webviewView.webview.onDidReceiveMessage(async (msg) => {
  if (msg.type === 'openFile') {
    const { filePath, lineStart } = msg;
    const uri = vscode.Uri.file(filePath);
    const doc = await vscode.workspace.openTextDocument(uri);
    const line0 = Math.max(0, lineStart - 1); // convert 1-indexed to 0-indexed
    await vscode.window.showTextDocument(doc, {
      selection: new vscode.Range(
        new vscode.Position(line0, 0),
        new vscode.Position(line0, 0),
      ),
    });
  }
});
```

### Pattern 6: package.json Manifest
**What:** The extension manifest declaring all VS Code contributions.
**When to use:** Required for EXT-03 — contributes activitybar, views, commands, configuration.
```json
{
  "name": "nexus",
  "displayName": "Nexus",
  "version": "0.1.0",
  "engines": { "vscode": "^1.74.0" },
  "activationEvents": ["onStartupFinished"],
  "main": "./out/extension.js",
  "contributes": {
    "viewsContainers": {
      "activitybar": [
        { "id": "nexus-sidebar", "title": "Nexus", "icon": "media/nexus.svg" }
      ]
    },
    "views": {
      "nexus-sidebar": [
        { "id": "nexus.sidebar", "name": "Nexus", "type": "webview" }
      ]
    },
    "commands": [
      { "command": "nexus.indexWorkspace", "title": "Nexus: Index Workspace" },
      { "command": "nexus.clearIndex", "title": "Nexus: Clear Index" }
    ],
    "configuration": {
      "title": "Nexus",
      "properties": {
        "nexus.backendUrl": {
          "type": "string",
          "default": "http://localhost:8000",
          "description": "URL of the Nexus backend"
        },
        "nexus.hopDepth": {
          "type": "number",
          "default": 1,
          "description": "Graph traversal hop depth"
        },
        "nexus.maxNodes": {
          "type": "number",
          "default": 10,
          "description": "Maximum context nodes for RAG retrieval"
        }
      }
    }
  }
}
```

### Anti-Patterns to Avoid
- **Fetching from the webview:** The webview CANNOT make `fetch()` calls to `http://localhost:8000`. VS Code's webview CORS policy blocks cross-origin requests. All HTTP must go through the extension host.
- **Using browser `EventSource` for POST:** `EventSource` only supports GET. The `/query` endpoint requires POST with a JSON body. Use `fetch()` + `ReadableStream` instead.
- **Using `*` (star) activation event:** Slows VS Code startup. Use `onStartupFinished` which fires after startup without blocking it.
- **Bundling `vscode` into the extension host:** The `vscode` module is provided by VS Code at runtime and must be in `external`. Including it in the bundle causes a runtime crash.
- **Using 1-indexed lines directly with VS Code API:** `vscode.Position` is 0-indexed. The backend `line_start`/`line_end` fields are 1-indexed (standard). Subtract 1 when constructing `Position`.
- **Not setting `"type": "webview"` in views contribution:** Without this field, `resolveWebviewView` is never called and the sidebar shows a static empty placeholder.
- **Skipping `retainContextWhenHidden`:** Without this option, the webview React state (chat history) is destroyed when the user switches away from the Nexus panel. Set `retainContextWhenHidden: true` when registering the provider — OR use `vscode.getState()`/`setState()` inside the webview for persistence. For V1, `retainContextWhenHidden: true` is the simpler path.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| SSE line parsing | Custom byte-level parser | `fetch` + `getReader()` + split on `\n\n` | SSE spec is simple but chunk boundaries don't align with event boundaries; buffer accumulation is required |
| Webview HTML injection | String templates with user content | Nonce-based CSP + `asWebviewUri()` | XSS vector if content is ever unsanitized; VS Code CSP enforcement catches violations |
| Theme-aware styling | Hardcoded hex colors | `var(--vscode-*)` CSS variables | Colors auto-update on theme switch; VS Code injects all theme colors into webview `<html>` element |
| Extension host ↔ Webview typing | Any-typed messages | Discriminated union `WebviewMessage` type | Compile-time safety across the message bridge; prevents type drift between sender and receiver |
| File path → line navigation | Custom editor scrolling | `showTextDocument` with `selection` Range | Handles multi-root workspaces, already-open documents, column placement |

**Key insight:** The webview sandbox boundary is the most common source of VS Code extension bugs. All side effects (HTTP, file I/O, VS Code API calls) must live in the extension host. The webview is a pure rendering layer.

---

## Common Pitfalls

### Pitfall 1: CORS Blocking Localhost Fetch from Webview
**What goes wrong:** Developer puts `fetch('http://localhost:8000/query', ...)` in React webview code. The request is blocked by CORS policy — webview origin is `vscode-webview://...` not `localhost`.
**Why it happens:** VS Code webviews are sandboxed with strict CSP. Even though the backend has `allow_origins=["vscode-webview://*"]`, the webview's security model blocks the outbound request before it reaches the backend.
**How to avoid:** All `fetch()` calls must be in extension host TypeScript files (`extension.ts`, `BackendClient.ts`, `SseStream.ts`). Forward results to webview via `postMessage`.
**Warning signs:** Console errors in webview DevTools showing "has been blocked by CORS policy" or "net::ERR_FAILED".

### Pitfall 2: resolveWebviewView Never Called
**What goes wrong:** Provider is registered, icon appears in activity bar, but sidebar never renders — `resolveWebviewView` is never invoked.
**Why it happens:** The `views` contribution in `package.json` is missing `"type": "webview"`. Without it, VS Code treats the view as a TreeView container.
**How to avoid:** Always include `"type": "webview"` in the view contribution definition.
**Warning signs:** Empty panel with no content and no errors in extension output.

### Pitfall 3: 0-indexed vs 1-indexed Line Numbers
**What goes wrong:** Citation chip click opens the file at the wrong line (one line off).
**Why it happens:** The backend `CodeNode.line_start` is 1-indexed (Python AST convention). `vscode.Position` constructor takes 0-indexed line numbers.
**How to avoid:** Always subtract 1: `new vscode.Position(lineStart - 1, 0)`.
**Warning signs:** Citations consistently point to the line before the intended symbol.

### Pitfall 4: React State Lost When Sidebar Hidden
**What goes wrong:** User switches to a different VS Code panel; returns to Nexus; all chat history is gone.
**Why it happens:** By default, webview content is destroyed when hidden and recreated when shown. React state does not persist.
**How to avoid:** Set `retainContextWhenHidden: true` in `registerWebviewViewProvider` options. This keeps the webview alive in background (memory cost is acceptable for a chat UI).
**Warning signs:** Chat messages disappear whenever sidebar loses focus.

### Pitfall 5: SSE Chunk Boundary Misalignment
**What goes wrong:** JSON parse errors when reading SSE data — `SyntaxError: Unexpected end of JSON input`.
**Why it happens:** `reader.read()` returns arbitrary byte chunks that do not align with SSE event boundaries (`\n\n`). A single `read()` call may contain part of an event or multiple events.
**How to avoid:** Accumulate chunks in a buffer string; split on `\n\n`; only process complete events; keep the last incomplete chunk in the buffer for the next iteration.
**Warning signs:** Intermittent JSON parse errors; some tokens appear corrupted.

### Pitfall 6: Extension Not Activating on Workspace Open
**What goes wrong:** User opens VS Code with a workspace folder, but `IndexerService.indexWorkspace()` is never called.
**Why it happens:** Using `onView:nexus.sidebar` activation event — extension only activates when the user manually opens the Nexus panel.
**How to avoid:** Use `onStartupFinished` activation event so the extension activates at VS Code startup regardless of which panel is open. Then check `vscode.workspace.workspaceFolders` in `activate()` and auto-trigger indexing.
**Warning signs:** Status bar shows "Not indexed" even though the backend is running.

### Pitfall 7: esbuild Not Externalizing `vscode`
**What goes wrong:** Runtime crash — `Cannot find module 'vscode'` — when the extension activates.
**Why it happens:** `vscode` is not an npm package on disk; VS Code injects it at runtime. If bundled, esbuild tries to include it and fails or creates a broken bundle.
**How to avoid:** Always set `external: ['vscode']` in the extension host esbuild config.
**Warning signs:** Extension activation fails with module resolution error.

---

## Code Examples

Verified patterns from official sources:

### Activation and Registration (extension.ts)
```typescript
// Source: https://code.visualstudio.com/api/references/vscode-api
import * as vscode from 'vscode';
import { SidebarProvider } from './SidebarProvider';

export function activate(context: vscode.ExtensionContext) {
  const provider = new SidebarProvider(context.extensionUri);

  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(
      SidebarProvider.viewType, // 'nexus.sidebar'
      provider,
      { webviewOptions: { retainContextWhenHidden: true } }
    )
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('nexus.indexWorkspace', () => {
      provider.triggerIndex();
    }),
    vscode.commands.registerCommand('nexus.clearIndex', () => {
      provider.triggerClear();
    })
  );

  // EXT-04: auto-index on workspace open
  if (vscode.workspace.workspaceFolders?.length) {
    provider.triggerIndex();
  }
}

export function deactivate() {}
```

### React 18 Webview Entry (webview/index.tsx)
```typescript
// Source: https://www.kenmuse.com/blog/using-react-in-vs-code-webviews/ (verified 2024)
import React from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';

const container = document.getElementById('root')!;
const root = createRoot(container);
root.render(<App />);
```

### SSE Stream Consumer (SseStream.ts)
```typescript
// Source: https://www.putzisan.com/articles/server-sent-events-via-native-fetch (verified pattern)
import * as vscode from 'vscode';

export async function streamQuery(
  question: string,
  repoPath: string,
  webview: vscode.Webview,
  backendUrl: string
): Promise<void> {
  const config = vscode.workspace.getConfiguration('nexus');
  const maxNodes = config.get<number>('maxNodes', 10);
  const hopDepth = config.get<number>('hopDepth', 1);

  const response = await fetch(`${backendUrl}/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      question,
      repo_path: repoPath,
      max_nodes: maxNodes,
      hop_depth: hopDepth,
    }),
  });

  if (!response.ok || !response.body) {
    webview.postMessage({ type: 'error', message: `Backend error: ${response.status}` });
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const parts = buffer.split('\n\n');
      buffer = parts.pop() ?? '';

      for (const part of parts) {
        const lines = part.split('\n');
        const eventLine = lines.find(l => l.startsWith('event: '));
        const dataLine = lines.find(l => l.startsWith('data: '));
        if (!eventLine || !dataLine) continue;

        const eventType = eventLine.slice(7).trim();
        try {
          const data = JSON.parse(dataLine.slice(6));
          webview.postMessage({ type: eventType, ...data });
        } catch {
          // skip malformed event
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
```

### Backend HTTP Polling (BackendClient.ts)
```typescript
// Source: VS Code API patterns; fetch built-in Node.js 18+
export class BackendClient {
  constructor(private readonly backendUrl: string) {}

  async startIndex(repoPath: string): Promise<void> {
    await fetch(`${this.backendUrl}/index`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repo_path: repoPath }),
    });
  }

  async pollUntilComplete(
    repoPath: string,
    onProgress: (status: IndexStatus) => void
  ): Promise<IndexStatus> {
    return new Promise((resolve, reject) => {
      const interval = setInterval(async () => {
        try {
          const res = await fetch(
            `${this.backendUrl}/index/status?repo_path=${encodeURIComponent(repoPath)}`
          );
          const status: IndexStatus = await res.json();
          onProgress(status);
          if (status.status === 'complete' || status.status === 'failed') {
            clearInterval(interval);
            resolve(status);
          }
        } catch (e) {
          clearInterval(interval);
          reject(e);
        }
      }, 2000); // SSE-01: poll every 2 seconds
    });
  }
}
```

### VS Code CSS Variables Usage (index.css)
```css
/* Source: https://code.visualstudio.com/api/extension-guides/webview */
/* No external framework — CHAT-05 compliance */

.chat-message-user {
  background: var(--vscode-input-background);
  color: var(--vscode-input-foreground);
  border-radius: 4px;
  padding: 8px 12px;
}

.chat-message-assistant {
  background: var(--vscode-editor-background);
  color: var(--vscode-editor-foreground);
  border: 1px solid var(--vscode-panel-border);
  border-radius: 4px;
  padding: 8px 12px;
}

.citation-chip {
  display: inline-block;
  background: var(--vscode-badge-background);
  color: var(--vscode-badge-foreground);
  border-radius: 3px;
  padding: 2px 6px;
  font-family: var(--vscode-editor-font-family);
  font-size: var(--vscode-editor-font-size);
  cursor: pointer;
  margin: 2px;
}

.citation-chip:hover {
  background: var(--vscode-list-hoverBackground);
}

.status-bar-text {
  color: var(--vscode-statusBar-foreground);
}
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| webpack for extension bundling | esbuild (recommended) | ~2022 | 50x faster builds; simpler config |
| `onView` activation event required | Views auto-activate without `onView` | VS Code 1.74 (Nov 2022) | Cleaner `package.json`; still use `onStartupFinished` for auto-indexing |
| `vscode.createWebviewPanel` for sidebars | `WebviewViewProvider` for sidebar | ~1.49 | Proper sidebar integration vs floating panel |
| React 17 `ReactDOM.render` | React 18 `createRoot` | React 18 (Mar 2022) | Concurrent rendering; `ReactDOM.render` deprecated |
| `EventSource` for SSE | `fetch` + `ReadableStream` | Node.js 18 (2022) | GET-only limitation removed; POST SSE supported |

**Deprecated/outdated:**
- `vscode-resource:` URI scheme: replaced by `webview.asWebviewUri()` since VS Code 1.48
- `ReactDOM.render()`: deprecated in React 18, use `createRoot`
- `onView:` activation event as the only option: not required since 1.74 for contributed views

---

## Open Questions

1. **Backend CORS for localhost fetch from extension host**
   - What we know: The backend (`API-07`) already allows `vscode-webview://*` and `http://localhost:3000`. Extension host `fetch()` does not send an `Origin` header (it's Node.js, not a browser).
   - What's unclear: Whether the FastAPI backend needs any additional CORS configuration for extension host fetch calls (probably not — CORS is a browser mechanism).
   - Recommendation: Test a simple `fetch` from the extension host in development. If blocked, check that FastAPI `CORSMiddleware` allows `*` for non-browser origins (it should by default).

2. **`file_path` in CodeNode — absolute path reliability**
   - What we know: `CodeNode.file_path` is described as "absolute path to source file" in `schemas.py`. The backend indexes `repo_path` as provided by the extension.
   - What's unclear: If the extension sends `workspaceFolders[0].uri.fsPath` as `repo_path`, and the backend stores absolute paths, the citation `file_path` values should be directly usable with `vscode.Uri.file()`. This assumption needs verification during implementation.
   - Recommendation: In `BackendClient.startIndex`, send `repoPath = workspaceFolders[0].uri.fsPath`. Trust that `file_path` in citations is absolute and valid.

3. **Status bar vs. webview status display**
   - What we know: CHAT-04 requires index status bar ("Indexing... spinner / Ready — N nodes / Not indexed") as part of the webview, while STATUS BAR items are VS Code chrome (not webview).
   - What's unclear: Whether "status bar" in CHAT-04 means the VS Code status bar (bottom chrome) or an in-webview status indicator.
   - Recommendation: Implement both: a VS Code `StatusBarItem` in the bottom chrome for global visibility, AND an in-webview status header for inline context. This exceeds the requirement without risk.

---

## Sources

### Primary (HIGH confidence)
- `https://code.visualstudio.com/api/extension-guides/webview` — WebviewViewProvider, CSP, postMessage, asWebviewUri, retainContextWhenHidden
- `https://code.visualstudio.com/api/references/vscode-api` — API signatures for registerWebviewViewProvider, showTextDocument, createStatusBarItem, workspaceFolders, registerCommand
- `https://code.visualstudio.com/api/references/contribution-points` — package.json viewsContainers, views, commands, configuration schema
- `https://code.visualstudio.com/api/references/activation-events` — onStartupFinished, onView, workspaceContains descriptions
- `https://code.visualstudio.com/api/working-with-extensions/bundling-extension` — esbuild recommendation, vscode external requirement

### Secondary (MEDIUM confidence)
- `https://www.kenmuse.com/blog/using-react-in-vs-code-webviews/` (Oct 2024) — dual esbuild entry points, React 18 webview pattern, CSP nonce
- `https://www.putzisan.com/articles/server-sent-events-via-native-fetch` — fetch + ReadableStream SSE consumption pattern
- `https://github.com/microsoft/vscode/issues/102959` — confirmed CORS restriction for webview localhost fetch
- Multiple WebSearch results confirming: webview cannot fetch localhost; extension host must proxy all HTTP

### Tertiary (LOW confidence)
- WebSearch community findings on `retainContextWhenHidden` behavior — matches official docs description but not directly cited from official source

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — VS Code API is stable; esbuild recommendation from official docs; React 18 `createRoot` is the current standard
- Architecture: HIGH — Two-context model (extension host vs webview) is the fundamental VS Code constraint; CORS behavior verified via multiple official GitHub issues
- SSE parsing: MEDIUM — fetch + ReadableStream pattern verified from official Node.js docs and community sources; specific SSE line-parsing logic is standard but not from a single authoritative source
- Pitfalls: HIGH — Most pitfalls (CORS, 0-indexed lines, missing type:webview, vscode external) confirmed from official docs or official GitHub issues

**Research date:** 2026-03-19
**Valid until:** 2026-04-19 (VS Code API is stable; 30-day window appropriate)
