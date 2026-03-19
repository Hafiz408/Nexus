# Roadmap: Nexus V1

## Overview

Nexus V1 builds a VS Code extension backed by a FastAPI multi-agent backend that delivers one complete, demoable feature: the Explorer agent. The 14 phases follow the PRD Section 12 implementation order, ensuring the system is always in a demoable state. Each phase produces a verified, tested artifact that the next phase builds on — from Docker infrastructure up through RAGAS evaluation proving graph-traversal RAG outperforms naive vector search.

## Phases

**Phase Numbering:**
- Integer phases (1–14): Planned milestone work in PRD order
- Decimal phases (N.1, N.2): Urgent insertions, created via `/gsd:insert-phase`

- [x] **Phase 1: Infrastructure** - Docker Compose running PostgreSQL + pgvector with health checks (completed 2026-03-18)
- [x] **Phase 2: File Walker** - `file_walker.py` + tests — traverse repo, return annotated file list (completed 2026-03-18)
- [x] **Phase 3: AST Parser** - `ast_parser.py` + tests — parse Python/TypeScript, extract CodeNode objects (completed 2026-03-18)
- [x] **Phase 4: Graph Builder** - `graph_builder.py` + tests — NetworkX DiGraph with edge resolution and PageRank (completed 2026-03-18)
- [x] **Phase 5: Embedder** - `embedder.py` — embed nodes into pgvector + SQLite FTS5 (completed 2026-03-18)
- [x] **Phase 6: Pipeline** - `pipeline.py` — orchestrate ingestion steps 2–5 with concurrency + incremental re-index (completed 2026-03-18)
- [x] **Phase 7: Index Endpoint** - `POST /index` + `GET /index/status` via FastAPI BackgroundTasks (completed 2026-03-18)
- [x] **Phase 7.1: Tech Debt Cleanup** - Fix FTS5 stale rows on incremental re-index + add backend Docker healthcheck (completed 2026-03-19)
- [x] **Phase 8: Graph RAG** - `graph_rag.py` + tests — 3-step graph-traversal RAG, testable without DB (completed 2026-03-19)
- [x] **Phase 9: Explorer Agent** - `explorer.py` — LangChain streaming agent with LangSmith tracing (completed 2026-03-19)
- [x] **Phase 10: Query Endpoint** - `POST /query` SSE streaming endpoint (completed 2026-03-19)
- [x] **Phase 11: VS Code Extension** - Sidebar, BackendClient, SSE streaming to React chat UI (completed 2026-03-19)
- [x] **Phase 12: Highlighter** - `Highlighter.ts` — file:line decoration in VS Code editor (completed 2026-03-19)
- [x] **Phase 13: File Watcher** - `FileWatcher.ts` — incremental re-index on file save (completed 2026-03-19)
- [ ] **Phase 14: RAGAS Eval** - Evaluation runner with 30 golden Q&A pairs, baseline scores committed

## Phase Details

### Phase 1: Infrastructure
**Goal**: Local development environment is fully operational with a healthy PostgreSQL + pgvector database
**Depends on**: Nothing (first phase)
**Requirements**: INFRA-01, INFRA-02, INFRA-03, INFRA-04
**Success Criteria** (what must be TRUE):
  1. `docker compose up` starts without errors and the postgres container reports healthy
  2. pgvector extension is available and queryable inside the container
  3. Backend container builds successfully with all Python dependencies installed
  4. `.env.example` documents every required secret; `.env` is git-ignored and never committed
  5. SQLite `data/` directory persists across container restarts
**Plans**: 3 plans
Plans:
- [ ] 01-01-PLAN.md — Docker Compose stack + backend Dockerfile + requirements.txt
- [ ] 01-02-PLAN.md — pydantic-settings config, database.py stub, .env.example, .gitignore, data/
- [ ] 01-03-PLAN.md — Create .env, start stack, verify all INFRA requirements (checkpoint)

