# Project: Nexus

## What This Is

Nexus is an AI-native codebase intelligence VS Code extension. It parses source code into an AST-based call graph (tree-sitter), indexes nodes with sqlite-vec + FTS5, and answers developer questions via graph-traversal RAG grounded in real code. It includes a LangGraph multi-agent team (Router → Debugger/Reviewer/Tester → Critic) with GitHub and Filesystem MCP integrations. V4 makes Nexus model and provider agnostic — users configure their own AI provider and models via VS Code settings, and the extension ships with a bundled backend sidecar for zero-setup installation.

## Core Value

Answers about code that cite real nodes and open the right file — not hallucinated summaries.

## Current Milestone: v4.1 AV-Safe Binary Distribution (Phase 37 complete — 2026-04-02)

**Goal:** Move the PyInstaller backend binary out of the VSIX and into GitHub Releases; SidecarManager downloads it once on first use per version and caches it permanently — eliminating the VS Marketplace AV false positive while preserving all existing behavior and UX.

**Target features:**
- SidecarManager: cache-first → download from GitHub Releases URL on miss → SHA256 verify → extract → run
- `vscode.window.withProgress` notification during first-use download (only UI change)
- SHA256 checksum manifest published alongside binaries in CI
- `bin/` removed from VSIX; VSIX shrinks from 62 MB → ~1.5 MB
- CI: `gh release upload` attaches tar.gz binaries to tagged Release (permanent, not workflow artifacts)
- Graceful failure: clear error message + manual download link if network fetch fails
- Zero behavioral change post-download — all features (chat, index, explain, review, test) identical

## Previous Milestone: v4.0 Model & Provider Agnostic + Zero-Setup Distribution (Shipped: 2026-04-01)

**Goal:** Make Nexus usable by anyone — users bring their own AI provider (OpenAI, Mistral, Anthropic, Ollama, Gemini), configure it in VS Code settings, and the extension works out-of-the-box with a bundled backend sidecar (no manual Python setup).

**Target features:**
- Bundled backend sidecar (PyInstaller binary) — extension spawns/kills it automatically on Mac and Windows
- `POST /api/config` dynamic config endpoint — providers, models, and API keys pushed from extension at activate time
- 5 providers: OpenAI, Mistral, Anthropic (chat only), Ollama (local, no key), Google Gemini
- Independent chat and embedding provider/model selection
- VS Code SecretStorage for API keys (`nexus.setApiKey` / `nexus.clearApiKey` commands)
- Hybrid settings UX: VS Code native settings for provider/model, webview shows status bar, commands for keys
- Embedding mismatch detection via `nexus_meta` table — warns and blocks chat until reindexed
- Reindex guard — chat always blocked until a valid index exists
- GitHub Actions build pipeline: PyInstaller jobs for Mac + Windows → `.vsix` package

## Previous Milestone: v3.0 Local-First Privacy (Shipped: 2026-03-25)

**Goal:** Move all index storage (code graph + vector embeddings) from the server into the user's workspace — no Postgres, no Docker, zero user data stored server-side.

**Shipped features:**
- Workspace-local graph store: SQLite at `.nexus/graph.db` inside user's repo
- Workspace-local vector store: `sqlite-vec` vec0 table in the same `.nexus/graph.db` file
- Postgres/pgvector dependency removed; `db/database.py` deleted
- Backend stateless — compute only (parsing + LLM calls), no storage
- Extension passes workspace db path in every request; all backend modules accept it as parameter

## Previous State: v2.0 Shipped

**v2.0 Multi-Agent Team shipped 2026-03-22.** All 11 phases (16–26) complete, 22/22 plans, 190 tests passing offline. Extension builds cleanly with esbuild dual-bundle.

**Shipped in v2.0:**
- LangGraph StateGraph with conditional routing (Router → specialist → Critic → MCP/done)
- Debugger: call graph traversal → ranked root cause suspects with anomaly scoring
- Reviewer: caller/callee context assembly → structured Finding schema
- Tester: framework detection → dependency-aware test generation → Filesystem MCP write
- Critic: LLM-as-judge quality gate with 2-loop hard cap
- GitHub MCP: post Reviewer findings as inline PR comments
- VS Code intent selector (Auto/Explain/Debug/Review/Test) + structured result panels (DebugPanel, ReviewPanel, TestPanel)

## Tech Stack

- **Backend:** FastAPI + Python, NetworkX (graph) + SQLite + sqlite-vec (local storage), PyInstaller (sidecar binary)
- **Orchestration:** LangGraph StateGraph with SqliteSaver checkpointing
- **Extension:** VS Code extension (TypeScript + React webview), esbuild dual-bundle
- **AI:** Provider-agnostic factory (`get_llm()` / `get_embedding_client()`) — OpenAI, Mistral, Anthropic, Ollama, Gemini configurable via VS Code settings
- **Distribution:** GitHub Actions CI, `vsce package`, SecretStorage for API keys
- **Eval:** RAGAS 0.4.3, 30-entry golden Q&A dataset

## Requirements

### Validated

- ✓ AST-based code graph ingestion — v1.0
- ✓ pgvector semantic search — v1.0
- ✓ Graph RAG (BFS expansion + reranking) — v1.0
- ✓ LangChain SSE streaming endpoint — v1.0
- ✓ VS Code extension with React webview — v1.0
- ✓ Citation highlighting in editor — v1.0
- ✓ File watcher incremental re-index — v1.0
- ✓ RAGAS evaluation harness (80% baseline) — v1.0

### Validated (v2.0)

