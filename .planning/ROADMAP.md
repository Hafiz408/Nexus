# Roadmap: Nexus

## Milestones

- ✅ **v1.0 MVP** — Phases 1-15 (shipped 2026-03-21) — [archive](.planning/milestones/v1.0-ROADMAP.md)
- ✅ **v2.0 Multi-Agent Team** — Phases 16-26 (shipped 2026-03-22) — [archive](.planning/milestones/v2.0-ROADMAP.md)
- ✅ **v3.0 Local-First Privacy** — Phases 27-29 (shipped 2026-03-25) — [archive](.planning/milestones/v3.0-ROADMAP.md)
- ✅ **v4.0 Model & Provider Agnostic + Zero-Setup Distribution** — Phases 30-35 (shipped 2026-04-01) — [archive](.planning/milestones/v4.0-ROADMAP.md)
- ✅ **v4.1 AV-Safe Binary Distribution** — Phases 36-37 (shipped 2026-04-02) — [archive](.planning/milestones/v4.1-ROADMAP.md)

## Phases

<details>
<summary>✅ v1.0 MVP (Phases 01-15) — SHIPPED 2026-03-21</summary>

> Phases 01-07 were foundation (infrastructure, AST parser, graph builder, embedder, ingestion pipeline, FTS5 search). Phase directories cleaned up; 07.1 onward tracked in `.planning/phases/`.

- [x] Phase 07.1: tech-debt-cleanup — FTS5/pgvector deletion + Docker healthcheck
- [x] Phase 08: graph-rag — 3-step retrieval pipeline (vector → BFS → rerank)
- [x] Phase 09: explorer-agent — LangChain LCEL SSE streaming agent
- [x] Phase 10: query-endpoint — POST /query SSE endpoint + lazy graph cache
- [x] Phase 11: vs-code-extension — Extension scaffold, services, webview UI, wiring
- [x] Phase 12: highlighter — Citation highlighting in editor
- [x] Phase 13: file-watcher — Incremental re-index on file save
- [x] Phase 14: ragas-eval — RAGAS golden dataset + evaluation runner (80% baseline)
- [x] Phase 15: extension-ui-revamp — Textarea UX, citation chips, progress bar

</details>

<details>
<summary>✅ v2.0 Multi-Agent Team (Phases 16-26) — SHIPPED 2026-03-22</summary>

- [x] **Phase 16: config-v2** — V2 environment configuration with safe defaults (completed 2026-03-21)
- [x] **Phase 17: router-agent** — Intent classifier with 100% accuracy gate before agent work begins (completed 2026-03-21)
- [x] **Phase 18: debugger-agent** — Call graph traversal + anomaly-scored suspect ranking (completed 2026-03-21)
- [x] **Phase 19: reviewer-agent** — Caller/callee context assembly + structured Finding schema (completed 2026-03-21)
- [x] **Phase 20: tester-agent** — Framework detection + dependency-aware test generation (completed 2026-03-21)
- [x] **Phase 21: critic-agent** — LLM-as-judge quality gate with 2-loop hard cap (completed 2026-03-21)
- [x] **Phase 22: orchestrator** — LangGraph StateGraph wiring all agents with checkpointing (completed 2026-03-21)
- [x] **Phase 23: mcp-tools** — GitHub PR commenting + Filesystem safe test file writing (completed 2026-03-21)
- [x] **Phase 24: query-endpoint-v2** — Wire orchestrator into /query; confirm zero V1 regressions (completed 2026-03-21)
- [x] **Phase 25: extension-intent-selector** — 5-option intent selector UI + intent_hint wiring (completed 2026-03-21)
- [x] **Phase 26: extension-result-rendering** — Structured debug/review/test result panels (completed 2026-03-22)

</details>

<details>
<summary>✅ v3.0 Local-First Privacy (Phases 27-29) — SHIPPED 2026-03-25</summary>

- [x] **Phase 27: wire-review-test-e2e** — Wire target_node_id through extension→backend; fix reviewer/tester crashes; activate MCP call site (completed 2026-03-25)
- [x] **Phase 28: local-first-privacy** — Storage migration: sqlite-vec replaces pgvector; workspace .nexus/graph.db; backend stateless; Postgres/Docker removed (completed 2026-03-25)
- [x] **Phase 29: extension-integration** — db_path threaded through all BackendClient methods; SidebarProvider derives and sends workspace db path per request (completed 2026-03-25)

</details>

<details>
<summary>✅ v4.0 Model & Provider Agnostic + Zero-Setup Distribution (Phases 30-35) — SHIPPED 2026-04-01</summary>

