# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-18)

**Core value:** A developer can ask any question about a codebase and get a streamed, cited, graph-grounded answer with exact file:line highlights in VS Code.
**Current focus:** Phase 5 — Embedder

## Current Position

Phase: 5 of 14 (Embedder)
Plan: 2 of 3 in current phase
Status: In progress — Plan 05-02 complete
Last activity: 2026-03-18 — Plan 05-02 complete: embedder.py implemented with init_pgvector_table and embed_and_store (lazy OpenAI client, pgvector ON CONFLICT upsert, FTS5 DELETE+INSERT); all 47 tests pass

Progress: [██░░░░░░░░] 23%

## Performance Metrics

**Velocity:**
- Total plans completed: 8
- Average duration: 3 min
- Total execution time: 0.37 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-infrastructure | 3 | 11 min | 4 min |
| 02-file-walker | 1 | 3 min | 3 min |
| 03-ast-parser | 2 | 5 min | 2.5 min |
| 04-graph-builder | 1 | 3 min | 3 min |
| 05-embedder | 2 | 5 min | 2.5 min |

**Recent Trend:**
- Last 5 plans: 3 min, 5 min, 3 min, 2 min, 3 min
- Trend: baseline

*Updated after each plan completion*

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

### Pending Todos

None yet.

### Blockers/Concerns

None yet.

## Session Continuity

Last session: 2026-03-18
Stopped at: Completed 05-02-PLAN.md — embedder.py implemented with init_pgvector_table and embed_and_store; lazy OpenAI client, pgvector ON CONFLICT upsert, FTS5 DELETE+INSERT; all 47 tests pass
Resume file: None
