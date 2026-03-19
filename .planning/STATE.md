# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-18)

**Core value:** A developer can ask any question about a codebase and get a streamed, cited, graph-grounded answer with exact file:line highlights in VS Code.
**Current focus:** Phase 11 — VS Code Extension

## Current Position

Phase: 11 of 14 (VS Code Extension) — IN PROGRESS
Plan: 2 of 5 in current phase — COMPLETE
Status: Phase 11-vs-code-extension plan 02 complete — extension host services: types.ts, BackendClient.ts, SseStream.ts, SidebarProvider.ts
Last activity: 2026-03-19 — Plan 11-02 complete: four extension host TypeScript files; tsc --noEmit 0 errors

Progress: [████████░░] 78%

## Performance Metrics

**Velocity:**
- Total plans completed: 13
- Average duration: 7 min
- Total execution time: 1.19 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-infrastructure | 3 | 11 min | 4 min |
| 02-file-walker | 1 | 3 min | 3 min |
| 03-ast-parser | 2 | 5 min | 2.5 min |
| 04-graph-builder | 1 | 3 min | 3 min |
| 05-embedder | 3 | 10 min | 3.3 min |
| 06-pipeline | 3 | 40 min | 13.3 min |
| 07-index-endpoint | 2 | 7 min | 3.5 min |
| 07.1-tech-debt-cleanup | 2 | 2 min | 1 min |
| 08-graph-rag | 1 | 4 min | 4 min |

**Recent Trend:**
- Last 5 plans: 5 min, 3 min, 2 min, 5 min, 4 min
- Trend: baseline

