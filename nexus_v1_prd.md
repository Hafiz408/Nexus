# Nexus V1 — Product Requirements Document
**AI-Native Codebase Intelligence — VS Code Extension**

> Feed this document to Claude Code CLI to scaffold and build Nexus V1.
> Version: 1.0 | Scope: V1 only (Explorer agent + ingestion + graph RAG + extension)

---

## 1. Project Overview

### 1.1 What We Are Building

Nexus is a VS Code extension backed by a FastAPI multi-agent backend. It parses a codebase into a structural **code graph** (nodes = functions/classes, edges = calls/imports/inheritance) using AST analysis, then uses **graph-traversal RAG** to answer questions grounded in the actual code structure — not just text similarity.

V1 ships one complete, demoable feature: **the Explorer agent** — ask any question about how the codebase works, get a cited, grounded answer with file:line references and highlighted code in the editor.

### 1.2 V1 Scope (what is IN)

- Multi-format code ingestion pipeline (Python + TypeScript)
- AST-based code graph construction (tree-sitter)
- Dual index: pgvector (semantic) + FTS5 (exact match)
- Graph-traversal RAG retrieval engine
- Single LangGraph agent (Explorer)
- LangSmith tracing on every query
- RAGAS baseline evaluation (30 golden Q&A pairs)
- FastAPI backend with SSE streaming
- VS Code extension with sidebar chat + file highlighting
- Docker Compose for local dev
- Basic pytest suite for the ingestion pipeline and retrieval engine

### 1.3 V1 Scope (what is OUT — save for V2)

- Debugger agent, Reviewer agent, Tester agent, Critic agent
- GitHub MCP, Filesystem MCP
- Full LangGraph multi-agent StateGraph (V1 uses a simple LangChain runnable)
- CI/CD GitHub Actions pipeline
- Production deployment (Fly.io/Render)
- Java, Go language support

### 1.4 Target Demo

Open any Python or TypeScript repo in VS Code → Nexus indexes it in < 30 seconds → Ask "How does user authentication work?" → Get a streamed, cited answer with the relevant files highlighted in the editor.

---

## 2. Repository Structure

```
nexus/
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI app entry point
│   │   ├── config.py                  # Settings (env-driven, pydantic-settings)
│   │   ├── ingestion/
│   │   │   ├── __init__.py
│   │   │   ├── file_walker.py         # Repo traversal, gitignore-aware
│   │   │   ├── ast_parser.py          # tree-sitter AST → structured nodes
│   │   │   ├── graph_builder.py       # NetworkX graph construction
│   │   │   ├── embedder.py            # Embed nodes → pgvector
│   │   │   └── pipeline.py            # Orchestrates full ingestion flow
│   │   ├── graph/
│   │   │   ├── __init__.py
│   │   │   ├── store.py               # Graph persistence (NetworkX + SQLite)
│   │   │   └── traversal.py           # BFS/DFS traversal, impact radius
│   │   ├── retrieval/
│   │   │   ├── __init__.py
│   │   │   ├── semantic_search.py     # pgvector cosine similarity search
│   │   │   ├── exact_search.py        # SQLite FTS5 exact match
│   │   │   └── graph_rag.py           # Graph-traversal RAG: seed → expand → rerank
│   │   ├── agents/
│   │   │   ├── __init__.py
│   │   │   ├── explorer.py            # Explorer agent (LangChain runnable, V1)
│   │   │   └── prompts.py             # All system + user prompt templates
│   │   ├── routers/
│   │   │   ├── __init__.py
│   │   │   ├── index.py               # POST /index, GET /index/status
│   │   │   └── query.py               # POST /query (SSE streaming)
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   └── schemas.py             # Pydantic request/response models
│   │   └── db/
│   │       ├── __init__.py
│   │       └── database.py            # SQLite + pgvector connection setup
│   ├── tests/
│   │   ├── test_file_walker.py
│   │   ├── test_ast_parser.py
│   │   ├── test_graph_builder.py
│   │   ├── test_graph_rag.py
│   │   └── conftest.py                # Shared fixtures (sample repo, mock embedder)
│   ├── eval/
│   │   ├── golden_qa.json             # 30 ground-truth Q&A pairs
│   │   └── run_ragas.py               # RAGAS evaluation runner
│   ├── requirements.txt
│   ├── Dockerfile
│   └── README.md
│
├── extension/
│   ├── src/
│   │   ├── extension.ts               # Extension entry point, activation
│   │   ├── sidebar/
│   │   │   ├── SidebarProvider.ts     # WebviewViewProvider implementation
│   │   │   └── webview/
│   │   │       ├── index.html         # Webview HTML shell
│   │   │       ├── main.tsx           # React app entry (sidebar UI)
│   │   │       ├── Chat.tsx           # Chat component with SSE streaming
│   │   │       └── styles.css
│   │   ├── indexer/
│   │   │   ├── IndexerService.ts      # Triggers backend /index on workspace open
│   │   │   └── FileWatcher.ts         # VS Code FileSystemWatcher → re-index on save
│   │   ├── editor/
│   │   │   └── Highlighter.ts         # Decorate cited file:line in editor
│   │   └── api/
│   │       ├── BackendClient.ts       # HTTP client to FastAPI
│   │       └── SseStream.ts           # SSE stream parser and emitter
│   ├── package.json
│   ├── tsconfig.json
│   ├── webpack.config.js
│   └── README.md
│
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## 3. Tech Stack

### Backend

| Layer | Technology | Version |
|---|---|---|
| Runtime | Python | 3.11+ |
| Web framework | FastAPI | 0.115+ |
| Agent framework | LangChain | 0.3+ |
| Observability | LangSmith | latest |
| AST parsing | tree-sitter + tree-sitter-python + tree-sitter-typescript | latest |
| Graph engine | NetworkX | 3.x |
| Vector store | pgvector (via psycopg2 + pgvector Python client) | latest |
| Exact search | SQLite FTS5 (built-in) | — |
| Graph persistence | SQLite (via aiosqlite) | — |
| Embeddings | OpenAI text-embedding-3-small (configurable) | — |
| LLM | OpenAI gpt-4o-mini (configurable) | — |
| Evaluation | RAGAS | latest |
| Settings | pydantic-settings | 2.x |
| Testing | pytest + pytest-asyncio | latest |

### Extension

| Layer | Technology |
|---|---|
| Language | TypeScript 5.x |
| Bundler | webpack |
| UI framework | React 18 (in Webview) |
| VS Code API | @types/vscode latest |
| HTTP client | native fetch |
| SSE | native EventSource |
| Packaging | vsce |

### Infrastructure

| Component | Technology |
|---|---|
| Container | Docker + Docker Compose |
| Database | PostgreSQL 16 with pgvector extension |
| Environment | .env via pydantic-settings |

---

## 4. Data Models

### 4.1 Code Graph Node

```python
# backend/app/models/schemas.py

