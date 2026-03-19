# Requirements: Nexus V1

**Defined:** 2026-03-18
**Core Value:** A developer can ask any question about a codebase and get a streamed, cited, graph-grounded answer with exact file:line highlights in VS Code.

## v1 Requirements

### Infrastructure

- [x] **INFRA-01**: `docker compose up` starts PostgreSQL 16 + pgvector without errors and passes health checks
- [x] **INFRA-02**: Backend Dockerfile builds Python 3.11 environment with all dependencies
- [x] **INFRA-03**: `.env.example` documents all required secrets; `.env` is in `.gitignore`
- [x] **INFRA-04**: `data/` directory is mounted for SQLite persistence across container restarts

### Ingestion — File Walker

- [x] **WALK-01**: `walk_repo(repo_path, languages)` returns list of `{path, language, size_kb}` dicts
- [x] **WALK-02**: Respects `.gitignore` at repo root and nested directories (via pathspec)
- [x] **WALK-03**: Skips directories: `.git`, `node_modules`, `__pycache__`, `.venv`, `venv`, `dist`, `build`, `.next`, `coverage`, `*.egg-info`
- [x] **WALK-04**: Skips files larger than `settings.max_file_size_kb` (default 500KB)
- [x] **WALK-05**: Detects language per file extension (`.py` → python; `.ts/.tsx/.js/.jsx` → typescript)
- [x] **WALK-06**: Unit tests pass with synthetic temp directory fixture

### Ingestion — AST Parser

- [x] **PARSE-01**: `parse_file(file_path, repo_root, language)` returns `(list[CodeNode], list[raw_edges])`
- [x] **PARSE-02**: Extracts Python `function_definition`, `class_definition`, methods inside classes
- [x] **PARSE-03**: Extracts TypeScript `function_declaration`, `arrow_function`, `method_definition`, `class_declaration`
- [x] **PARSE-04**: Node ID format: `"relative_file_path::name"` (consistent across all modules)
- [x] **PARSE-05**: Populates `signature`, `docstring`, `body_preview` (first 300 chars), `complexity` (keyword count proxy)
- [x] **PARSE-06**: `embedding_text` = `"{signature}\n{docstring}\n{body_preview}"`
- [x] **PARSE-07**: Detects `import` statements and `call_expression`s for raw IMPORTS/CALLS edges
- [x] **PARSE-08**: Unit tests pass: 2 functions + 1 class in sample file → correct node count + docstrings

### Ingestion — Graph Builder

- [x] **GRAPH-01**: `build_graph(nodes, raw_edges)` returns `nx.DiGraph` with all node attributes
- [x] **GRAPH-02**: Resolves raw CALLS edges by matching `target_name` against full node registry; unresolvable edges dropped with warning
- [x] **GRAPH-03**: Resolves IMPORTS edges: module import → IMPORTS edge to all nodes in target file
- [x] **GRAPH-04**: Computes and stores `in_degree`, `out_degree`, `pagerank` as node attributes
- [x] **GRAPH-05**: Unit tests pass: edge resolution, PageRank presence, in/out degree correctness

### Ingestion — Embedder

- [x] **EMBED-01**: `embed_and_store(nodes, repo_path)` embeds all nodes and upserts into pgvector
- [x] **EMBED-02**: Creates `code_embeddings` table with vector(1536) and ivfflat index on startup
- [x] **EMBED-03**: Creates SQLite FTS5 `code_fts` virtual table for exact name search
- [x] **EMBED-04**: Embeds in batches of 100 using `openai.embeddings.create()`
- [x] **EMBED-05**: Upsert logic: `INSERT ... ON CONFLICT (id) DO UPDATE` — safe for incremental re-index
- [x] **EMBED-06**: Returns count of nodes stored

### Ingestion — Pipeline

- [x] **PIPE-01**: `run_ingestion(repo_path, languages)` orchestrates walk → parse → build → embed → save
- [x] **PIPE-02**: File parsing runs concurrently via `asyncio.gather` with semaphore limiting to 10 concurrent parses
- [x] **PIPE-03**: Supports `changed_files: list[str]` for incremental re-index (re-parse only changed files, remove old nodes)
- [x] **PIPE-04**: Stores current status in in-memory dict keyed by `repo_path` for status polling
- [x] **PIPE-05**: Returns `IndexStatus` with `{status, nodes_indexed, edges_indexed, files_processed, error}`

