# Milestones

## v1.0 MVP (Shipped: 2026-03-21)

**Phases completed:** 10 phases, 16 plans, 0 tasks

**Key accomplishments:**
- Graph RAG 3-step pipeline: vector search → BFS graph expansion → score reranking (Phase 08)
- LangChain LCEL SSE streaming explorer agent with LangSmith tracing (Phase 09)
- POST /query SSE endpoint with lazy per-repo graph cache (Phase 10)
- VS Code extension: esbuild dual-bundle, fetch+ReadableStream SSE consumer, React 18 webview (Phase 11)
- Citation highlighting via TextEditorDecorationType + file watcher incremental re-index (Phases 12-13)
- RAGAS evaluation harness: 30-entry golden dataset, 80% baseline (8/10) (Phase 14)
- Extension UI revamp: auto-grow textarea, citation chips with expand, indeterminate progress bar (Phase 15)

**Known gaps:**
- Q5/Q9 RAGAS eval failures (embedding similarity: "agents" ≠ "members" in vector space; query expansion needed)
- Docker image rebuild needed for ast_parser.py body_preview fix to survive container restart

---


## v2.0 Multi-Agent Team (Shipped: 2026-03-22)

**Phases completed:** 11 phases (16–26), 22 plans, 190 tests passing

**Key accomplishments:**
- LangGraph StateGraph orchestrator with SqliteSaver checkpointing — Router → specialist → Critic → MCP/done (Phases 22, 24)
- Router agent: 100% accuracy on 12 labelled intent classification queries; intent_hint bypass path (Phase 17)
- Debugger agent: BFS call graph traversal + 5-factor anomaly scoring + top-5 suspects + impact radius (Phase 18)
- Reviewer agent: 1-hop caller/callee context assembly + structured Finding schema + groundedness post-filter (Phase 19)
- Tester agent: marker-file framework detection + CALLS-edge mock targets + deterministic test file path derivation (Phase 20)
- Critic agent: 0.40×groundedness + 0.35×relevance + 0.25×actionability + 2-loop hard cap (Phase 21)
- GitHub MCP (tenacity retry + 422-skip) + Filesystem MCP (path traversal guard + extension allowlist) (Phase 23)
- VS Code intent selector (5 pills) + DebugPanel + ReviewPanel + TestPanel structured result rendering (Phases 25–26)

**Stats:** 87 files changed, ~9,600 LOC, 4-day build (2026-03-18 → 2026-03-22)

---


## v3.0 Local-First Privacy (Shipped: 2026-03-25)

**Phases completed:** 3 phases (27–29)

**Key accomplishments:**
- Workspace-local storage: sqlite-vec + SQLite at .nexus/graph.db — Postgres/Docker fully removed
- Backend made stateless — compute only, no storage
- db_path threaded through all API endpoints and BackendClient methods
- target_node_id wired extension→backend; reviewer and tester E2E flows fixed

---

## v4.0 Model & Provider Agnostic + Zero-Setup Distribution (Shipped: 2026-04-01)

**Phases completed:** 6 phases (30–35)

**Key accomplishments:**
- POST /api/config dynamic config replaces .env singleton — 5 providers (OpenAI, Mistral, Anthropic, Ollama, Gemini)
- SidecarManager: auto-spawn/kill PyInstaller binary, lockfile multi-window reuse, /health polling
- SecretStorage API key management — keys never written to disk or settings.json
- nexus_meta mismatch detection + chat guard until valid index exists
- GitHub Actions pipeline: parallel Mac + Windows PyInstaller builds → .vsix

---

## v4.1 AV-Safe Binary Distribution (Shipped: 2026-04-02)

**Phases completed:** 2 phases (36–37)

**Key accomplishments:**
- Cache-first binary resolution from globalStorage/<version>/ — offline after first download per version
- SHA256 checksum verification before extraction
- vscode.window.withProgress download notification on first use
- VSIX shrinks from ~62 MB to ~1.5 MB; bin/ excluded from package
- CI uploads tar.gz + checksums.sha256 as permanent GitHub Release assets

---