### Phase 2: File Walker
**Goal**: A verified module that accurately enumerates the files in any Python or TypeScript repo
**Depends on**: Phase 1
**Requirements**: WALK-01, WALK-02, WALK-03, WALK-04, WALK-05, WALK-06, TEST-02
**Success Criteria** (what must be TRUE):
  1. `walk_repo(repo_path, languages)` returns a list of `{path, language, size_kb}` dicts for every qualifying file
  2. Files and directories excluded by `.gitignore` do not appear in results
  3. Noise directories (`.git`, `node_modules`, `__pycache__`, `.venv`, `dist`, etc.) are always skipped
  4. Files exceeding `max_file_size_kb` are silently dropped
  5. All unit tests pass against a synthetic temp directory fixture
**Plans**: 1 plan
Plans:
- [ ] 02-01-PLAN.md — TDD: walk_repo implementation + test_file_walker.py (12 test cases)

### Phase 3: AST Parser
**Goal**: A verified module that transforms source files into structured CodeNode objects ready for graph construction
**Depends on**: Phase 2
**Requirements**: PARSE-01, PARSE-02, PARSE-03, PARSE-04, PARSE-05, PARSE-06, PARSE-07, PARSE-08, TEST-03
**Success Criteria** (what must be TRUE):
  1. `parse_file()` returns the correct number of CodeNode objects from a sample Python file (2 functions + 1 class)
  2. Every node carries `signature`, `docstring`, `body_preview`, `complexity`, and `embedding_text`
  3. Node IDs consistently use `"relative_file_path::name"` format across all parsed files
  4. TypeScript `function_declaration`, `arrow_function`, `method_definition`, and `class_declaration` nodes are extracted
  5. Raw IMPORTS and CALLS edges are detected and returned alongside nodes
**Plans**: 2 plans
Plans:
- [ ] 03-01-PLAN.md — CodeNode/CodeEdge Pydantic models + tree-sitter dependencies
- [ ] 03-02-PLAN.md — TDD: ast_parser.py Python + TypeScript implementation + test_ast_parser.py

### Phase 4: Graph Builder
**Goal**: A verified module that constructs a fully resolved, PageRank-scored code graph from parsed nodes
**Depends on**: Phase 3
**Requirements**: GRAPH-01, GRAPH-02, GRAPH-03, GRAPH-04, GRAPH-05, TEST-04
**Success Criteria** (what must be TRUE):
  1. `build_graph(nodes, raw_edges)` returns a `nx.DiGraph` where every node has its original attributes preserved
  2. CALLS edges resolve to the correct target node IDs; unresolvable edges are dropped with a warning
  3. IMPORTS edges link caller files to all nodes in the imported target file
  4. Every node has `pagerank`, `in_degree`, and `out_degree` attributes populated
  5. All unit tests pass including edge resolution, PageRank presence, and degree correctness
**Plans**: 1 plan
Plans:
- [ ] 04-01-PLAN.md — TDD: graph_builder.py implementation + test_graph_builder.py (19 test cases)

### Phase 5: Embedder
**Goal**: CodeNode objects are embedded and stored so that semantic search and exact-name search are both available
**Depends on**: Phase 4
**Requirements**: EMBED-01, EMBED-02, EMBED-03, EMBED-04, EMBED-05, EMBED-06, STORE-01, STORE-02, STORE-03
**Success Criteria** (what must be TRUE):
  1. `embed_and_store()` completes without error and returns the count of nodes stored
  2. pgvector `code_embeddings` table exists with a `vector(1536)` column and ivfflat index
  3. SQLite FTS5 `code_fts` virtual table supports exact name search queries
  4. Re-running `embed_and_store()` on the same nodes upserts without duplicate rows
  5. NetworkX graph persists to SQLite and reconstructs correctly on load