- ✓ LangGraph StateGraph orchestrator with SqliteSaver checkpointing — v2.0
- ✓ Router agent: 100% accuracy on 12 labelled intent classification queries — v2.0
- ✓ Debugger agent: forward/backward graph traversal + anomaly scoring — v2.0
- ✓ Reviewer agent: caller/callee context assembly + Finding schema — v2.0
- ✓ Tester agent: framework detection + dependency-aware test generation — v2.0
- ✓ Critic agent: groundedness/relevance/actionability scoring + 2-loop hard cap — v2.0
- ✓ GitHub MCP: post findings as inline PR comments (mocked in tests) — v2.0
- ✓ Filesystem MCP: write test files with path traversal security — v2.0
- ✓ VS Code intent selector + debug/review/test structured rendering — v2.0
- ✓ Full V2 test suite: all agents with mock LLM + mock graph, V1 tests stay green — v2.0

### Validated (v4.0)

- ✓ Backend sidecar binary bundled with extension (Mac + Windows via PyInstaller) — v4.0
- ✓ SidecarManager spawns/kills backend process; polls `/health` before config push — v4.0
- ✓ `POST /api/config` replaces `.env` singleton — dynamic in-memory config — v4.0
- ✓ 5 providers in `model_factory.py`: OpenAI, Mistral, Anthropic, Ollama, Gemini — v4.0
- ✓ Independent chat provider+model and embedding provider+model configuration — v4.0
- ✓ API keys stored in VS Code SecretStorage; `nexus.setApiKey` / `nexus.clearApiKey` commands — v4.0
- ✓ VS Code native settings for provider/model; webview status bar shows active config — v4.0
- ✓ `nexus_meta` table in `graph.db` tracks embedding provider/model/dimensions for mismatch detection — v4.0
- ✓ Chat blocked with warning banner until index is valid; re-blocks on embedding model change — v4.0
- ✓ GitHub Actions pipeline: 2 parallel PyInstaller jobs (Mac + Windows) → `.vsix` — v4.0

### Validated (v4.1)

- ✓ SidecarManager downloads backend binary from GitHub Releases URL on cache miss — Phase 36
- ✓ SHA256 checksum verification before extraction — Phase 36
- ✓ `vscode.window.withProgress` download notification on first use per version — Phase 36
- ✓ Graceful failure with manual download fallback link — Phase 36

### Active (v4.1)

- [ ] `bin/` excluded from VSIX; build pipeline uploads binaries as GitHub Release assets
- [ ] SHA256 manifest generated in CI and published alongside binaries

### Out of Scope

- Real-time collaboration
- Cloud-hosted indexing
- Linux sidecar binary — deferred to v5+ (Mac + Windows only in v4)
- MCP protocol model server connection — deferred to v5+ (API key only in v4)
- Bug localisation accuracy benchmark — V5+
- Production deployment (Fly.io/Render) — V5+
- Java, Go language support — V5+
- CodeLens hotspot annotations — V5+
- Prompt versioning registry — V5+

## Context

V1.0 shipped: FastAPI ingestion → Postgres/pgvector + SQLite/NetworkX graph → LangChain LCEL SSE → VS Code extension. 93 tests passing. RAGAS eval baseline 80% (graph RAG +13% vs naive vector).

V2.0 shipped: LangGraph StateGraph orchestrator + 4 specialist agents + MCP tools + VS Code intent selector + structured result panels. 190 tests passing (all offline, mock LLM + mock graph).

**Codebase notes for v3:**
- Module paths: `app/agent/` (singular), `app/api/query_router.py`
- SQLite: `"data/nexus.db"` for graph, separate path for LangGraph SqliteSaver checkpointer
- Graph edges: `G.add_edge(u, v, type="CALLS")` — type attribute, not edge label
- `get_llm()` factory in `model_factory.py` — provider-agnostic, use this everywhere
- `document.execCommand('copy')` for clipboard in webview — `navigator.clipboard` blocked by VS Code WebKit CSP
- `langgraph-checkpoint-sqlite>=3.0.3` must be installed separately from langgraph

## Key Decisions

| Decision | Outcome | Status |
|----------|---------|--------|
| Mistral for both embedding + LLM | Cost-effective, self-hostable | ✓ Good |
| Graph RAG over naive vector-only | Better context assembly for interconnected code | ✓ Good |
| fetch + ReadableStream (not EventSource) for SSE | EventSource is GET-only; POST /query requires custom method | ✓ Good |
| Single TextEditorDecorationType per extension lifetime | Avoids VS Code decoration limit | ✓ Good |
| RAGAS 0.4.3 with pandas unpinned | Avoids dep conflict with transitive resolution | ✓ Good |

| LangGraph over raw LangChain LCEL | Supports conditional routing, checkpointing, retry loops | ✓ Good |
| SqliteSaver checkpointer (separate DB) | Reuses SQLite pattern, isolated from graph data | ✓ Good |
| get_llm() factory (not ChatOpenAI) | Provider-agnostic, consistent with V1 | ✓ Good |
| Critic loop cap = 2 (hard-coded) | Prevents infinite retry in production | ✓ Good |

| Config push via POST /api/config | Avoids restart on provider change; extension is single source of truth | — Pending |
| SecretStorage for API keys | Industry standard for VS Code credential storage; keys never touch disk | — Pending |
| PyInstaller sidecar (not hosted backend) | Preserves local-first privacy; user data never leaves device | — Pending |
| Anthropic chat-only (no embedding) | Anthropic has no public embedding API | ✓ Good |
| Mac + Windows only for v4 sidecar | Linux deferred; reduces build complexity for initial release | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd:transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-02 — Phase 36 (sidecar-download) complete; Phase 37 (release-pipeline) next*