### Graph Store

- [x] **STORE-01**: `save_graph(G, repo_path)` persists NetworkX graph to SQLite (`graph_nodes` + `graph_edges` tables)
- [x] **STORE-02**: `load_graph(repo_path)` reconstructs NetworkX DiGraph from SQLite on startup
- [x] **STORE-03**: `delete_nodes_for_files(file_paths, repo_path)` removes nodes for incremental re-index

### Retrieval — Graph RAG

- [x] **RAG-01**: `semantic_search(query, repo_path, top_k)` embeds query, cosine similarity search in pgvector, returns top_k CodeNodes
- [x] **RAG-02**: `expand_via_graph(seed_node_ids, G, hop_depth, edge_types)` BFS in both directions up to `hop_depth` hops; returns deduplicated node IDs
- [x] **RAG-03**: `rerank_and_assemble(expanded_node_ids, seed_scores, G, max_nodes)` scores nodes: `(semantic_score if seed else 0.3) + (0.2 * pagerank) + (0.1 * in_degree_norm)`; returns top `max_nodes` sorted by score
- [x] **RAG-04**: `graph_rag_retrieve(query, repo_path, G, max_nodes, hop_depth)` runs full 3-step retrieval, returns `(list[CodeNode], stats_dict)`
- [x] **RAG-05**: Unit tests pass using in-memory NetworkX fixture — no database required
- [x] **RAG-06**: Tests verify BFS expansion at hop depth 1 and 2, reranking order, max_nodes limit

### Agent — Explorer

- [x] **AGNT-01**: `explorer.py` implements LangChain runnable (not LangGraph) that takes retrieved context + question, generates grounded answer
- [x] **AGNT-02**: System prompt in `prompts.py` instructs agent to cite only file:line present in retrieved nodes; never fabricate
- [x] **AGNT-03**: Uses `llm.astream()` and yields SSE-formatted tokens
- [x] **AGNT-04**: All LLM calls traced in LangSmith via `LANGCHAIN_TRACING_V2=true` and `tracing_v2_enabled` context manager
- [x] **AGNT-05**: Context formatted per PRD: `--- [file_path:line_start-line_end] name (type) ---\n{signature}\n{docstring}\n{body_preview}`

### API Endpoints

- [x] **API-01**: `POST /index` accepts `IndexRequest{repo_path, languages}`, starts ingestion as BackgroundTask, returns `{status: "pending", repo_path}`
- [x] **API-02**: `GET /index/status?repo_path=...` returns `IndexStatus`
- [x] **API-03**: `POST /query` accepts `QueryRequest{question, repo_path, max_nodes, hop_depth}`, returns SSE `StreamingResponse`
- [x] **API-04**: SSE stream format: `event: token\ndata: {type, content}` → `event: citations\ndata: {type, citations}` → `event: done\ndata: {type, retrieval_stats}` → `event: error\ndata: {type, message}`
- [x] **API-05**: `GET /health` returns `{status: "ok", version: "1.0.0"}`
- [x] **API-06**: `DELETE /index?repo_path=...` removes all pgvector, FTS5, SQLite data for repo
- [x] **API-07**: CORS allows `vscode-webview://*` and `http://localhost:3000`
- [x] **API-08**: `app/config.py` uses pydantic-settings; all secrets from `.env`; no hardcoded values

### VS Code Extension — Core

- [x] **EXT-01**: Extension activates on VS Code startup; registers `nexus.sidebar` WebviewViewProvider
- [x] **EXT-02**: Registers commands: `nexus.indexWorkspace`, `nexus.clearIndex`
- [x] **EXT-03**: `package.json` contributes activity bar icon `$(circuit-board)`, sidebar view, commands, and configuration (`backendUrl`, `hopDepth`, `maxNodes`)
- [x] **EXT-04**: On activation with open workspace, automatically triggers `IndexerService.indexWorkspace()`

### VS Code Extension — Sidebar Chat

