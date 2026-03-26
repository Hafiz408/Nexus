# Nexus — Graph-Grounded Code Intelligence

AI-powered code assistant that understands your codebase through a **call graph + vector index**. Ask questions in plain English; get grounded, citation-backed answers with file/line references — streamed live in VS Code.

> **Local-first & privacy-preserving.** No database server required. The graph and vector index live in `.nexus/graph.db` inside your workspace — your code never leaves your machine.

## Features

| Mode | What it does |
|---|---|
| **Explain** | Semantic + graph-aware retrieval; streams tokens with clickable file citations |
| **Debug** | BFS call-graph traversal, anomaly scoring, ranked suspect list with diagnosis |
| **Review** | Structured findings (severity · category · suggestion), postable to GitHub PRs |
| **Test** | Framework-aware test generation written directly to your repo |
| **Auto** | LLM classifies intent and routes to the right specialist automatically |

## Architecture

```
┌──────────────────────────────────────┐
│         VS Code Extension            │
│  Sidebar UI · FileWatcher · SSE      │
│  SidecarManager (auto-starts backend)│
└──────────────────┬───────────────────┘
                   │ HTTP + SSE  (+ db_path per request)
                   ▼
┌──────────────────────────────────────┐
│     FastAPI Backend  (stateless)     │
│                                      │
│  Ingestion ──► Graph + Vectors       │
│                     │                │
│  Query ──► Retrieval ──► Agents      │
│                     │                │
│            MCP Tools (PR · files)    │
└──────────┬───────────────────────────┘
           │
  ┌────────┴──────────────────────┐
  │ SQLite  (sqlite-vec)          │
  │ .nexus/graph.db per workspace │
  │ graph · FTS · vector index    │
  └───────────────────────────────┘
```

The backend is **stateless compute** — it receives a `db_path` with every request pointing to the workspace SQLite file. No shared database, no server to manage.

The extension **automatically spawns** the bundled backend binary on activate and shuts it down on deactivate. No Python installation required.

## Query Flow

```
Question
  │
  ├─ Embed → sqlite-vec cosine search (top-k seeds)
  ├─ BFS expand via call graph (callers + callees)
  ├─ Rerank: semantic + 0.2×PageRank + 0.1×in-degree
  │
  └─ intent = explain?  → stream tokens → file citations
     intent = debug/review/test?
       → Specialist agent
           → Critic (score = 0.4G + 0.35R + 0.25A)
               └── score < 0.7 → retry (max 2×)
```

## Installation

### Option A — Download from GitHub Actions (latest build)

1. Go to [Actions](https://github.com/Hafiz408/Nexus/actions) → latest **Build and Package Nexus** run
2. Download the `nexus-vsix` artifact
3. In VS Code: `Extensions` → `...` → `Install from VSIX…` → select `nexus.vsix`

> Artifacts are retained for 90 days. For permanent releases, see the [Releases](https://github.com/Hafiz408/Nexus/releases) page.

### Option B — Build from source

**Prerequisites:** VS Code 1.74+ · Node.js 20+ · Python 3.11+

```bash
# 1. Build backend binary
cd backend
pip install -r requirements.txt pyinstaller
python build.py           # outputs extension/bin/nexus-backend-mac (or .exe on Windows)

# 2. Build and install extension
cd extension
npm install && npm run compile
npm install -g @vscode/vsce
vsce package --out nexus.vsix
# VS Code: install nexus.vsix, or press F5 in extension/ for dev mode
```

## Configuration

No `.env` file or Docker setup needed. Everything is configured inside VS Code:

1. **Set your API key** — `Cmd+Shift+P` → `Nexus: Set API Key` → pick provider → enter key
   - Keys are stored in VS Code `SecretStorage` and never written to disk
2. **Choose provider/model** — `Code > Settings > Extensions > Nexus`
   - Chat provider: `openai` | `mistral` | `anthropic` | `ollama` | `gemini`
   - Embedding provider: `openai` | `mistral` | `ollama` | `gemini`
   - Custom Ollama base URL (default: `http://localhost:11434`)
3. **Index your workspace** — `Cmd+Shift+P` → `Nexus: Index Workspace`
   - Creates `.nexus/graph.db` in your workspace (git-ignored by default)
   - Chat is disabled until the first index completes

The extension pushes provider/model/key config to the backend at startup and on every settings change.

> **Changing embedding provider or model** requires a reindex — the sidebar will warn you and disable chat until reindexing is complete.

## CI / Build Pipeline

Every push to a `v*` tag triggers **GitHub Actions** (`.github/workflows/build.yml`):

| Job | Runner | Output |
|---|---|---|
| `build-mac` | `macos-latest` | `nexus-backend-mac` binary via PyInstaller |
| `build-win` | `windows-latest` | `nexus-backend-win.exe` binary via PyInstaller |
| `package` | `ubuntu-latest` | `nexus.vsix` bundling both binaries |

The final `.vsix` works on Mac and Windows with no Python installation required.

## Structure

```
nexus/
├── backend/           → FastAPI service
│   ├── build.py       → PyInstaller build script
│   └── app/
│       ├── api/       → HTTP endpoints + SSE routing
│       ├── ingestion/ → AST parsing, graph, sqlite-vec index
│       ├── retrieval/ → 3-step Graph RAG pipeline
│       ├── agent/     → Multi-agent orchestration
│       ├── core/      → Provider-agnostic model factory
│       └── mcp/       → GitHub PR + file-write tools
├── extension/         → VS Code extension (TypeScript + React)
│   └── bin/           → Bundled backend binaries (mac + win)
├── eval/              → RAGAS evaluation suite
└── .github/workflows/ → CI build pipeline
```

## Docs

| Area | |
|---|---|
| Backend | [backend/README.md](backend/README.md) |
| Ingestion | [backend/app/ingestion/README.md](backend/app/ingestion/README.md) |
| Retrieval | [backend/app/retrieval/README.md](backend/app/retrieval/README.md) |
| Agents | [backend/app/agent/README.md](backend/app/agent/README.md) |
| API | [backend/app/api/README.md](backend/app/api/README.md) |
| MCP Tools | [backend/app/mcp/README.md](backend/app/mcp/README.md) |
| Extension | [extension/README.md](extension/README.md) |
| Evaluation | [eval/README.md](eval/README.md) |
