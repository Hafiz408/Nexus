# Nexus — Graph-Grounded Code Intelligence

AI-powered code assistant that understands your codebase through a **call graph + vector index**. Ask questions in plain English; get grounded, citation-backed answers with file/line references — streamed live in VS Code.

> **Local-first & privacy-preserving.** No database server required. The graph and vector index live in `.nexus/graph.db` inside your workspace — your code never leaves your machine.

## Features

| Mode | What it does |
|---|---|
| **Explain** | Semantic + graph-aware retrieval; streams tokens with clickable file citations. When the selected code is module-level (not a function/class), the selected lines are read directly from disk and used as context. |
| **Debug** | BFS call-graph traversal, anomaly scoring, ranked suspect list with diagnosis |
| **Review** | Structured findings (severity · category · suggestion), postable to GitHub PRs |
| **Test** | Framework-aware test generation written directly to your repo |

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
│            Tools (PR post · file I/O)│
└──────────┬───────────────────────────┘
           │
  ┌────────┴──────────────────────┐
  │ SQLite  (sqlite-vec)          │
  │ .nexus/graph.db per workspace │
  │ graph · FTS · vector index    │
  └───────────────────────────────┘
```

The backend is **stateless compute** — it receives a `db_path` with every request pointing to the workspace SQLite file. No shared database, no server to manage.

The extension **automatically downloads** (on first use) and **spawns** the backend binary on activate, and shuts it down on deactivate. No Python installation required.

## Query Flow

```
Question
  │
  ├─ Dual search:
  │   ├─ Embed → sqlite-vec cosine search (semantic seeds, cosine ≥ 0.20 floor)
  │   └─ FTS5 BM25 on name + embedding_text (keyword seeds, stopword-filtered)
  ├─ RRF merge: rank-fusion of semantic + FTS → unified scores
  ├─ Graph expand from seed nodes:
  │   ├─ CALLS depth-1: callers + callees (IMPORTS excluded; score = parent × 0.6)
  │   ├─ CLASS_CONTAINS: class → method and method → class edges
  │   └─ PPR (Personalized PageRank): alpha=0.85, 50 iterations from seed set
  ├─ Full-body promotion: top nodes fetch complete source body (not preview)
  ├─ Combine pool: seeds overwrite neighbors + test-file ×0.5 penalty
  ├─ Cross-encoder rerank (default on): ms-marco-MiniLM-L-6-v2 jointly scores
  │   (query, node_context) pairs over top 2×N → CE floor ≥ 0.1; falls back silently on error
  ├─ MMR selection: score − 0.35×same-file-count → top max_nodes
  │
  └─ intent = explain?  → stream tokens → file citations
     intent = debug/review/test?
       → Specialist agent
           → Critic (score = 0.4G + 0.35R + 0.25A)
               └── score < 0.7 → retry (max 2×)
```

See [backend/app/retrieval/README.md](backend/app/retrieval/README.md) for a detailed breakdown of the dual-search and graph expansion pipeline, including eval results.

## Installation

### Option A — VS Code Marketplace (recommended)

Search **Nexus AI** in the VS Code Extensions panel, or install directly:

**[Install from VS Code Marketplace →](https://marketplace.visualstudio.com/items?itemName=Hafiz408.nexus-ai)**

**[Install from Open VSX Registry →](https://open-vsx.org/extension/Hafiz408/nexus-ai)** (VSCodium and other open editors)

On first activation the extension downloads the backend binary for your platform from GitHub Releases, verifies its SHA256 checksum, and caches it permanently. Subsequent activations start from the local cache — no Python or terminal required.

---

### Option B — Run locally (development)

**Prerequisites:** VS Code 1.74+ · Node.js 20+ · Python 3.11+

#### 1. Clone and set up the backend

```bash
git clone https://github.com/Hafiz408/Nexus.git
cd Nexus/backend

# Python must be compiled with loadable-extension support (required for sqlite-vec)
# If using pyenv: PYTHON_CONFIGURE_OPTS="--enable-loadable-sqlite-extensions" pyenv install 3.11.13

python -m venv ../venv
source ../venv/bin/activate          # Windows: ..\venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env                 # then edit .env with your API key(s)

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
python build.py          # → extension/bin/nexus-backend-mac.tar.gz (or nexus-backend-win.tar.gz)

cd ../extension
npm install && npm run build
npm install -g @vscode/vsce
vsce package --out nexus.vsix
# Install: VS Code → Extensions → ··· → Install from VSIX…
```

> The locally built VSIX will use the binary at `extension/bin/` rather than downloading from GitHub Releases.

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

```
tag push  ──────────────────────────────────────────────────────────┐
                                                                     │
          ┌──────────────────── Validation (parallel) ─────────────┐│
          │  backend-unit-tests   289 tests, no API keys            ││
          │  backend-smoke-test   live index + chat stream          ││
          │  changelog-check      tag = package.json = CHANGELOG    ││
          │  extension-build      TypeScript compile check          ││
          └──────────────────────────────┬──────────────────────────┘│
                                         │ all pass                   │
                         ┌───────────────┴───────────────┐           │
                         │       Build (parallel)        │           │
                         │  build-mac   macOS PyInstaller │           │
                         │  build-win   Windows PyInstaller│          │
                         └───────────────┬───────────────┘           │
                                         │                            │
                                  github-release  ◄──────────────────┘
                             binaries + checksums.sha256
                             uploaded as GitHub Release assets
                                         │
                                      package
                              lightweight .vsix  (~1.5 MB, no binaries)
                                         │
                                       publish
                              VS Code Marketplace + Open VSX Registry
```

The VSIX contains no native binaries — on first activation the extension downloads the correct platform binary from the GitHub Release, verifies its SHA256 checksum, and caches it in VS Code's global storage.

## Structure

```
nexus/
├── backend/           → FastAPI service
│   ├── build.py       → PyInstaller build script
│   └── app/
│       ├── api/       → HTTP endpoints + SSE routing
│       ├── ingestion/ → AST parsing, graph, sqlite-vec index
│       ├── retrieval/ → Graph RAG pipeline (semantic + FTS5 dual search)
│       ├── agent/     → Multi-agent orchestration (LangGraph)
│       ├── core/      → Provider-agnostic model factory
│       └── mcp/       → Side-effect tools (GitHub PR posting, test file writer)
├── extension/         → VS Code extension (TypeScript + React)
│   └── bin/           → Local dev binaries (not bundled in published VSIX)
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
| Agent Tools | [backend/app/mcp/README.md](backend/app/mcp/README.md) |
| Extension | [extension/README.md](extension/README.md) |
| Evaluation | [eval/README.md](eval/README.md) |
