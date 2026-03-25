# VS Code Extension

The Nexus VS Code extension provides a sidebar chat interface for querying code, viewing results, and managing the repository index. It runs in two isolated environments: the extension host (Node.js) handles VS Code API calls and backend communication, while the webview (React) renders the UI.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│  Extension Host (Node.js, Single-threaded)              │
│                                                         │
│  ┌──────────────┐  ┌─────────────────┐  ┌────────────┐ │
│  │extension.ts  │  │SidebarProvider  │  │FileWatcher │ │
│  │              │  │                 │  │(incremental│ │
│  │• activate()  │  │• webview msgs   │  │ re-index)  │ │
│  │• commands    │  │• SSE listening  │  │            │ │
│  │• FileWatcher │  │• highlighting   │  └────────────┘ │
│  └──────┬───────┘  └────────┬────────┘                 │
│         │                   │                           │
│         │          ┌────────┴───────────┐              │
│         │          │                    │              │
│         │    ┌──────────────────┐  ┌────────────────┐  │
│         │    │ SseStream.ts     │  │BackendClient   │  │
│         │    │ SSE event parser │  │HTTP /index /q  │  │
│         │    │ + assembler      │  │                │  │
│         │    └────────┬─────────┘  └────────────────┘  │
│         │             │                                 │
│         │             └─────────────┬───────────────────┤
│         │                           │                   │
│         │ postMessage({type, data}) │ (events from SSE) │
├─────────┼───────────────────────────┼───────────────────┤
│  Bridge (message passing)                               │
├─────────┼───────────────────────────┼───────────────────┤
│         │   onDidReceiveMessage({type, data})           │
│         ↓                           ↓                   │
│  ┌────────────────────────────────────────────────────┐ │
│  │ Webview (Isolated Context, React 18)              │ │
│  │                                                    │ │
│  │  ┌──────────────────────────────────────────────┐ │ │
│  │  │ App.tsx                                      │ │ │
│  │  │ • Chat message history                       │ │ │
│  │  │ • Intent pills (auto, explain, debug, etc.)  │ │ │
│  │  │ • Result panels (findings, test code, etc.)  │ │ │
│  │  │ • File/citation viewer                       │ │ │
│  │  └──────────────────────────────────────────────┘ │ │
│  │                      ↕ useState updates            │ │
│  │  ┌──────────────────────────────────────────────┐ │ │
│  │  │ HighlightService (decorations via postMsg)  │ │ │
│  │  └──────────────────────────────────────────────┘ │ │
│  └────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
                         ↓ HTTP
              ┌──────────────────────┐
              │   Backend (FastAPI)  │
              │ /index, /query (SSE) │
              └──────────────────────┘