- [x] **CHAT-01**: React 18 Webview shows chat messages with `user` and `assistant` roles
- [x] **CHAT-02**: Streaming: tokens append to last assistant message in real-time
- [x] **CHAT-03**: Citations rendered as clickable chips (`auth/login.py:42`); click opens file at correct line in editor
- [x] **CHAT-04**: Index status bar shows `Indexing...` spinner / `Ready — N nodes` / `Not indexed` + Index Workspace button
- [x] **CHAT-05**: Styling uses VS Code CSS variables (`--vscode-*`); no external CSS frameworks

### VS Code Extension — Backend Client & SSE

- [x] **SSE-01**: `BackendClient.ts` sends `POST /index` and polls `GET /index/status` every 2 seconds until complete/failed
- [x] **SSE-02**: `SseStream.ts` parses native EventSource stream; forwards token/citations/done/error events to SidebarProvider
- [x] **SSE-03**: SidebarProvider forwards events to Webview via `webview.postMessage()`

### VS Code Extension — Highlighter

- [ ] **HIGH-01**: `highlightCitations(citations)` groups citations by file path, opens documents, applies `TextEditorDecorationType` to cited line ranges
- [ ] **HIGH-02**: Uses `editor.findMatchHighlightBackground` theme color; clears after 10 seconds or next query

### VS Code Extension — File Watcher

- [ ] **WATCH-01**: `FileWatcher` watches `**/*.{py,ts,tsx,js,jsx}` via `vscode.workspace.createFileSystemWatcher`
- [ ] **WATCH-02**: Debounces 2 seconds after last file change before triggering re-index
- [ ] **WATCH-03**: Sends `POST /index` with `changed_files: [filePath]` for incremental re-index

### Evaluation

- [ ] **EVAL-01**: `backend/eval/golden_qa.json` contains 30 Q&A pairs based on the FastAPI repo, covering routing, middleware, DI, request parsing, response models, exception handlers, background tasks, security
- [ ] **EVAL-02**: `eval/run_ragas.py` runs faithfulness, answer_relevancy, context_precision metrics against golden dataset
- [ ] **EVAL-03**: Results written to `eval/results/ragas_results_{timestamp}.json` with per-question breakdown
- [ ] **EVAL-04**: Comparison experiment: graph-traversal RAG vs naive vector-only RAG side-by-side scores committed

### Tests

- [ ] **TEST-01**: `pytest backend/tests/` passes all unit tests
- [x] **TEST-02**: `tests/test_file_walker.py` — gitignore, skip dirs, extension filtering with temp dir fixture
- [x] **TEST-03**: `tests/test_ast_parser.py` — Python + TypeScript parsing, docstring extraction, CALLS edge detection
- [x] **TEST-04**: `tests/test_graph_builder.py` — edge resolution, unresolvable edge drop, PageRank, in/out degree
- [x] **TEST-05**: `tests/test_graph_rag.py` — BFS expansion, reranking, max_nodes; all with in-memory fixture (no DB)
- [x] **TEST-06**: `tests/conftest.py` — `sample_repo_path` (synthetic temp repo), `mock_embedder` (deterministic np.random.seed(42)), `sample_graph` (small NetworkX DiGraph)

## v2 Requirements

### Multi-Agent System

- **MAGNT-01**: Full LangGraph StateGraph with Debugger, Reviewer, Tester, Critic agents
- **MAGNT-02**: GitHub MCP integration
- **MAGNT-03**: Filesystem MCP integration

### Language Support

- **LANG-01**: Java language parsing and graph integration
- **LANG-02**: Go language parsing and graph integration

### DevOps

- **DEVOPS-01**: GitHub Actions CI/CD pipeline
- **DEVOPS-02**: Production deployment to Fly.io or Render

## Out of Scope