- [x] **Phase 30: backend-config** — Dynamic in-memory config endpoint + health endpoint + 5-provider model factory (completed 2026-04-01)
- [x] **Phase 31: embedding-safety** — nexus_meta table in graph.db tracks embedding provider/model; mismatch detection on config push (completed 2026-04-01)
- [x] **Phase 32: extension-settings-keys** — VS Code settings for provider/model selection + SecretStorage API key commands + config push to backend (completed 2026-04-01)
- [x] **Phase 33: sidecar-manager** — SidecarManager spawns/kills/polls bundled backend binary; output channel; dev-mode skip (completed 2026-04-01)
- [x] **Phase 34: reindex-guard-status** — Reindex guard blocks chat until valid index exists; webview status bar shows active config and index state (completed 2026-04-01)
- [x] **Phase 35: build-pipeline** — PyInstaller Mac + Windows binaries; GitHub Actions CI builds and packages into .vsix (completed 2026-04-01)

</details>

## v4.1 AV-Safe Binary Distribution

**Milestone Goal:** Move the PyInstaller backend binary out of the VSIX and into GitHub Releases; SidecarManager downloads it once on first use per version and caches it permanently — eliminating the VS Marketplace AV false positive while preserving all existing behavior and UX.

- [x] **Phase 36: sidecar-download** — SidecarManager downloads backend binary from GitHub Releases on cache miss, verifies SHA256, shows progress UI, and handles failure gracefully (completed 2026-04-01)
- [x] **Phase 37: release-pipeline** — CI uploads platform binaries and SHA256 manifest as GitHub Release assets; bin/ excluded from VSIX (completed 2026-04-01)

## Phase Details

### Phase 30: backend-config
**Goal**: Backend accepts dynamic provider/model/key configuration at runtime, replacing the static `.env` singleton, and exposes a health endpoint for readiness polling
**Depends on**: Phase 29
**Requirements**: CONF-02, CONF-03, CONF-04
**Success Criteria** (what must be TRUE):
  1. `POST /api/config` accepts provider, model, and API key fields and stores them in memory without restarting the process
  2. All LLM and embedding calls use the in-memory config rather than environment variables loaded at startup
  3. `model_factory.py` instantiates a working client for all 5 chat providers (OpenAI, Mistral, Anthropic, Ollama, Gemini) and all 4 embedding providers (OpenAI, Mistral, Ollama, Gemini)
  4. `GET /health` returns HTTP 200 when the backend process is ready to serve requests
**Plans**: 1 plan
Plans:
- [x] 37-01-PLAN.md — GitHub Release assets and binary-free VSIX

### Phase 31: embedding-safety
**Goal**: Backend detects when the active embedding model has changed relative to the existing index, so the extension can warn users before stale vectors are used for chat
**Depends on**: Phase 30
**Requirements**: EMBD-01, EMBD-02
**Success Criteria** (what must be TRUE):
  1. A `nexus_meta` table in `graph.db` persists the embedding provider, model name, and vector dimensions written during the last successful index
  2. When `POST /api/config` is called with a different embedding provider or model than what is stored in `nexus_meta`, the response includes `reindex_required: true`
  3. When the embedding config matches `nexus_meta`, the response does not set `reindex_required`
**Plans**: 1 plan
Plans:
- [ ] 37-01-PLAN.md — GitHub Release assets and binary-free VSIX

### Phase 32: extension-settings-keys
**Goal**: Users configure their AI provider and model selections in VS Code native settings and store API keys securely via commands; the extension pushes the full config to the backend on activate and on every settings change
**Depends on**: Phase 30
**Requirements**: PROV-01, PROV-02, PROV-03, PROV-04, PROV-05, KEYS-01, KEYS-02, KEYS-03, CONF-01
**Success Criteria** (what must be TRUE):
  1. VS Code Settings UI shows dropdowns for chat provider and embedding provider, free-text fields for chat model and embedding model, and a text field for Ollama base URL
  2. Running `Nexus: Set API Key` prompts for a provider name and key, stores the key in VS Code SecretStorage, and never writes it to `settings.json` or any file on disk
  3. Running `Nexus: Clear API Key` removes the stored key for the chosen provider from SecretStorage
  4. On extension activate and on any settings change, the extension assembles provider, model, and API key values and sends them to `POST /api/config`
**Plans**: 1 plan
Plans:
- [ ] 37-01-PLAN.md — GitHub Release assets and binary-free VSIX

### Phase 33: sidecar-manager
**Goal**: The extension automatically spawns the bundled backend binary on activate and shuts it down on deactivate, with no manual Python setup required from the user
**Depends on**: Phase 32
**Requirements**: SIDE-01, SIDE-02, SIDE-03, SIDE-04, SIDE-05
**Success Criteria** (what must be TRUE):
  1. Installing the extension and opening a workspace starts the backend process automatically with no terminal commands from the user
  2. Backend stdout and stderr appear in a VS Code Output Channel named "Nexus Backend"
  3. The extension polls `GET /health` after spawning and does not push config until the backend responds with HTTP 200
  4. If a process is already listening on `localhost:8000` when the extension activates, the extension skips spawning (dev mode compatibility)
  5. Deactivating or closing VS Code terminates the spawned backend process
**Plans**: 1 plan
Plans:
- [ ] 37-01-PLAN.md — GitHub Release assets and binary-free VSIX

