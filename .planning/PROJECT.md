# Nexus V1

## What This Is

Nexus is a VS Code extension backed by a FastAPI multi-agent backend that parses a codebase into a structural **code graph** (nodes = functions/classes, edges = calls/imports/inheritance) using tree-sitter AST analysis, then uses **graph-traversal RAG** to answer questions grounded in the actual code structure — not just text similarity. V1 ships one complete, demoable feature: the **Explorer agent** — ask any question about how the codebase works, get a cited, grounded answer with file:line references and highlighted code in the editor.

## Core Value

A developer can open any Python or TypeScript repo in VS Code, ask a natural-language question about how the code works, and receive a streamed, cited answer with exact file:line highlights — grounded in the actual code graph, not hallucinated.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Docker Compose brings up PostgreSQL + pgvector with health checks
- [ ] `file_walker.py` traverses a repo respecting `.gitignore`, skips noise directories, returns file list with language detection
- [ ] `ast_parser.py` parses Python and TypeScript files via tree-sitter, extracting CodeNode objects (functions, classes, methods) with signatures, docstrings, body previews, and complexity
- [ ] `graph_builder.py` builds a NetworkX DiGraph from nodes + raw edges, resolves CALLS/IMPORTS/INHERITS edges, computes PageRank
- [ ] `embedder.py` embeds CodeNode objects into pgvector (1536-dim) and SQLite FTS5, with batch processing and upsert logic
- [ ] `pipeline.py` orchestrates the full ingestion flow with concurrency (asyncio.gather + semaphore) and incremental re-index support
- [ ] `POST /index` endpoint exposes pipeline via FastAPI BackgroundTasks, returns immediately
- [ ] `GET /index/status` returns IndexStatus with node/edge/file counts
- [ ] `graph_rag.py` implements 3-step graph-traversal RAG: semantic seed search → N-hop BFS expansion → rerank with PageRank scoring
- [ ] `explorer.py` is a LangChain streaming agent with LangSmith tracing that generates grounded answers with file:line citations
- [ ] `POST /query` SSE endpoint streams token events → citations event → done event
- [ ] VS Code extension sidebar with React chat UI, SSE token streaming, and citation chips
- [ ] `Highlighter.ts` decorates cited file:line ranges in the VS Code editor
- [ ] `FileWatcher.ts` watches for file saves and triggers incremental re-index within 5 seconds
- [ ] RAGAS evaluation runner with 30 golden Q&A pairs against the FastAPI repo, baseline scores committed

### Out of Scope

- Debugger, Reviewer, Tester, Critic agents — V2 multi-agent StateGraph
- GitHub MCP, Filesystem MCP — V2
- Java, Go language support — V2
- CI/CD GitHub Actions — V2
- Production deployment (Fly.io/Render) — V2
- Full LangGraph StateGraph — V1 uses simple LangChain runnable

## Context

- **Tech Stack (Backend):** Python 3.11, FastAPI 0.115, LangChain 0.3, LangSmith, tree-sitter (Python + TypeScript bindings), NetworkX 3.x, pgvector via psycopg2, SQLite FTS5 via aiosqlite, OpenAI text-embedding-3-small + gpt-4o-mini, RAGAS, pytest
- **Tech Stack (Extension):** TypeScript 5.x, webpack, React 18 (Webview), native fetch + EventSource, vsce
- **Infrastructure:** Docker Compose, PostgreSQL 16 + pgvector, pydantic-settings for all secrets
- **Key architectural insight:** Graph-traversal RAG expands semantic seed nodes N hops through the code graph to retrieve callers/callees/imports — finding structurally related code that pure vector search misses
- **Non-negotiables:** All LLM calls traced in LangSmith; no hardcoded secrets; incremental re-index from day one; SSE streaming required; `graph_rag.py` must be testable without a DB; CORS must allow `vscode-webview://*`
- **Demo target:** FastAPI repo (100k+ LOC) indexed in under 2 minutes, "How does dependency injection work?" returns cited, streaming answer

## Constraints

- **Tech stack:** Fully specified in PRD — do not deviate without explicit reason
- **Security:** No hardcoded API keys anywhere; all secrets via `.env` + pydantic-settings; `.env` must never be committed
- **Node IDs:** Format `"file_path::name"` — must be consistent across all modules
- **SSE format:** Specific event/data format per PRD Section 4.3 — extension parses this exactly
- **Git branch:** `feature/v1` — push after every step commit

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| LangChain runnable (not LangGraph) for V1 | Simpler, ships faster; full StateGraph in V2 | — Pending |
| pgvector for semantic search | Native PostgreSQL integration, production-proven | — Pending |
| SQLite FTS5 for exact search | Zero infrastructure overhead, built-in | — Pending |
| NetworkX in-memory graph | Fast traversal, serializable to SQLite for persistence | — Pending |
| tree-sitter for AST parsing | Multi-language, battle-tested, Python bindings available | — Pending |
| OpenAI text-embedding-3-small | 1536-dim, cost-effective, configurable via env | — Pending |
| Implementation order from PRD Section 12 | Always-demoable state — each step builds on verified previous | — Pending |

---
*Last updated: 2026-03-18 after initialization*