**Plans**: 3 plans
Plans:
- [ ] 05-01-PLAN.md — graph_store.py: save_graph, load_graph, delete_nodes_for_files (SQLite persistence)
- [ ] 05-02-PLAN.md — embedder.py: init_pgvector_table, embed_and_store + openai to requirements.txt
- [ ] 05-03-PLAN.md — test_embedder.py (graph_store + embedder tests) + wire lifespan

### Phase 6: Pipeline
**Goal**: The full ingestion flow runs end-to-end from repo path to indexed graph in a single orchestrated call
**Depends on**: Phase 5
**Requirements**: PIPE-01, PIPE-02, PIPE-03, PIPE-04, PIPE-05
**Success Criteria** (what must be TRUE):
  1. `run_ingestion(repo_path, languages)` completes and returns an `IndexStatus` with non-zero node and edge counts
  2. File parsing executes concurrently (asyncio.gather + semaphore) with no race conditions on a multi-file repo
  3. Incremental re-index with `changed_files` re-parses only the listed files and removes their old nodes
  4. Status is queryable at any point during ingestion and reflects current progress
**Plans**: 3 plans
Plans:
- [ ] 06-01-PLAN.md — IndexStatus schema + pipeline.py (run_ingestion, _parse_concurrent, get_status)
- [ ] 06-02-PLAN.md — ast_parser.py thread-safety fix (per-call Parser construction)
- [ ] 06-03-PLAN.md — test_pipeline.py (5 mocked unit tests for all PIPE requirements)

### Phase 7: Index Endpoint
**Goal**: The ingestion pipeline is accessible over HTTP with non-blocking background execution
**Depends on**: Phase 6
**Requirements**: API-01, API-02, API-05, API-06, API-07, API-08
**Success Criteria** (what must be TRUE):
  1. `POST /index` returns `{status: "pending"}` immediately without waiting for ingestion to complete
  2. `GET /index/status?repo_path=...` reflects live ingestion progress (nodes/edges/files counts)
  3. `GET /health` returns `{status: "ok", version: "1.0.0"}`
  4. `DELETE /index?repo_path=...` removes all stored data for that repo
  5. CORS allows requests from `vscode-webview://*` and `http://localhost:3000`
**Plans**: 2 plans
Plans:
- [x] 07-01-PLAN.md — IndexRequest schema + delete helpers + index_router.py (POST /index, GET /index/status, DELETE /index)
- [x] 07-02-PLAN.md — Wire CORSMiddleware + router in main.py + live smoke test checkpoint

### Phase 7.1: Tech Debt Cleanup
**Goal**: Close the two non-critical integration gaps identified in the v1.0 audit — stale FTS5 rows on incremental re-index and missing backend Docker healthcheck
**Depends on**: Phase 7
**Requirements**: PIPE-03, STORE-03, EMBED-05, INFRA-01 (gap closure)
**Gap Closure:** Closes gaps from v1.0 audit (PIPE-03+STORE-03, INFRA-01-backend-healthcheck)
**Success Criteria** (what must be TRUE):
  1. Incremental re-index with `changed_files` removes stale FTS5 rows for renamed/removed functions
  2. `backend` service in `docker-compose.yml` has a `healthcheck` stanza using `GET /health`
  3. `delete_embeddings_for_files(file_paths, repo_path)` is implemented and tested in `embedder.py`
  4. Existing pipeline tests still pass after the change
**Plans**: 2 plans
Plans:
- [ ] 07.1-01-PLAN.md — delete_embeddings_for_files in embedder.py + pipeline wiring + tests
- [ ] 07.1-02-PLAN.md — Docker healthcheck stanza for backend service in docker-compose.yml