| Feature | Reason |
|---------|--------|
| LangGraph StateGraph | V1 uses simple LangChain runnable; StateGraph complexity deferred to V2 |
| Java / Go language support | Focus on Python + TypeScript for V1 demo |
| GitHub MCP | V2 multi-agent architecture |
| CI/CD GitHub Actions | V2 |
| Production deployment | V2 — V1 is local dev only |
| OAuth / multi-user auth | Single-user VS Code extension, no user accounts needed |
| Real-time collaboration | Out of scope for a developer tool extension |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| INFRA-01 | Phase 1 | Complete |
| INFRA-02 | Phase 1 | Complete |
| INFRA-03 | Phase 1 | Complete |
| INFRA-04 | Phase 1 | Complete |
| WALK-01 | Phase 2 | Complete |
| WALK-02 | Phase 2 | Complete |
| WALK-03 | Phase 2 | Complete |
| WALK-04 | Phase 2 | Complete |
| WALK-05 | Phase 2 | Complete |
| WALK-06 | Phase 2 | Complete |
| TEST-02 | Phase 2 | Complete |
| PARSE-01 | Phase 3 | Complete |
| PARSE-02 | Phase 3 | Complete |
| PARSE-03 | Phase 3 | Complete |
| PARSE-04 | Phase 3 | Complete |
| PARSE-05 | Phase 3 | Complete |
| PARSE-06 | Phase 3 | Complete |
| PARSE-07 | Phase 3 | Complete |
| PARSE-08 | Phase 3 | Complete |
| TEST-03 | Phase 3 | Complete |
| GRAPH-01 | Phase 4 | Complete |
| GRAPH-02 | Phase 4 | Complete |
| GRAPH-03 | Phase 4 | Complete |
| GRAPH-04 | Phase 4 | Complete |
| GRAPH-05 | Phase 4 | Complete |
| TEST-04 | Phase 4 | Complete |
| EMBED-01 | Phase 5 | Complete |
| EMBED-02 | Phase 5 | Complete |
| EMBED-03 | Phase 5 | Complete |
| EMBED-04 | Phase 5 | Complete |
| EMBED-05 | Phase 5 | Complete |
| EMBED-06 | Phase 5 | Complete |
| STORE-01 | Phase 5 | Complete |
| STORE-02 | Phase 5 | Complete |
| STORE-03 | Phase 5 | Complete |
| PIPE-01 | Phase 6 | Complete |
| PIPE-02 | Phase 6 | Complete |
| PIPE-03 | Phase 6 | Complete |
| PIPE-04 | Phase 6 | Complete |
| PIPE-05 | Phase 6 | Complete |
| API-01 | Phase 7 | Complete |
| API-02 | Phase 7 | Complete |
| API-05 | Phase 7 | Complete |
| API-06 | Phase 7 | Complete |
| API-07 | Phase 7 | Complete |
| API-08 | Phase 7 | Complete |
| RAG-01 | Phase 8 | Complete |
| RAG-02 | Phase 8 | Complete |
| RAG-03 | Phase 8 | Complete |
| RAG-04 | Phase 8 | Complete |
| RAG-05 | Phase 8 | Complete |
| RAG-06 | Phase 8 | Complete |
| TEST-05 | Phase 8 | Complete |
| TEST-06 | Phase 8 | Complete |
| AGNT-01 | Phase 9 | Complete |
| AGNT-02 | Phase 9 | Complete |
| AGNT-03 | Phase 9 | Complete |
| AGNT-04 | Phase 9 | Complete |
| AGNT-05 | Phase 9 | Complete |
| API-03 | Phase 10 | Complete |
| API-04 | Phase 10 | Complete |
| EXT-01 | Phase 11 | Complete |
| EXT-02 | Phase 11 | Complete |
| EXT-03 | Phase 11 | Complete |
| EXT-04 | Phase 11 | Complete |
| CHAT-01 | Phase 11 | Complete |
| CHAT-02 | Phase 11 | Complete |
| CHAT-03 | Phase 11 | Complete |
| CHAT-04 | Phase 11 | Complete |
| CHAT-05 | Phase 11 | Complete |
| SSE-01 | Phase 11 | Complete |
| SSE-02 | Phase 11 | Complete |
| SSE-03 | Phase 11 | Complete |
| HIGH-01 | Phase 12 | Pending |
| HIGH-02 | Phase 12 | Pending |
| WATCH-01 | Phase 13 | Pending |
| WATCH-02 | Phase 13 | Pending |
| WATCH-03 | Phase 13 | Pending |
| EVAL-01 | Phase 14 | Pending |
| EVAL-02 | Phase 14 | Pending |
| EVAL-03 | Phase 14 | Pending |
| EVAL-04 | Phase 14 | Pending |
| TEST-01 | Phase 14 | Pending |

**Coverage:**
- v1 requirements: 74 total (68 functional + 6 test files mapped to their phases)
- Mapped to phases: 74
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-18*
*Last updated: 2026-03-18 — traceability updated after roadmap creation*
