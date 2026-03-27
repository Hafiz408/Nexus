# VS Code Extension

Sidebar chat interface for querying code, viewing results, and managing the index. Runs in two isolated environments: **extension host** (Node.js, VS Code API) and **webview** (React, UI).

## Architecture

```
Extension Host (Node.js)
  ├── extension.ts       activate, register commands, wire FileWatcher + ConfigManager
  ├── SidecarManager     spawn/kill/poll bundled backend binary; dev-mode skip
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
  FastAPI Backend (localhost:8000)
```

## Key Flows

**Startup:**
```
Extension activates
  → SidecarManager checks port 8000
      → port free: spawn bundled binary, poll /api/health until ready
      → port occupied: skip spawn (dev mode — Docker backend already running)
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
| Auto | Routes automatically |
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
```

**Run in Extension Development Host:**
1. Open the `extension/` folder in VS Code
2. Press `F5` — a new Extension Development Host window opens
3. In that window, open your repo as the workspace

## Settings

| Setting | Default | Description |
|---|---|---|
| `nexus.chatProvider` | `mistral` | LLM provider for chat |
| `nexus.chatModel` | `mistral-small-latest` | Chat model name |
| `nexus.embeddingProvider` | `mistral` | Embedding provider |
| `nexus.embeddingModel` | `mistral-embed` | Embedding model name |
| `nexus.backendUrl` | `http://localhost:8000` | Backend URL |
| `nexus.hopDepth` | `1` | Graph traversal hop depth |
| `nexus.maxNodes` | `10` | Max context nodes for RAG |
| `nexus.ollamaBaseUrl` | `http://localhost:11434` | Ollama base URL |

## API Key Management

Keys are stored in VS Code's `SecretStorage` (OS keychain) — never in settings files.

```
Cmd+Shift+P → "Nexus: Set API Key"   → pick provider → enter key
Cmd+Shift+P → "Nexus: Clear API Key" → pick provider → removes key
```

On activation and on settings change, the extension pushes provider + key config to `POST /api/config`. The `.env` file provides fallback defaults if no key has been set via the extension.