### Phase 8: Graph RAG
**Goal**: Retrieval produces structurally grounded context that is verifiably better than pure vector search, without requiring a live database
**Depends on**: Phase 7
**Requirements**: RAG-01, RAG-02, RAG-03, RAG-04, RAG-05, RAG-06, TEST-05, TEST-06
**Success Criteria** (what must be TRUE):
  1. `graph_rag_retrieve()` returns a ranked list of CodeNodes with an accompanying stats dict
  2. BFS expansion at hop depth 1 includes direct callers/callees; hop depth 2 extends one layer further
  3. Reranking scores correctly combine semantic score, PageRank weight, and in-degree normalization
  4. `max_nodes` limit is respected — result list never exceeds it
  5. All tests pass using an in-memory NetworkX fixture with no database connection required
**Plans**: 2 plans
Plans:
- [ ] 08-01-PLAN.md — Retrieval package: graph_rag.py with semantic_search, expand_via_graph, rerank_and_assemble, graph_rag_retrieve
- [ ] 08-02-PLAN.md — TDD: conftest fixtures (sample_graph, mock_embedder) + test_graph_rag.py (10 tests, no DB)

### Phase 9: Explorer Agent
**Goal**: A streaming LangChain agent generates grounded, cited answers from retrieved code context
**Depends on**: Phase 8
**Requirements**: AGNT-01, AGNT-02, AGNT-03, AGNT-04, AGNT-05
**Success Criteria** (what must be TRUE):
  1. Agent produces a streaming answer that references only file:line locations present in the retrieved context
  2. System prompt prevents fabricated citations — answers cite nodes or say they are uncertain
  3. Every LLM call appears as a trace in LangSmith when `LANGCHAIN_TRACING_V2=true`
  4. Context blocks are formatted as `--- [file_path:line_start-line_end] name (type) ---\n{signature}\n{docstring}\n{body_preview}`
**Plans**: 2 plans
Plans:
- [ ] 09-01-PLAN.md — Explorer Agent implementation: prompts.py + explorer.py + requirements
- [ ] 09-02-PLAN.md — test_explorer.py: format_context_block and explore_stream unit tests

### Phase 10: Query Endpoint
**Goal**: Streaming query responses are accessible over HTTP via a well-specified SSE protocol
**Depends on**: Phase 9
**Requirements**: API-03, API-04
**Success Criteria** (what must be TRUE):
  1. `POST /query` returns a `StreamingResponse` that emits `event: token` events with incremental content
  2. After the last token, a single `event: citations` event delivers the full citation list
  3. Stream closes with `event: done` carrying retrieval stats, or `event: error` on failure
  4. A curl client can consume the SSE stream and reconstruct the full answer from events
**Plans**: 2 plans
Plans:
- [ ] 10-01-PLAN.md — QueryRequest schema + query_router.py SSE endpoint + main.py wiring
- [ ] 10-02-PLAN.md — test_query_router.py: 9 unit tests for SSE event sequence and error paths

### Phase 11: VS Code Extension
**Goal**: A developer can open the Nexus sidebar, index a workspace, and ask a question that streams back a cited answer
**Depends on**: Phase 10
**Requirements**: EXT-01, EXT-02, EXT-03, EXT-04, CHAT-01, CHAT-02, CHAT-03, CHAT-04, CHAT-05, SSE-01, SSE-02, SSE-03
**Success Criteria** (what must be TRUE):
  1. Extension activates on VS Code startup and the Nexus icon appears in the activity bar
  2. Opening a workspace automatically triggers `IndexerService.indexWorkspace()`; the status bar shows indexing progress then "Ready — N nodes"
  3. Sending a question streams tokens into the chat panel in real-time with visible incremental rendering
  4. Citation chips appear after the answer completes and are clickable
  5. All styling uses VS Code CSS variables — no external CSS framework is shipped
**Plans**: 4 plans
Plans:
- [ ] 11-01-PLAN.md — Extension scaffold (package.json, tsconfigs, esbuild.js, media/nexus.svg, extension.ts stub)
- [ ] 11-02-PLAN.md — Extension host services (types.ts, BackendClient.ts, SseStream.ts, SidebarProvider.ts)
- [ ] 11-03-PLAN.md — React 18 webview UI (App.tsx, index.tsx, index.css with VS Code CSS variables)
- [ ] 11-04-PLAN.md — Wire extension.ts + full build + human verify checkpoint