from pydantic import BaseModel
from typing import Optional, Literal

NodeType = Literal["function", "class", "module", "method"]
EdgeType = Literal["CALLS", "IMPORTS", "INHERITS", "DEFINES", "USES"]

class CodeNode(BaseModel):
    id: str                    # unique: "file_path::name" e.g. "auth/login.py::validate_token"
    type: NodeType
    name: str                  # function/class name
    file_path: str             # relative to repo root
    line_start: int
    line_end: int
    language: str              # "python" | "typescript"
    signature: str             # full function signature or class declaration
    docstring: Optional[str]
    body_preview: str          # first 300 chars of body
    complexity: int            # cyclomatic complexity (1 if unknown)
    embedding_text: str        # what gets embedded: signature + docstring + body_preview

class CodeEdge(BaseModel):
    source_id: str             # CodeNode.id
    target_id: str             # CodeNode.id
    edge_type: EdgeType
```

### 4.2 API Request / Response Models

```python
class IndexRequest(BaseModel):
    repo_path: str             # absolute path to the repo on the backend filesystem
    languages: list[str] = ["python", "typescript"]

class IndexStatus(BaseModel):
    status: Literal["pending", "running", "complete", "failed"]
    nodes_indexed: int
    edges_indexed: int
    files_processed: int
    error: Optional[str]

class QueryRequest(BaseModel):
    question: str
    repo_path: str
    max_nodes: int = 10        # max context nodes to retrieve
    hop_depth: int = 2         # graph expansion depth

class SourceCitation(BaseModel):
    node_id: str
    file_path: str
    line_start: int
    line_end: int
    name: str
    relevance_score: float

class QueryResponse(BaseModel):
    answer: str                # streamed via SSE, this is the full answer on completion
    citations: list[SourceCitation]
    retrieval_stats: dict      # nodes_retrieved, graph_hops, latency_ms
```

### 4.3 SSE Stream Event Format

Every SSE event has this shape. The extension parses `event.data` as JSON:

```
event: token
data: {"type": "token", "content": "The authenticate"}

event: token
data: {"type": "token", "content": "d user flow starts"}

event: citations
data: {"type": "citations", "citations": [{...SourceCitation...}]}

event: done
data: {"type": "done", "retrieval_stats": {...}}