```

---

## File Breakdown

### Extension Host

**`extension.ts`** — Activation & Commands

- **Lifecycle:** `activate(context: ExtensionContext)` called on extension load (or onStartupFinished)
- **OneBackendClient:** Created once, shared between SidebarProvider and FileWatcher
- **Providers:** Register WebviewViewProvider (nexus.sidebar)
- **Commands:**
  - `nexus.indexWorkspace` — Trigger full re-index
  - `nexus.clearIndex` — Delete repo data
- **FileWatcher:** Auto re-index on file save (WATCH-01/02)

**`BackendClient.ts`** — HTTP Client

- **Constructor:** Takes backend URL from VS Code settings (`nexus.backendUrl`)
- **Methods:**
  - `startIndex(repoPath, languages, changedFiles?)` → POST /index
  - `getIndexStatus(repoPath)` → GET /index/status?repo_path=...
  - `clearIndex(repoPath)` → DELETE /index?repo_path=...
- **Error handling:** Throws on network errors; caller must handle

**`SidebarProvider.ts`** — WebviewViewProvider

- **Role:** Bridge between VS Code API (host) and webview (React)
- **onDidReceiveMessage:** Dispatcher for all webview → host messages
  - `query` — SSE stream answer via streamQuery()
  - `openFile` — Open file at cited line (CHAT-03)
  - `indexWorkspace` — Trigger indexing
  - `clearIndex` — Clear repo data
  - `postReviewToPR` — (Phase 27+) GitHub integration
- **postMessage:** Send data to webview (updates, highlights, status)
- **HighlightService:** Manages citation decorations (HIGH-02)

**`SseStream.ts`** — SSE Event Handler

- **Function:** `streamQuery(question, repo_path, webview, backendUrl, onCitations, intent_hint)`
- **Algorithm:**
  1. POST /query (returns fetch Response with ReadableStream)
  2. Decode SSE events (text/event-stream MIME type)
  3. Parse `event: type` and `data: JSON` fields
  4. Emit events to webview via postMessage
  5. Collect citations; call onCitations callback
- **Error handling:** Catches and emits `error` events

**`FileWatcher.ts`** — Incremental Re-Indexing

- **Trigger:** File save via vscode.workspace.onDidSaveTextDocument
- **Debounce:** 2 seconds (WATCH-02)
- **Logic:**
  1. Track changed file paths (relative to repo root)
  2. Debounce timer resets on each save
  3. When timer fires: POST /index with changed_files list
  4. Backend handles incremental re-parse + upsert
- **Filtering:** Only trigger for .py, .ts, .tsx, .js, .jsx files

**`HighlightService.ts`** — Citation Decorations

- **Input:** Citations (node_id, file_path, line_start, line_end)
- **Output:** Editor.TextEditorDecorationType with background color
- **Lifecycle:**
  - clearHighlights() — remove all decorations
  - highlightCitations(citations) — apply new decorations
- **Color:** Defined via VS Code theme colors (scoped decoration)

---

### Webview (React)

**`App.tsx`** — Main UI Component

**State:**
```typescript
const [messages, setMessages] = useState<Message[]>([])
const [query, setQuery] = useState("")
const [intent, setIntent] = useState("auto")
const [indexStatus, setIndexStatus] = useState<IndexStatus | null>(null)
const [result, setResult] = useState<any>(null)
const [loading, setLoading] = useState(false)
```

**Message Types:**
- User message (question) + timestamp
- Assistant message (assistant response) + citations
- Status update (indexing progress)
- Result panel (structured output: findings, test code, etc.)

**Features:**
- Chat history (ephemeral, lost on refresh)
- Intent pills: Auto | Explain | Debug | Review | Test
- Result panels (dynamic based on intent)
- Citation viewer with file + line range
- Index status indicator (running/complete/failed)
- Copy-to-clipboard (fallback for test code if file write fails)

**Lifecycle Hooks:**
- **useEffect (onMessage listener):** Listen for postMessage events from host
- **onSubmit:** Send query via postMessage to host
- **onOpenFile:** Request host to open editor (CHAT-03)
- **onCopyText:** Copy result to clipboard

---

### Type System

**`types.ts`** — Message Contracts

```typescript
// Host → Webview
interface HostToWebviewMessage {
  type: "token" | "citations" | "done" | "error" | "status" | "result"
  content?: string
  citations?: Citation[]
  retrieval_stats?: object
  message?: string
  status?: IndexStatus
  intent?: string
  result?: any
  has_github_token?: boolean
  file_written?: boolean
  written_path?: string | null
}

// Webview → Host
interface WebviewToHostMessage {
  type: "query" | "openFile" | "indexWorkspace" | "clearIndex" | "postReviewToPR"
  question?: string
  intent_hint?: string
  filePath?: string
  lineStart?: number
  findings?: any[]
  repo?: string
  pr_number?: number | null
}
```

---

## Message Flow Examples

### Query + V1 Response (Token Streaming)

```
Webview:
  send { type: "query", question: "...", intent_hint: null }

Host (SidebarProvider):
  ← webview message
  → streamQuery(question, repo_path, webview, backendUrl, ...)
    ↓
  Backend POST /query (SSE stream)
    ↓
  SseStream.ts parses events:
    event: token, data: {"type": "token", "content": "The "}
    → postMessage to webview
    event: citations
    → collect, onCitations() → highlight
    event: done
    → final message

Webview:
  onMessage("token") → append to messages
  onMessage("citations") → request highlights
  onMessage("done") → mark complete
```

### Query + V2 Response (Structured Result)

```
Webview:
  send { type: "query", question: "...", intent_hint: "debug" }

Host (SidebarProvider):
  ← webview message
  → streamQuery(question, repo_path, webview, backendUrl, ..., "debug")
    ↓
  Backend POST /query + intent_hint="debug" (V2 path)
    ↓
  SseStream.ts parses events:
    event: result, data: {
      "type": "result",
      "intent": "debug",
      "result": { "suspects": [...], "diagnosis": "..." },
      "has_github_token": false,
      "file_written": false
    }
    → postMessage to webview
    event: done
    → final message

Webview:
  onMessage("result") → setResult, render DebugPanel
  onMessage("done") → mark complete
  Show "Post to PR" button if has_github_token=true
```

### File Watcher (Incremental Re-Index)

```
User saves file.py

FileWatcher:
  ← onDidSaveTextDocument event
  → debounce timer starts (2s)

User saves another file (within 2s):
  → timer resets

After 2s idle:
  → POST /index with changed_files: [file1.py, file2.py, ...]
    ↓
  Backend: incremental re-parse + upsert

Host (SidebarProvider):
  Poll /index/status every 500ms
  ← receive status updates
  → postMessage({type: "status", ...}) to webview

Webview:
  onMessage("status") → setIndexStatus, show progress
