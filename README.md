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

### Option A — VS Code Marketplace (recommended)

Search **Nexus AI** in the VS Code Extensions panel, or install directly:

**[Install from Marketplace →](https://marketplace.visualstudio.com/items?itemName=Hafiz408.nexus-ai)**

The extension auto-starts the bundled backend — no Python or terminal required.

---

### Option B — Run locally (development)

**Prerequisites:** VS Code 1.74+ · Node.js 20+ · Python 3.11+

#### 1. Clone and set up the backend

```bash
git clone https://github.com/Hafiz408/Nexus.git
cd Nexus/backend

python -m venv ../venv
source ../venv/bin/activate          # Windows: ..\venv\Scripts\activate
pip install -r requirements.txt

uvicorn app.main:app --reload --port 8000
# → http://localhost:8000/api/health should return {"status":"ok"}
```

#### 2. Set up and run the extension

In a separate terminal:

```bash
cd Nexus/extension
npm install
npm run build       # compiles TypeScript + React bundles into out/
```

Then in VS Code:
1. Open the `extension/` folder (`File > Open Folder`)
2. Press `F5` — an **Extension Development Host** window opens
3. In that new window, open your target repo as the workspace

> The extension detects that port 8000 is already occupied and skips spawning its own backend — your local `uvicorn` process is used instead (dev-mode passthrough).

#### 3. Configure provider and index

Inside the Extension Development Host window:

1. `Cmd+Shift+P` → **Nexus: Set API Key** → pick your provider → paste key
2. Open `Code > Settings > Extensions > Nexus` to set chat/embedding provider and model
3. `Cmd+Shift+P` → **Nexus: Index Workspace** — indexes the open repo into `.nexus/graph.db`
4. Once indexing completes, the chat input unlocks — ask a question

---

### Option C — Build .vsix from source

```bash
cd Nexus/backend
pip install -r requirements.txt pyinstaller
python build.py          # → extension/bin/nexus-backend-mac (or nexus-backend-win.exe)

cd ../extension
npm install && npm run build
npm install -g @vscode/vsce
vsce package --out nexus.vsix
# Install: VS Code → Extensions → ··· → Install from VSIX…
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