event: error
data: {"type": "error", "message": "..."}
```

---

## 5. Backend Implementation

### 5.1 Configuration (`app/config.py`)

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # LLM
    openai_api_key: str
    llm_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536

    # LangSmith
    langchain_tracing_v2: bool = True
    langchain_api_key: str = ""
    langchain_project: str = "nexus-v1"

    # Database
    postgres_url: str = "postgresql://nexus:nexus@localhost:5432/nexus"
    sqlite_path: str = "./data/nexus.db"

    # CORS
    allowed_origins: list[str] = ["http://localhost:3000", "vscode-webview://*"]

    # Ingestion
    max_file_size_kb: int = 500        # skip files larger than this
    chunk_body_preview_chars: int = 300

    class Config:
        env_file = ".env"

settings = Settings()
```

### 5.2 File Walker (`app/ingestion/file_walker.py`)

**Responsibility:** Walk a repo directory tree, return a list of file paths to parse.

**Behaviour:**
- Read `.gitignore` at the repo root and any nested `.gitignore` files. Skip ignored paths.
- Skip directories: `.git`, `node_modules`, `__pycache__`, `.venv`, `venv`, `dist`, `build`, `.next`, `coverage`, `*.egg-info`
- Skip files larger than `settings.max_file_size_kb`
- Return only files matching supported extensions: `.py` for Python, `.ts` / `.tsx` / `.js` / `.jsx` for TypeScript
- Detect language per file based on extension
- Return: `list[dict]` where each dict is `{"path": str, "language": str, "size_kb": float}`

**Function signature:**
```python
def walk_repo(repo_path: str, languages: list[str]) -> list[dict]:
    """
    Walk repo_path and return list of files to parse.
    Respects .gitignore. Skips binary, large, and irrelevant files.
    """
```

### 5.3 AST Parser (`app/ingestion/ast_parser.py`)

**Responsibility:** Parse a single source file using tree-sitter and extract CodeNode objects.

**Setup:**
```python
# Use tree-sitter Python bindings
# pip install tree-sitter tree-sitter-python tree-sitter-typescript
from tree_sitter import Language, Parser
import tree_sitter_python as tspython
import tree_sitter_typescript as tstypescript

PY_LANGUAGE = Language(tspython.language())
TS_LANGUAGE = Language(tstypescript.language_typescript())
```

**For Python files, extract:**
- `function_definition` nodes → CodeNode(type="function")
- `class_definition` nodes → CodeNode(type="class")
- For each function inside a class → CodeNode(type="method")
- `import_statement` and `import_from_statement` → used to build IMPORTS edges
- Call expressions inside function bodies → used to build CALLS edges

**For TypeScript/JavaScript files, extract:**
- `function_declaration`, `arrow_function`, `method_definition` → CodeNode
- `class_declaration` → CodeNode
- `import_declaration` → IMPORTS edges
- `call_expression` → CALLS edges

**Node ID format:** `"{relative_file_path}::{name}"` e.g. `"src/auth/login.py::validate_token"`

**For each node, populate:**
- `signature`: reconstruct the function/class declaration line from the AST
- `docstring`: extract the first string literal if it immediately follows the def/class
- `body_preview`: first 300 chars of the node body text
- `complexity`: count `if`, `for`, `while`, `try`, `elif`, `and`, `or` occurrences in body (simple proxy for cyclomatic complexity)
- `embedding_text`: `f"{signature}\n{docstring or ''}\n{body_preview}"`

**Function signature:**
```python
def parse_file(file_path: str, repo_root: str, language: str) -> tuple[list[CodeNode], list[tuple[str, str, str]]]:
    """
    Returns:
        nodes: list of CodeNode extracted from the file
        raw_edges: list of (source_id, target_name, edge_type) — target resolved later
    """
```

### 5.4 Graph Builder (`app/ingestion/graph_builder.py`)

**Responsibility:** Take all parsed nodes and raw edges, resolve edge targets, build a NetworkX DiGraph.

**Edge resolution:**
- Raw CALLS edges have `target_name` (just the function name called). Resolve by looking up the name in the full node registry.
- If a name matches multiple nodes (common name like `get`), keep all matches as edges.
- IMPORTS edges: if `auth.utils` is imported, add an IMPORTS edge from the importing module to every node in `auth/utils.py`.
- Unresolvable edges are dropped (log a warning).

**Graph structure:**
```python
import networkx as nx

G = nx.DiGraph()
# Add node: G.add_node(node.id, **node.dict())
# Add edge: G.add_edge(source_id, target_id, edge_type=edge_type)
```

**Metrics computed at build time (stored as node attributes):**
- `in_degree`: number of callers
- `out_degree`: number of callees
- `pagerank`: nx.pagerank(G) — measures centrality / hotspot score

