# VS Code Extension

Sidebar chat interface for querying code, viewing results, and managing the index. Runs in two isolated environments: **extension host** (Node.js, VS Code API) and **webview** (React, UI).

## Architecture

```
Extension Host (Node.js)
  ├── extension.ts       activate, register commands, wire FileWatcher
  ├── SidebarProvider    webview bridge — message dispatcher, SSE listener
  ├── BackendClient      HTTP: POST /index · GET /status · POST /query
  ├── SseStream          SSE parser → postMessage events to webview
  ├── FileWatcher        debounce 2s on file save → incremental re-index
  └── HighlightService   citation decorations in the editor
          │
          │  postMessage / onDidReceiveMessage
          ▼
Webview (React 18)
  └── App.tsx            chat history, intent pills, result panels, citation viewer
          │
          │  HTTP + SSE
          ▼
  FastAPI Backend (localhost:8000)
```

## Key Flows

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
  → POST /index {changed_files}
    → poll /index/status every 500ms
      → webview shows progress indicator
```

## Intent Modes

| Pill | Result panel |
|---|---|
| Auto | Routes automatically |
| Explain | Streaming answer + clickable citations |
| Debug | Suspect list with anomaly scores + diagnosis |
| Review | Findings with severity badges + "Post to PR" button |
| Test | Test code block + copy button + written file path |

## Build

```bash
npm install && npm run build
# → out/extension.js  (host bundle)
# → out/webview/index.js  (React bundle)
```

Load unpacked in VS Code from `./out/`, or package with `npm run package`.

## Settings

```json
{
  "nexus.backendUrl": "http://localhost:8000",
  "nexus.hopDepth": 1,
  "nexus.maxNodes": 10
}
```