```

### Citation Highlighting

```
Backend SSE:
  event: citations
  data: {
    "citations": [
      {"node_id": "file.py::func", "file_path": "/abs/path/file.py", "line_start": 42, "line_end": 55, ...}
    ]
  }

Host (SseStream):
  ← parse citations
  → onCitations(citations) callback

Host (SidebarProvider):
  → highlightCitations(citations)
    ↓
  HighlightService:
    → open editors, apply decorations
    ↓
  User sees highlighted range in editor
```

---

## Configuration

**VS Code Settings (`.vscode/settings.json`):**

```json
{
  "nexus.backendUrl": "http://localhost:8000",
  "nexus.hopDepth": 1,
  "nexus.maxNodes": 10
}
```

These are read by `extension.ts` and passed to queries:

```typescript
const config = vscode.workspace.getConfiguration("nexus")
const backendUrl = config.get<string>("backendUrl", "http://localhost:8000")
const maxNodes = config.get<number>("maxNodes", 10)
const hopDepth = config.get<number>("hopDepth", 1)
```

---

## Build & Distribution

**Build Process:**

```bash
npm install
npm run build  # → esbuild with dual bundles
```

**Dual Bundles (esbuild.js):**

1. **Extension host bundle:** `out/extension.js`
   - Bundled from extension.ts (node target)
   - Includes: BackendClient, SidebarProvider, FileWatcher, SseStream, HighlightService
   - External: vscode (doesn't bundle)

2. **Webview bundle:** `out/webview/index.js`
   - Bundled from webview/index.tsx (browser target)
   - Includes: React 18, App.tsx, index.css
   - External: VS Code API (webview bridge)

**Distribution:**

- Load unpacked: `code --install-extension <path>`
- Pre-built .vsix: `npm run package` (requires vsce)
- VS Code Marketplace: Submit .vsix

---

## UI/UX Design

**Sidebar Layout:**

```
┌─────────────────────────┐
│ Index: /path/to/repo    │  ← Status bar
├─────────────────────────┤
│ [Auto] [Explain] [Debug]│  ← Intent pills
│ [Review] [Test]         │
├─────────────────────────┤
│ Q: How does auth work?  │  ← Chat message
│ ————————————————         │
│ A: The middleware...    │  ← Assistant response (highlighted citations)
│ ————————————————         │
│ [file.py:45–67]         │  ← Citation chip (clickable)
├─────────────────────────┤
│ [Input: "New question"] │  ← Query input
├─────────────────────────┤
│ [Index] [Clear]         │  ← Action buttons
└─────────────────────────┘
```

**Result Panels (Intent-specific):**

- **Explain:** Answer text + citations
- **Debug:** Suspect list with anomaly scores + diagnosis
- **Review:** Findings with severity badges + suggestions
- **Test:** Test code (copy button) + test file path

**CSS:**

- VS Code CSS variables (colors, fonts)
- No Tailwind (keep bundle size minimal)
- Light/dark theme support

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Backend offline | Error message in chat, retry button |
| Repository not indexed | Status message, "Index Workspace" button |
| SSE parse error | Error event, logged to console |
| File not accessible | openFile fails gracefully, error toast |
| Network timeout | Timeout error, retry option |

---

## Performance Optimizations

1. **Message debouncing:** FileWatcher uses 2s debounce to batch file saves
2. **Citation caching:** Highlight service caches open editors
3. **Webview context retention:** `retainContextWhenHidden: true` keeps React state alive when sidebar is hidden
4. **Graph cache (host):** Backend graph cached in `app.state.graph_cache` per repo

---

## Testing

Extension testing is limited due to VS Code API sandboxing:

- No unit tests for host code (VS Code API mocking is complex)
- Webview can be tested with React testing library (not included in current setup)
- Manual testing: F5 in VS Code to open Extension Development Host

---

## Debugging

**Host (extension.ts):**

```bash
# In Extension Development Host:
F5 → opens new VS Code window with extension
Ctrl+Shift+D → Debug Console
```

**Webview (App.tsx):**

```bash
# In webview iframe:
Ctrl+Shift+P → "Developer: Open Webview Developer Tools"
console.log() messages appear in webview console
```

---

## Known Limitations

1. **Chat history is ephemeral** — lost on reload or sidebar hide/show
2. **No multi-turn conversations** — each query is independent (Phase 27+ work)
3. **No command history** — users must re-type previous queries
4. **Single workspace folder** — uses workspace[0] only (multi-folder support future work)

---

## Future Work (Phase 27+)

- [ ] Persistent chat history (localStorage or backend)
- [ ] Multi-turn agent conversations
- [ ] Streaming test code + results (don't wait for full result)
- [ ] GitHub PR integration (show open PRs, post findings)
- [ ] Code execution (run generated tests directly in extension)
- [ ] Multi-folder workspace support
- [ ] Custom color themes for result panels
- [ ] Query bookmarks / saved conversations