**Function signature:**
```python
def build_graph(nodes: list[CodeNode], raw_edges: list[tuple]) -> nx.DiGraph:
    """
    Resolves edges, constructs NetworkX DiGraph.
    Returns the graph with all node attributes and computed metrics.
    """
```

### 5.5 Embedder (`app/ingestion/embedder.py`)

**Responsibility:** Generate embeddings for all CodeNode objects and upsert into pgvector.

**pgvector table schema (create on startup if not exists):**
```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS code_embeddings (
    id TEXT PRIMARY KEY,           -- CodeNode.id
    repo_path TEXT NOT NULL,
    file_path TEXT NOT NULL,
    node_type TEXT NOT NULL,
    name TEXT NOT NULL,
    line_start INTEGER,
    line_end INTEGER,
    language TEXT,
    signature TEXT,
    docstring TEXT,
    body_preview TEXT,
    complexity INTEGER,
    embedding vector(1536)
);

CREATE INDEX IF NOT EXISTS idx_embedding ON code_embeddings
    USING ivfflat (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_repo ON code_embeddings (repo_path);
```

**SQLite FTS5 table (for exact name search):**
```sql
CREATE VIRTUAL TABLE IF NOT EXISTS code_fts USING fts5(
    id, name, signature, docstring, repo_path,
    content='', contentless_delete=1
);
```

**Batching:** Embed in batches of 100 to avoid API rate limits. Use `openai.embeddings.create(input=[...], model=settings.embedding_model)`.

**Upsert logic:** Use `INSERT INTO ... ON CONFLICT (id) DO UPDATE SET ...` — safe for incremental re-indexing.

**Function signature:**
```python
async def embed_and_store(nodes: list[CodeNode], repo_path: str) -> int:
    """
    Embeds all nodes and upserts into pgvector + FTS5.
    Returns count of nodes stored.
    """
```

### 5.6 Ingestion Pipeline (`app/ingestion/pipeline.py`)

**Responsibility:** Orchestrate the full ingestion flow. Called by the `/index` endpoint.

```python
async def run_ingestion(repo_path: str, languages: list[str]) -> IndexStatus:
    """
    Full pipeline:
    1. file_walker.walk_repo()
    2. ast_parser.parse_file() for each file (run concurrently with asyncio.gather)
    3. graph_builder.build_graph()
    4. embedder.embed_and_store()
    5. graph_store.save_graph()
    Returns IndexStatus with counts.
    """
```

**Concurrency:** Parse files concurrently using `asyncio.gather` with a semaphore limiting to 10 concurrent parses. This keeps ingestion fast.

**Progress tracking:** Store current status in a simple in-memory dict keyed by `repo_path`. The `/index/status` endpoint reads from this dict.

**Incremental re-index (for FileSystemWatcher):** Accept a `changed_files: list[str]` parameter. If provided, only re-parse those files, remove their old nodes from the graph and pgvector, and re-add the new ones. Full re-index if `changed_files` is None.

### 5.7 Graph Store (`app/graph/store.py`)

**Responsibility:** Persist the NetworkX graph to SQLite and reload it on startup.

**SQLite schema:**
```sql
CREATE TABLE IF NOT EXISTS graph_nodes (
    id TEXT PRIMARY KEY,
    repo_path TEXT,
    data TEXT  -- JSON-serialised CodeNode attributes
);

CREATE TABLE IF NOT EXISTS graph_edges (
    source_id TEXT,
    target_id TEXT,
    edge_type TEXT,
    repo_path TEXT
);
```

**Key functions:**
```python
def save_graph(G: nx.DiGraph, repo_path: str) -> None: ...
def load_graph(repo_path: str) -> nx.DiGraph: ...
def delete_nodes_for_files(file_paths: list[str], repo_path: str) -> None: ...
```

### 5.8 Graph Traversal RAG (`app/retrieval/graph_rag.py`)

**This is the core differentiator. Implement carefully.**

**The 3-step retrieval:**

**Step 1 — Semantic seed search:**
```python
async def semantic_search(query: str, repo_path: str, top_k: int = 5) -> list[CodeNode]:
    """
    Embed the query, cosine similarity search in pgvector.
    Filter by repo_path. Return top_k nodes.
    SQL: SELECT *, 1 - (embedding <=> $query_vec) AS score
         FROM code_embeddings WHERE repo_path = $repo_path
         ORDER BY embedding <=> $query_vec LIMIT $top_k
    """
```