*Updated after each plan completion*
| Phase 07.1-tech-debt-cleanup P01 | 2 | 2 tasks | 4 files |
| Phase 08-graph-rag P01 | 4 | 2 tasks | 2 files |
| Phase 08-graph-rag P02 | 2 | 1 tasks | 3 files |
| Phase 09-explorer-agent P01 | 2 min | 2 tasks | 5 files |
| Phase 09-explorer-agent P02 | 2 min | 1 tasks | 1 files |
| Phase 10-query-endpoint P01 | 2 | 3 tasks | 3 files |
| Phase 10-query-endpoint P02 | 3 | 2 tasks | 1 files |
| Phase 11-vs-code-extension P01 | 3 | 2 tasks | 8 files |
| Phase 11-vs-code-extension P02 | 2 | 2 tasks | 4 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- LangChain runnable (not LangGraph) for V1 — simpler, ships faster; full StateGraph in V2
- Implementation order follows PRD Section 12 — ensures always-demoable state at every phase
- pydantic_settings (separate package) required for pydantic v2 — BaseSettings was moved out of pydantic core
- lru_cache on get_settings() ensures single Settings instance across entire app (no repeated .env reads)
- conn.autocommit = True on psycopg2 required for CREATE EXTENSION DDL outside transaction
- data/* with !data/.gitkeep pattern commits directory structure without committing database files
- [Phase 01-infrastructure]: Host port 5433:5432 for postgres — avoids conflicts with local postgres on default 5432 (01-01)
- [Phase 01-infrastructure]: Bind mount ./data (not named volume) — SQLite files visible in project dir, survive docker compose down (01-01)
- [Phase 01-infrastructure]: psycopg2-binary (not psycopg2) — python:3.11-slim lacks libpq-dev/gcc for source build (01-01)
- [Phase 01-infrastructure]: CREATE EXTENSION IF NOT EXISTS vector in FastAPI lifespan — idempotent per-database activation (01-01)
- [Phase 01-infrastructure]: OPENAI_API_KEY set to sk-placeholder for Phase 1 — not needed until Phase 5 (Embedder) (01-03)
- [Phase 01-infrastructure]: All 4 INFRA requirements verified before Phase 2 gate — smoke test gate pattern established (01-03)
- [Phase 02-file-walker]: pathspec.GitIgnoreSpec.from_lines() used (not PathSpec factory) — correct class for gitignore semantics (02-01)
- [Phase 02-file-walker]: Two-pass os.walk — collect gitignore specs first, then filter files — ensures nested specs loaded before file evaluation (02-01)
- [Phase 02-file-walker]: os.walk used not Path.walk — project targets Python 3.11; Path.walk only available in Python 3.12+ (02-01)
- [Phase 02-file-walker]: Test assertions use Path.parts not substring match — pytest tmp_path dir name embeds test function name which may contain skip-dir strings (02-01)
- [Phase 03-ast-parser]: str | None union syntax used (not Optional[str]) — idiomatic Pydantic v2 + Python 3.11 target (03-01)
- [Phase 03-ast-parser]: tree-sitter pinned at exact versions == not >= — API changed significantly at 0.21 (captures() return type, Parser constructor, Language construction) (03-01)
- [Phase 03-ast-parser]: tree-sitter-typescript exposes language_typescript() and language_tsx() (not .language()) — separate function per dialect (03-01)
- [Phase 03-ast-parser]: embedding_text is a plain str field with default "" — populated by ast_parser.py, not auto-computed in the model (03-01)
- [Phase 03-ast-parser]: QueryCursor(Query).captures(node) — tree-sitter 0.25.x removed captures() from Query object; must wrap with QueryCursor (03-02)
- [Phase 03-ast-parser]: Query() constructor used not lang.query() — lang.query() deprecated in 0.25.x (03-02)
- [Phase 03-ast-parser]: raw_edges returned as (source_id, target_name, edge_type) tuples — Graph Builder (Phase 4) resolves target_name to full node_ids (03-02)
- [Phase 03-ast-parser]: IMPORTS edges use synthetic "rel_path::__module__" source_id — avoids requiring a file-level node in the graph (03-02)
- [Phase 04-graph-builder]: scipy added alongside networkx — nx.pagerank() delegates to _pagerank_scipy() in networkx 3.6; scipy must be explicitly installed (04-01)
- [Phase 04-graph-builder]: 3-pass construction order enforced — all nodes added in Pass 1 before any edges in Pass 2 to prevent bare attribute-less nodes (04-01)
- [Phase 04-graph-builder]: ::__module__ synthetic source_id fan-out — edges emitted from all real nodes in importing file to all real nodes in target file (Option A) (04-01)
- [Phase 05-embedder]: data/nexus.db single file for all repos; repo_path TEXT column scopes all queries — simpler than per-repo files (05-01)
- [Phase 05-embedder]: file_path promoted to dedicated column in graph_nodes — enables O(n) delete_nodes_for_files without JSON parsing (05-01)
- [Phase 05-embedder]: save_graph does full DELETE+INSERT replace (not incremental merge) — idempotent, simpler for V1 (05-01)
- [Phase 05-embedder]: json.dumps(attrs, default=str) safety net — handles any future non-serialisable types without crashing (05-01)
- [Phase 05-embedder]: Lazy OpenAI client init inside embed_and_store() body — prevents ValidationError on import when OPENAI_API_KEY absent (05-02)
- [Phase 05-embedder]: FTS5 upsert via DELETE + INSERT per batch — FTS5 virtual tables have no ON CONFLICT support (05-02)
- [Phase 05-embedder]: register_vector(conn) called per-connection — pgvector requires per-connection type registration, never global (05-02)
- [Phase 05-embedder]: Patch targets use app.ingestion.embedder namespace not origin module — from-imports bind at module load time
- [Phase 05-embedder]: FTS5 content='' removed — contentless mode silently breaks SELECT and DELETE on UNINDEXED columns
- [Phase 06-pipeline]: IndexStatus uses str | None union syntax (not Optional[str]) — consistent with Python 3.11 + pydantic v2 patterns (06-01)
- [Phase 06-pipeline]: asyncio.gather with return_exceptions=True — single parse failure does not cancel all other parses (06-01)
- [Phase 06-pipeline]: embed_and_store and save_graph wrapped in asyncio.to_thread — they are blocking I/O operations (06-01)
- [Phase 06-pipeline]: Module-level _status dict keyed by repo_path — readable via get_status() at any point during async execution (06-01)
- [Phase 06-pipeline]: Incremental path calls delete_nodes_for_files before re-parsing to avoid stale nodes in graph (06-01)
- [Phase 06-pipeline]: Parser instances constructed per parse_file() call — each asyncio.to_thread worker gets its own Parser, no shared mutable state (06-02)
- [Phase 06-pipeline]: Language singletons remain at module level — Language objects are read-only and safe to share; Parser objects have mutable state and must be per-call (06-02)
- [Phase 06-pipeline]: _parse_python() and _parse_typescript() accept parser as explicit parameter — keeps helpers pure, no global state dependency (06-02)
- [Phase 06-pipeline]: Patch all I/O stages at app.ingestion.pipeline.* namespace (not origin modules) — from-imports bind at load time
- [Phase 06-pipeline]: asyncio.run() used in tests to invoke async run_ingestion — no pytest-asyncio fixture needed for pipeline unit tests
- [Phase 07-index-endpoint]: BackgroundTasks.add_task passes run_ingestion directly — no asyncio.run() wrapper; Starlette awaits async functions correctly (07-01)
- [Phase 07-index-endpoint]: DELETE and GET routes use plain str repo_path query parameter — FastAPI maps plain str params to query params, Pydantic models to request bodies (07-01)
- [Phase 07-index-endpoint]: CORSMiddleware registered before include_router — Starlette middleware wraps full app stack; registration order matters for OPTIONS preflight interception (07-02)
- [Phase 07-index-endpoint]: allow_credentials=True omitted — combining wildcard allow_origin_regex with allow_credentials causes browser CORS rejection (07-02)
- [Phase 07-index-endpoint]: run_ingestion final status write guarded with repo_path presence check — prevents stale complete status written after concurrent DELETE (07-02)
- [Phase 07-index-endpoint]: delete_embeddings_for_repo collects pgvector ids before DELETE to build FTS5 target set — single connection traversal (07-01)
- [Phase 07.1-tech-debt-cleanup]: CMD array format used (not CMD-SHELL) for backend healthcheck — exec form, no shell interpretation overhead (07.1-02)
- [Phase 07.1-tech-debt-cleanup]: start_period: 15s on backend — uvicorn + postgres init can take 2-8s; backend needs more than postgres (10s) since it depends on postgres being up first (07.1-02)
- [Phase 07.1-tech-debt-cleanup]: curl -f http://localhost:8000/health reuses existing GET /health endpoint in main.py — no new code or infra required (07.1-02)
- [Phase 07.1-tech-debt-cleanup]: Plain WHERE file_path IN (...) for FTS5 delete — MATCH syntax invalid on UNINDEXED columns (07.1-01)
- [Phase 07.1-tech-debt-cleanup]: delete_embeddings_for_files empty-list guard returns before any DB connection opened — no-op is safe and zero-cost (07.1-01)
- [Phase 07.1-tech-debt-cleanup]: Incremental path calls both delete_nodes_for_files and delete_embeddings_for_files before re-parsing — ensures all three stores cleaned together (07.1-01)
- [Phase 08-graph-rag]: semantic_search returns (node_id, score) pairs not CodeNode objects — code_embeddings table lacks signature/docstring/body_preview; CodeNode hydration happens in graph_rag_retrieve via G.nodes (08-01)
- [Phase 08-graph-rag]: nx.ego_graph(undirected=True) for bidirectional BFS — covers both predecessors (callers) and successors (callees) in one call; nx.bfs_tree only follows outgoing edges on DiGraph (08-01)
- [Phase 08-graph-rag]: nx.subgraph_view() zero-copy edge-type filtering — avoids graph copy overhead when restricting BFS traversal to specific edge types (08-01)
- [Phase 08-graph-rag]: Lazy OpenAI client init inside semantic_search body — same pattern as embedder.py; prevents ValidationError on import when OPENAI_API_KEY absent (08-01)
- [Phase 08-graph-rag]: max_in_degree guard (max(in_degrees) if in_degrees else 1) prevents ZeroDivisionError when all expanded nodes have in_degree 0 (08-01)
- [Phase 08-graph-rag]: Patch register_vector at app.retrieval.graph_rag namespace for full test isolation from DB
- [Phase 08-graph-rag]: max_in_degree guard changed to (max(in_degrees) if in_degrees else 0) or 1 to handle all-zeros case in rerank_and_assemble
- [Phase 09-explorer-agent]: Lazy _get_chain() init prevents ValidationError when OPENAI_API_KEY absent at import time (09-01)
- [Phase 09-explorer-agent]: tracing_v2_enabled wraps entire astream() call not per-token to avoid trace explosion in LangSmith (09-01)
- [Phase 09-explorer-agent]: Inject _chain directly via explorer_mod._chain = mock_chain to bypass _get_chain() LCEL composition — avoids needing to mock ChatPromptTemplate (09-02)
- [Phase 09-explorer-agent]: asyncio.run() in explorer tests (not pytest-asyncio) — consistent with test_pipeline.py pattern, no extra dependencies (09-02)
- [Phase 09-explorer-agent]: AIMessageChunk(content="") as first fixture yield to exercise empty-chunk filtering guard in explore_stream (09-02)
- [Phase 10-query-endpoint]: HTTPException raised before StreamingResponse — headers not yet sent; only safe error point for POST /query (10-01)
- [Phase 10-query-endpoint]: asyncio.to_thread wraps _get_graph and graph_rag_retrieve — both do blocking SQLite/pgvector I/O (10-01)
- [Phase 10-query-endpoint]: app.state.graph_cache dict initialized in lifespan — lazy per-repo nx.DiGraph cache avoids repeated SQLite reads (10-01)
- [Phase 10-query-endpoint]: patch init_db/init_pgvector_table at app.main namespace to decouple TestClient from postgres (10-02)
- [Phase 10-query-endpoint]: r.read() inside client.stream() context required to materialize SSE body before httpx connection closes (10-02)
- [Phase 11-vs-code-extension]: esbuild.js wraps webview rebuild in try/catch — gracefully skips missing entry point at scaffold stage, fails fast on extension host errors
- [Phase 11-vs-code-extension]: fetch + ReadableStream used in SseStream (not EventSource) — EventSource is GET-only, POST /query requires custom method
- [Phase 11-vs-code-extension]: DOM lib added to extension tsconfig.json — fetch/setInterval types unavailable without it even in Node 18+ extension host

### Pending Todos

None yet.

### Blockers/Concerns

None yet.

## Session Continuity

Last session: 2026-03-19
Stopped at: Completed 11-02-PLAN.md — extension host services: types.ts discriminated unions, BackendClient HTTP polling, SseStream fetch SSE consumer, SidebarProvider webview bridge
Resume file: None