### Phase 12: Highlighter
**Goal**: Cited file:line references from an answer are visibly highlighted in the VS Code editor
**Depends on**: Phase 11
**Requirements**: HIGH-01, HIGH-02
**Success Criteria** (what must be TRUE):
  1. Clicking a citation chip opens the referenced file and scrolls to the cited line
  2. Cited line ranges are decorated with the editor's `findMatchHighlightBackground` color
  3. Highlights clear automatically after 10 seconds or when the next query is submitted
**Plans**: 1 plan
Plans:
- [x] 12-01-PLAN.md — HighlightService.ts + wire SseStream/SidebarProvider/extension.ts

### Phase 13: File Watcher
**Goal**: The index stays current as the developer edits code, without requiring manual re-indexing
**Depends on**: Phase 12
**Requirements**: WATCH-01, WATCH-02, WATCH-03
**Success Criteria** (what must be TRUE):
  1. Saving a `.py`, `.ts`, `.tsx`, `.js`, or `.jsx` file triggers a re-index within 5 seconds
  2. Rapid successive saves are debounced — only one re-index request is sent after a 2-second quiet period
  3. The re-index request sends only the changed file path, not the full repo
**Plans**: 1 plan
Plans:
- [ ] 13-01-PLAN.md — FileWatcher.ts + BackendClient.indexFiles + wire extension.ts/SidebarProvider.ts

### Phase 14: RAGAS Eval
**Goal**: Quantitative evidence that graph-traversal RAG outperforms naive vector search, committed to the repo as a baseline
**Depends on**: Phase 13
**Requirements**: EVAL-01, EVAL-02, EVAL-03, EVAL-04, TEST-01
**Success Criteria** (what must be TRUE):
  1. `eval/golden_qa.json` contains 30 Q&A pairs covering routing, DI, middleware, background tasks, and security in the FastAPI repo
  2. `eval/run_ragas.py` runs successfully and produces a results file at `eval/results/ragas_results_{timestamp}.json`
  3. Results include per-question faithfulness, answer_relevancy, and context_precision scores
  4. A committed comparison shows graph-traversal RAG scores higher than naive vector-only RAG on at least one metric
  5. `pytest backend/tests/` passes with all unit tests green
**Plans**: 2 plans
Plans:
- [x] 14-01-PLAN.md — Golden Q&A dataset (eval/golden_qa.json, 30 pairs) + ragas/pandas to requirements.txt
- [ ] 14-02-PLAN.md — eval/run_ragas.py evaluation script + results directory + pytest verification

## Progress

**Execution Order:**
Phases execute in sequence: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13 → 14

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Infrastructure | 3/3 | Complete   | 2026-03-18 |
| 2. File Walker | 1/1 | Complete   | 2026-03-18 |
| 3. AST Parser | 2/2 | Complete   | 2026-03-18 |
| 4. Graph Builder | 1/1 | Complete   | 2026-03-18 |
| 5. Embedder | 3/3 | Complete   | 2026-03-18 |
| 6. Pipeline | 3/3 | Complete   | 2026-03-18 |
| 7. Index Endpoint | 2/2 | Complete   | 2026-03-18 |
| 7.1. Tech Debt Cleanup | 2/2 | Complete    | 2026-03-19 |
| 8. Graph RAG | 2/2 | Complete    | 2026-03-19 |
| 9. Explorer Agent | 2/2 | Complete    | 2026-03-19 |
| 10. Query Endpoint | 2/2 | Complete    | 2026-03-19 |
| 11. VS Code Extension | 4/4 | Complete    | 2026-03-19 |
| 12. Highlighter | 0/TBD | Complete    | 2026-03-19 |
| 13. File Watcher | 1/1 | Complete    | 2026-03-19 |
| 14. RAGAS Eval | 1/2 | In Progress | - |