**Step 2 — Graph expansion (N-hop BFS):**
```python
def expand_via_graph(
    seed_node_ids: list[str],
    G: nx.DiGraph,
    hop_depth: int = 2,
    edge_types: list[str] = ["CALLS", "IMPORTS", "INHERITS"]
) -> list[str]:
    """
    BFS from each seed node, following edges in both directions up to hop_depth hops.
    Returns list of all node IDs reached (including seeds).
    Direction: follow outgoing edges (callees) AND incoming edges (callers).
    Deduplicate results.
    """
```

**Step 3 — Rerank and assemble context:**
```python
def rerank_and_assemble(
    expanded_node_ids: list[str],
    seed_scores: dict[str, float],   # node_id -> semantic similarity score
    G: nx.DiGraph,
    max_nodes: int = 10
) -> list[CodeNode]:
    """
    Score each expanded node:
        final_score = (semantic_score if in seeds else 0.3) +
                      (0.2 * pagerank_score) +
                      (0.1 * in_degree_normalised)
    Sort by final_score descending. Return top max_nodes.
    Assemble context string: for each node, include signature + docstring + body_preview + file:line.
    """
```

**Main entry point:**
```python
async def graph_rag_retrieve(
    query: str,
    repo_path: str,
    G: nx.DiGraph,
    max_nodes: int = 10,
    hop_depth: int = 2
) -> tuple[list[CodeNode], dict]:
    """
    Runs full 3-step graph-traversal RAG.
    Returns (retrieved_nodes, stats_dict).
    stats_dict: {nodes_semantic: int, nodes_after_expansion: int, nodes_final: int, hop_depth: int}
    """
```

### 5.9 Explorer Agent (`app/agents/explorer.py`)

