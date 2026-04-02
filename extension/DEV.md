# VS Code Extension — Developer Guide

Sidebar chat interface for querying code, viewing results, and managing the index. Runs in two isolated environments: **extension host** (Node.js, VS Code API) and **webview** (React, UI).

## Setup for Development

**Prerequisites:** Node.js 20+ · VS Code 1.74+ · Python 3.11+ (for running the backend locally)

Full backend setup → [root README Option B](../README.md#option-b----run-locally-development).

Quick steps:

```bash
# 1. Start the backend (terminal 1)
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # add your API key
uvicorn app.main:app --reload --port 8000

# 2. Build the extension (terminal 2)
cd extension
npm install && npm run build

# 3. Launch Extension Development Host
#    Open extension/ in VS Code, then press F5
#    In the new window, open your target repo as the workspace
```

> **Dev-mode passthrough:** SidecarManager checks if port 8000 is already bound at startup. If it is, it skips the binary download and spawn entirely — your local `uvicorn` process is used instead. No binary needed for backend development.

## Architecture

```
Extension Host (Node.js)
  ├── extension.ts       activate, register commands, wire FileWatcher + ConfigManager
  ├── SidecarManager     download (first use) + spawn/kill/poll backend binary; auto-restart on exit; dev-mode skip
  ├── ConfigManager      VS Code settings → POST /api/config; SecretStorage API keys
  ├── SidebarProvider    webview bridge — message dispatcher, SSE listener
  ├── BackendClient      HTTP: POST /index · GET /status · POST /query
  ├── SseStream          SSE parser → postMessage events to webview
  ├── FileWatcher        debounce 2s on file save → incremental re-index + activity log
  └── HighlightService   citation decorations in the editor
          │
          │  postMessage / onDidReceiveMessage
          ▼
Webview (React 18)
  └── App.tsx            chat history, intent pills, result panels, citation viewer
          │
          │  HTTP + SSE
          ▼
  FastAPI Backend (dynamically allocated port — managed by SidecarManager)
```

## Source Layout

```
src/
├── extension.ts          Entry point — activate(), deactivate(), command registration
├── SidecarManager.ts     Binary lifecycle: download → verify SHA256 → extract → spawn → keepalive → restart
├── ConfigManager.ts      Reads VS Code settings + SecretStorage; pushes to POST /api/config on change
├── SidebarProvider.ts    Webview host — resolveWebviewView(), message router, SSE orchestration
├── BackendClient.ts      Typed HTTP client for /index, /index/status, /query, /api/health
├── SseStream.ts          Fetch-based SSE reader; emits token / citations / done / error events
├── FileWatcher.ts        vscode.workspace.onDidSaveTextDocument watcher with 2s debounce flush
├── HighlightService.ts   TextEditorDecorationType — applies citation range highlights on done event
├── types.ts              Shared TypeScript interfaces (QueryRequest, CitationEvent, …)
└── webview/
    ├── App.tsx           React root — chat state, intent pills, result panels, citation viewer
    ├── index.tsx         ReactDOM.createRoot entry for the webview bundle
    └── index.css         Webview styles (VS Code CSS variable tokens)
```

Two separate esbuild bundles are produced — `out/extension.js` (Node.js, has access to `vscode` API) and `out/webview/index.js` (browser sandbox, no `vscode` API). Code cannot be shared at runtime between them; communication is only through `postMessage` / `onDidReceiveMessage`.

## Key Flows

**Startup:**
```
Extension activates
  → SidecarManager.start()
      → lockfile present + PID alive + health OK → reuse (no spawn)
      → otherwise → download binary from GitHub Releases if not cached
                  → spawn binary on a free port (detached)
                  → write lockfile {pid, port, version}
                  → proc.on('exit') → deleteLock() + onUnexpectedExit()
  → sidecar.onUnexpectedExit = _restartBackend  (max 5 consecutive failures)
  → keepalive setInterval(30s) → client.ping()
      → alive: clear failure streak
      → dead: _restartBackend()          (covers reuse-path windows)
  → ConfigManager.pushConfig() → POST /api/config (provider, model, API keys)
  → SidebarProvider.broadcastConfigStatus() → webview shows active config
```

**Query:**
```
User submits question
  → webview {type:"query"} → SidebarProvider
    → SseStream → POST /query
      → token events → append to chat
      → citations event → HighlightService decorates editor
      → done event → finalize
```

**Incremental Re-index:**
```
File saved → FileWatcher (debounce 2s)
  → onFlush callback → SidebarProvider.postLog() → Activity panel entry
  → POST /index {changed_files}
    → poll /index/status every 500ms
      → webview shows progress indicator
```

## Intent Modes

| Pill | Result panel |
|---|---|
| Explain | Streaming answer + clickable citations |
| Debug | Suspect list with anomaly scores + diagnosis |
| Review | Findings with severity badges + "Post to PR" button |
| Test | Test code block + copy button + written file path |

## Build

```bash
npm install && npm run build
# → out/extension.js        (host bundle)
# → out/webview/index.js    (React bundle)

# Watch mode (auto-rebuild on save)
npm run watch

# Type-check without emitting
npm run typecheck
```

**Run in Extension Development Host:**
1. Open the `extension/` folder in VS Code
2. Press `F5` — a new Extension Development Host window opens
3. In that window, open your repo as the workspace

**Package a local `.vsix`:**
```bash
npm install -g @vscode/vsce
vsce package --out nexus-local.vsix
# Install: VS Code → Extensions panel → ··· → Install from VSIX…
```

> If you built a local backend binary (`python build.py` from `backend/`), place it in `extension/bin/` before packaging — the local `.vsix` will use it instead of downloading from GitHub Releases.

Settings, commands, and API key management → [README.md](README.md).

> **Dev note:** `ConfigManager` watches for `vscode.workspace.onDidChangeConfiguration` on the `nexus` namespace and calls `pushConfig()` on every change, so settings take effect immediately without a reload. In local dev mode (Option B), the backend `.env` file provides fallback defaults if no key has been set via the extension.

## Binary Cache

The downloaded backend binary is cached at:

```
# macOS
~/Library/Application Support/Code/User/globalStorage/Hafiz408.nexus-ai/backend/<version>/

# Windows
%APPDATA%\Code\User\globalStorage\Hafiz408.nexus-ai\backend\<version>\
```

To force a fresh download (e.g. after changing the binary): delete the `backend/<version>/` directory and reload the window. The lockfile (`backend.lock` in the same `globalStorage` folder) tracks the running process — delete it too if the backend fails to start after a forced cache clear.

## Debugging Tips

**Extension host logs:**
Open `Output` panel → select `Nexus Backend` from the dropdown. All `SidecarManager`, `ConfigManager`, and `SidebarProvider` logs appear here with timestamps.

**Webview DevTools (React panel):**
`Cmd+Shift+P` → `Developer: Open Webview Developer Tools` — opens a Chrome DevTools instance scoped to the sidebar webview. Console, Elements, and Network tabs all work.

**Backend API directly:**
Once the sidecar is running, find its port in the Output panel (`Spawning backend on port XXXXX`) and call endpoints directly:
```bash
curl http://localhost:XXXXX/api/health
curl http://localhost:XXXXX/api/config/status
```

For backend internals, tests, and the retrieval pipeline → [backend/README.md](../backend/README.md).