### Phase 34: reindex-guard-status
**Goal**: Chat is reliably blocked until a valid index exists and whenever an embedding model change makes the current index stale; the sidebar surface shows the active config and index state at a glance
**Depends on**: Phase 33, Phase 31
**Requirements**: EMBD-03, EMBD-04, EMBD-05, VIEW-01, VIEW-02, VIEW-03, VIEW-04
**Success Criteria** (what must be TRUE):
  1. When a user changes the embedding provider or model in VS Code settings, a warning notification appears before the change is applied, informing them that a reindex will be required
  2. The chat input is disabled and a warning banner is shown whenever `reindex_required` is true, until a successful index completes
  3. The chat input is disabled on first install until the user has run at least one successful index
  4. The sidebar status bar shows the active chat provider/model and embedding provider/model
  5. The sidebar shows a `[Configure Keys]` button that triggers `nexus.setApiKey` and an index status indicator (valid / reindex required / never indexed)
**Plans**: 1 plan
Plans:
- [ ] 37-01-PLAN.md — GitHub Release assets and binary-free VSIX

### Phase 35: build-pipeline
**Goal**: The extension ships as a single `.vsix` file containing PyInstaller binaries for Mac and Windows; a GitHub Actions workflow builds and packages them automatically
**Depends on**: Phase 34
**Requirements**: SIDE-06
**Success Criteria** (what must be TRUE):
  1. GitHub Actions runs two parallel PyInstaller jobs (one Mac runner, one Windows runner) and produces platform-specific backend binaries
  2. The `.vsix` package includes both binaries and the extension activates correctly on Mac and Windows without any Python installation
  3. The build pipeline completes successfully on a clean runner with no manual steps
**Plans**: 1 plan
Plans:
- [ ] 37-01-PLAN.md — GitHub Release assets and binary-free VSIX

### Phase 36: sidecar-download
**Goal**: SidecarManager resolves the backend binary via a cache-first strategy — using a locally cached copy when available and downloading from GitHub Releases on a version miss — with SHA256 integrity verification, a progress notification on first use, and graceful failure with a manual fallback link
**Depends on**: Phase 35
**Requirements**: DIST-01, DIST-02, DIST-03, DIST-04, DIST-05, PRES-01, PRES-02, PRES-03
**Success Criteria** (what must be TRUE):
  1. A user who installs the extension for the first time sees a VS Code progress notification ("Downloading Nexus backend...") and the backend starts automatically with no manual steps
  2. On all subsequent activations for the same version, the extension starts the backend from the `globalStorage/<version>/` cache with no network call and no noticeable delay
  3. If the download fails (network error, 404, or timeout), the user sees a clear error notification with a direct link to the GitHub Releases page for manual download
  4. A checksum mismatch between the downloaded archive and the published SHA256 value aborts activation with an error; the corrupted file is not extracted
  5. All existing features (chat, index, explain, debug, review, test) work identically after the binary is downloaded and cached; if a backend is already running on the configured port, spawning is skipped
**Plans**: 2 plans
Plans:
- [x] 36-01-PLAN.md — Install @types/node + add _fetchChecksum, _downloadAndVerify, _showDownloadError helpers
- [x] 36-02-PLAN.md — Refactor _ensureExtracted for GitHub Releases download + wire error handling in start()
**UI hint**: yes

### Phase 37: release-pipeline
**Goal**: The CI pipeline attaches platform-specific backend archives and a SHA256 checksum manifest as assets on the tagged GitHub Release, and the published VSIX contains no native binaries
**Depends on**: Phase 36
**Requirements**: DIST-06, DIST-07, DIST-08
**Success Criteria** (what must be TRUE):
  1. The `.vsix` published to the VS Marketplace contains no files under `bin/`; file size drops from ~62 MB to ~1.5 MB
  2. A tagged GitHub Release contains `nexus-backend-mac.tar.gz`, `nexus-backend-win.tar.gz`, and `checksums.sha256` as Release assets (not expiring workflow artifacts)
  3. The `checksums.sha256` manifest lists the SHA256 hash for each platform binary and can be used to verify a downloaded archive
**Plans**: 1 plan
Plans:
- [ ] 37-01-PLAN.md — GitHub Release assets and binary-free VSIX

## Progress

**v4.0 Execution Order (COMPLETE):** 30 → 31 → 32 → 33 → 34 → 35

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 30. backend-config | — | Complete | 2026-04-01 |
| 31. embedding-safety | — | Complete | 2026-04-01 |
| 32. extension-settings-keys | — | Complete | 2026-04-01 |
| 33. sidecar-manager | — | Complete | 2026-04-01 |
| 34. reindex-guard-status | — | Complete | 2026-04-01 |
| 35. build-pipeline | — | Complete | 2026-04-01 |

**v4.1 Execution Order:** 36 → 37

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 36. sidecar-download | 2/2 | Complete    | 2026-04-01 |
| 37. release-pipeline | 1/1 | Complete    | 2026-04-02 |

---
*v3.0 shipped: 2026-03-25*
*v4.0 shipped: 2026-04-01*
*v4.1 roadmap created: 2026-04-01*