**Responsibility:** V1 uses a simple LangChain runnable (not full LangGraph — that's V2). Takes retrieved context + question, generates a grounded answer with citations.

**System prompt** (in `app/agents/prompts.py`):
```
You are Nexus, an expert code intelligence assistant.
You answer questions about a codebase strictly grounded in the provided code context.
You NEVER make up function names, file paths, or behaviours not present in the context.

For every claim you make, cite the source using this format: [file_path:line_start]
If the context does not contain enough information to answer, say so clearly.
Structure your answer with:
1. A direct answer to the question (2-3 sentences)
2. A step-by-step explanation of the relevant flow
3. Key files and functions involved (with citations)
```

**User prompt template:**
```
Question: {question}

Codebase context (retrieved from graph-traversal RAG):
{context}

Answer the question based only on the context above.
```

**Context formatting:** For each CodeNode in retrieved list:
```
--- [{file_path}:{line_start}-{line_end}] {name} ({type}) ---
{signature}
{docstring}
{body_preview}
```

**Streaming:** Use `llm.astream()` and yield tokens via FastAPI's `StreamingResponse` with SSE format.

**LangSmith tracing:** Set `LANGCHAIN_TRACING_V2=true` in environment. LangChain automatically traces all LLM calls. Wrap the agent call with a named run:
```python
from langchain_core.tracers.context import tracing_v2_enabled
with tracing_v2_enabled(project_name="nexus-v1"):
    async for chunk in chain.astream(input):
        yield chunk
```

### 5.10 API Routers

**`POST /index`** — Start ingestion
```python
# Request body: IndexRequest
# Starts ingestion as a background task (FastAPI BackgroundTasks)
# Returns immediately with: {"status": "pending", "repo_path": "..."}
```

**`GET /index/status`** — Poll ingestion status
```python
# Query param: repo_path
# Returns: IndexStatus
```

**`POST /query`** — Query with SSE streaming
```python
# Request body: QueryRequest
# Returns StreamingResponse with media_type="text/event-stream"
# Stream: token events → citations event → done event
# On error: error event
```

**`GET /health`** — Health check
```python
# Returns: {"status": "ok", "version": "1.0.0"}
```

**`DELETE /index`** — Clear index for a repo
```python
# Query param: repo_path
# Removes all pgvector entries, FTS5 entries, and SQLite graph for this repo
```

---

## 6. VS Code Extension Implementation

### 6.1 Extension Entry Point (`extension.ts`)

**On activation (`activate` function):**
1. Register the `SidebarProvider` as a `WebviewViewProvider` for view ID `nexus.sidebar`
2. Register commands:
   - `nexus.indexWorkspace` — trigger indexing of the current workspace
   - `nexus.clearIndex` — clear the index for current workspace
3. If a workspace is open, automatically trigger `IndexerService.indexWorkspace()`
4. Start `FileWatcher` to watch for file changes

**Package.json contributions:**
```json
{
  "contributes": {
    "viewsContainers": {
      "activitybar": [{
        "id": "nexus",
        "title": "Nexus",
        "icon": "$(circuit-board)"
      }]
    },
    "views": {
      "nexus": [{
        "type": "webview",
        "id": "nexus.sidebar",
        "name": "Nexus Chat"
      }]
    },
    "commands": [
      {"command": "nexus.indexWorkspace", "title": "Nexus: Index Workspace"},
      {"command": "nexus.clearIndex", "title": "Nexus: Clear Index"}
    ],
    "configuration": {
      "title": "Nexus",
      "properties": {
        "nexus.backendUrl": {
          "type": "string",
          "default": "http://localhost:8000",
          "description": "Nexus backend URL"
        },
        "nexus.hopDepth": {
          "type": "number",
          "default": 2,
          "description": "Graph traversal hop depth (1-3)"
        },
        "nexus.maxNodes": {
          "type": "number",
          "default": 10,
          "description": "Max context nodes per query"
        }
      }
    }
  }
}
```

### 6.2 Sidebar Provider (`sidebar/SidebarProvider.ts`)

**Implements `vscode.WebviewViewProvider`.**

**`resolveWebviewView` method:**
- Set `webview.options = { enableScripts: true }`
- Set `webview.html` to the full HTML shell (loads the React bundle)
- Handle `webview.onDidReceiveMessage` for messages from the React UI:
  - `{ type: "query", question: string }` → call `BackendClient.streamQuery()` and forward SSE tokens back to webview via `webview.postMessage()`
  - `{ type: "ready" }` → send current index status to webview

**Messages sent TO the webview:**
```typescript
{ type: "token", content: string }
{ type: "citations", citations: SourceCitation[] }
{ type: "done", stats: object }
{ type: "error", message: string }
{ type: "indexStatus", status: IndexStatus }
```

### 6.3 Chat UI (`sidebar/webview/Chat.tsx`)

**React component. State:**
```typescript
interface Message {
  role: "user" | "assistant"
  content: string
  citations?: SourceCitation[]
  streaming?: boolean
}

const [messages, setMessages] = useState<Message[]>([])
const [input, setInput] = useState("")
const [isStreaming, setIsStreaming] = useState(false)
const [indexStatus, setIndexStatus] = useState<"idle"|"indexing"|"ready"|"error">("idle")
```

**On send:**
1. Add user message to `messages`
2. Add empty assistant message with `streaming: true`
3. Send `{ type: "query", question: input }` to extension via `vscode.postMessage()`
4. Listen for messages from extension:
   - `token` → append content to last assistant message
   - `citations` → add citations to last assistant message
   - `done` → set `streaming: false`
   - `error` → show error in UI

**Citation rendering:** Below each assistant message, show citations as clickable chips: `auth/login.py:42`. On click, send `{ type: "openFile", filePath, lineStart }` to extension, which uses `vscode.window.showTextDocument()` to open and scroll to the line.

**Index status bar:** At the top of the sidebar, show a status pill:
- "Indexing..." with a spinner (while ingestion runs)
- "Ready — 142 nodes" (after completion)
- "Not indexed" with a button "Index Workspace" (if no index)

**Styling:** Use VS Code CSS variables (`--vscode-*`) for all colours. No external CSS frameworks. Keep it minimal.

### 6.4 Indexer Service (`indexer/IndexerService.ts`)

```typescript
export class IndexerService {
  async indexWorkspace(): Promise<void> {
    const workspaceRoot = vscode.workspace.workspaceFolders?.[0].uri.fsPath
    if (!workspaceRoot) return

    // POST /index with { repo_path: workspaceRoot, languages: ["python", "typescript"] }
    // Poll GET /index/status every 2 seconds until status is "complete" or "failed"
    // Update sidebar with status via SidebarProvider.updateStatus()
  }
}
```

### 6.5 File Watcher (`indexer/FileWatcher.ts`)

```typescript
export class FileWatcher {
  activate(context: vscode.ExtensionContext): void {
    // Watch for .py, .ts, .tsx, .js, .jsx changes
    const watcher = vscode.workspace.createFileSystemWatcher(
      "**/*.{py,ts,tsx,js,jsx}"
    )

    // Debounce: wait 2 seconds after last change before triggering re-index
    // POST /index with changed_files: [filePath] (incremental re-index)
    watcher.onDidChange(debounce(this.onFileChange.bind(this), 2000))
    watcher.onDidCreate(debounce(this.onFileChange.bind(this), 2000))
    watcher.onDidDelete(debounce(this.onFileChange.bind(this), 2000))
  }
}
```

### 6.6 File Highlighter (`editor/Highlighter.ts`)

**Decorates cited file:line ranges in the editor with a subtle highlight.**

```typescript
const highlightDecoration = vscode.window.createTextEditorDecorationType({
  backgroundColor: new vscode.ThemeColor("editor.findMatchHighlightBackground"),
  borderRadius: "2px",
  isWholeLine: false
})

export async function highlightCitations(citations: SourceCitation[]): Promise<void> {
  // Group citations by file_path
  // For each file, open the document (vscode.workspace.openTextDocument)
  // Create DecorationOptions for each line range
  // Apply decorations via editor.setDecorations()
  // Clear decorations after 10 seconds or on next query
}
```

---

## 7. Docker Compose Setup

```yaml
# docker-compose.yml
version: "3.9"

services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: nexus
      POSTGRES_USER: nexus
      POSTGRES_PASSWORD: nexus
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U nexus"]
      interval: 5s
      timeout: 5s
      retries: 5

  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    volumes:
      - ./backend:/app           # mount for hot reload in dev
      - ./data:/app/data         # SQLite persistence
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - LANGCHAIN_API_KEY=${LANGCHAIN_API_KEY}
      - LANGCHAIN_TRACING_V2=true
      - LANGCHAIN_PROJECT=nexus-v1
      - POSTGRES_URL=postgresql://nexus:nexus@postgres:5432/nexus
    depends_on:
      postgres:
        condition: service_healthy
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

volumes:
  pgdata:
```

**`backend/Dockerfile`:**
```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y gcc libpq-dev && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**`.env.example`:**
```
OPENAI_API_KEY=sk-...
LANGCHAIN_API_KEY=ls__...
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT=nexus-v1
POSTGRES_URL=postgresql://nexus:nexus@localhost:5432/nexus
SQLITE_PATH=./data/nexus.db
LLM_MODEL=gpt-4o-mini
EMBEDDING_MODEL=text-embedding-3-small
```

---

## 8. Requirements Files

**`backend/requirements.txt`:**
```
fastapi==0.115.0
uvicorn[standard]==0.30.0
pydantic==2.7.0
pydantic-settings==2.3.0
langchain==0.3.0
langchain-openai==0.2.0
langsmith==0.1.99
openai==1.40.0
tree-sitter==0.23.0
tree-sitter-python==0.23.0
tree-sitter-typescript==0.23.0
networkx==3.3
psycopg2-binary==2.9.9
pgvector==0.3.2
aiosqlite==0.20.0
python-multipart==0.0.9
httpx==0.27.0
ragas==0.2.0
pytest==8.3.0
pytest-asyncio==0.23.0
python-dotenv==1.0.0
pathspec==0.12.1
```

---

## 9. Test Plan

### 9.1 Unit Tests

**`tests/test_file_walker.py`:**
- Test that `.gitignore` patterns are respected
- Test that `node_modules`, `__pycache__` are skipped
- Test that only `.py` and `.ts` files are returned when those languages are specified
- Test with a synthetic temp directory

**`tests/test_ast_parser.py`:**
- Test Python parsing: given a sample `.py` file with 2 functions and 1 class, assert correct nodes extracted
- Test that docstrings are extracted correctly
- Test that function calls inside bodies are detected as raw CALLS edges
- Test TypeScript parsing: function declarations, arrow functions, imports

**`tests/test_graph_builder.py`:**
- Test that CALLS edges are resolved correctly when function name exists in the node registry
- Test that unresolvable edge targets are dropped
- Test that PageRank is computed and stored as a node attribute
- Test graph has correct in_degree / out_degree for a known sample

**`tests/test_graph_rag.py`:**
- Test `expand_via_graph`: given a seed node with known neighbours, assert correct nodes returned at hop depth 1 and 2
- Test `rerank_and_assemble`: given seed scores and graph, assert output is sorted by final_score
- Test that max_nodes limit is respected
- Use a small in-memory NetworkX graph as fixture (no database required)

**`tests/conftest.py`:**
```python
# Shared fixtures:
# - sample_repo_path: a small synthetic Python repo in a temp dir (3 files, ~10 functions)
# - mock_embedder: returns deterministic fake embeddings (np.random.seed(42))
# - sample_graph: a small NetworkX DiGraph for unit tests
```

### 9.2 Integration Test (manual for V1)

1. `docker compose up`
2. Open the FastAPI sample repo in VS Code with Nexus extension loaded
3. Verify indexing completes and status shows "Ready"
4. Ask: "How does the routing system work?" — verify cited answer references correct files
5. Modify a file — verify re-indexing triggers automatically

---

## 10. Evaluation Setup

### 10.1 Golden Q&A Dataset

Create `backend/eval/golden_qa.json` with 30 Q&A pairs based on the **FastAPI source repo** (https://github.com/tiangolo/fastapi). This is a well-known, well-structured Python codebase that any interviewer can verify.

**Format:**
```json
[
  {
    "question": "How does FastAPI handle dependency injection?",
    "ground_truth": "FastAPI uses the Depends() function to declare dependencies. When a route is called, FastAPI resolves the dependency graph by calling each dependency function and injecting its return value. The core logic is in fastapi/dependencies/utils.py in the solve_dependencies() function.",
    "relevant_files": ["fastapi/dependencies/utils.py", "fastapi/params.py"]
  }
]
```

Create at least 30 pairs covering: routing, middleware, dependency injection, request parsing, response models, exception handlers, background tasks, security.

### 10.2 RAGAS Runner (`eval/run_ragas.py`)

```python
"""
Run RAGAS evaluation against the golden Q&A dataset.
Usage: python eval/run_ragas.py --repo-path /path/to/fastapi
Outputs: eval/results/ragas_results_{timestamp}.json
"""
```

**Metrics to compute:**
- `faithfulness`: does the answer only contain claims supported by the retrieved context?
- `answer_relevancy`: how relevant is the answer to the question?
- `context_precision`: how much of the retrieved context is actually relevant?

**Output format:**
```json
{
  "timestamp": "2025-01-01T00:00:00",
  "num_questions": 30,
  "avg_faithfulness": 0.87,
  "avg_answer_relevancy": 0.82,
  "avg_context_precision": 0.79,
  "per_question": [...]
}
```

**Comparison experiment:** Also run the same 30 questions with naive vector-only RAG (no graph expansion, just top-k semantic search). Report both sets of scores side by side to demonstrate graph-traversal improvement.

---

## 11. Key Constraints & Non-Negotiables

1. **All LLM calls must be traced in LangSmith.** No exceptions. Set `LANGCHAIN_TRACING_V2=true` from day one.

2. **The Explorer agent must never cite a file or line number that doesn't exist in the retrieved nodes.** If the context doesn't support the answer, the agent must say so. Enforce this via the system prompt and validate in tests.

3. **Ingestion must be incremental.** Full re-indexing on every file save is a dealbreaker for UX. The pipeline must support `changed_files` parameter from day one.

4. **SSE streaming is required.** The extension must show tokens as they stream — not wait for the full response. This is critical for the demo.

5. **The `graph_rag.py` module must have unit tests that run without a database.** Use a small in-memory NetworkX graph as a fixture. The retrieval logic must be testable in isolation.

6. **No hardcoded API keys anywhere.** All secrets via `.env` and `pydantic-settings`.

7. **CORS must allow `vscode-webview://*`.** The Webview origin is non-standard and must be explicitly allowed.

---

## 12. Implementation Order (Recommended)

Follow this sequence to always have a working, demoable state:

1. **Docker Compose up** — get PostgreSQL + pgvector running
2. **`file_walker.py` + tests** — walk a repo, get file list
3. **`ast_parser.py` + tests** — parse Python files, extract nodes
4. **`graph_builder.py` + tests** — build NetworkX graph, resolve edges
5. **`embedder.py`** — embed nodes into pgvector
6. **`pipeline.py`** — wire steps 2-5 together
7. **`/index` endpoint** — expose pipeline via FastAPI
8. **`graph_rag.py` + tests** — implement 3-step retrieval (test without DB)
9. **`explorer.py`** — LangChain agent with streaming
10. **`/query` endpoint** — SSE streaming endpoint
11. **VS Code extension** — sidebar, BackendClient, SSE streaming to UI
12. **Highlighter** — file:line decoration in editor
13. **FileWatcher** — incremental re-index on save
14. **RAGAS eval** — run baseline, record numbers

---

## 13. Definition of Done for V1

V1 is complete when all of the following are true:

- [ ] `docker compose up` starts the full stack without errors
- [ ] Indexing the FastAPI repo (100k+ LOC) completes in under 2 minutes
- [ ] GET `/index/status` returns `complete` with accurate node/edge counts
- [ ] POST `/query` returns a streamed, cited answer for "How does dependency injection work?"
- [ ] The VS Code extension sidebar shows the answer with token streaming
- [ ] Clicking a citation highlights the correct line in the editor
- [ ] Modifying a file triggers incremental re-index within 5 seconds
- [ ] All unit tests pass (`pytest backend/tests/`)
- [ ] LangSmith dashboard shows traces for all queries
- [ ] RAGAS baseline scores recorded and committed to `eval/results/`
- [ ] README documents setup, architecture, and how to run the eval