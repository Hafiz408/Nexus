# Requirements: Nexus

**Defined:** 2026-03-26 (v4.0) | **Updated:** 2026-04-01 (v4.1 added)
**Current Milestone:** v4.1 — AV-Safe Binary Distribution
**Core Value:** Answers about code that cite real nodes and open the right file — not hallucinated summaries.

## v4.1 Requirements

### Binary Download & Distribution

- [x] **DIST-01**: User installs the extension and the backend binary is downloaded automatically from GitHub Releases on first activation — no manual download required
- [x] **DIST-02**: Once downloaded for a given version, the binary is served from `globalStorage/<version>/` cache on all subsequent activations without any network call
- [x] **DIST-03**: User sees a VS Code progress notification ("Downloading Nexus backend…") while the binary is being fetched on first use per version
- [x] **DIST-04**: If the binary download fails (network error, 404, timeout), the user sees a clear error notification with a direct link to manually download the binary from GitHub Releases
- [x] **DIST-05**: The downloaded archive is verified against a SHA256 checksum published in the GitHub Release before extraction; a checksum mismatch aborts activation with an error
- [x] **DIST-06**: The VSIX published to the VS Marketplace contains no native binaries; `bin/` is excluded from packaging
- [x] **DIST-07**: CI attaches platform-specific backend tar.gz archives (`nexus-backend-mac.tar.gz`, `nexus-backend-win.tar.gz`) as assets on the tagged GitHub Release for each version
- [x] **DIST-08**: CI generates a `checksums.sha256` manifest file and uploads it as a GitHub Release asset alongside the binaries

### Behavioral Preservation

- [x] **PRES-01**: All existing features (chat, index, explain, debug, review, test) work identically after the binary is downloaded and cached — no behavioral change
- [x] **PRES-02**: Extension activation time is unaffected when a cached binary for the current version already exists (no network call on warm path)
- [x] **PRES-03**: Dev-mode compatibility is preserved — if a backend is already running on the configured port at activate time, the extension skips spawning

## v4 Requirements

### Sidecar Distribution

- [ ] **SIDE-01**: User installs the extension and the backend starts automatically (no manual Python setup)
- [ ] **SIDE-02**: Extension spawns the bundled backend binary on activate and kills it on deactivate
- [ ] **SIDE-03**: Extension polls `/health` after spawn and waits until backend is ready before pushing config
- [ ] **SIDE-04**: Backend stdout/stderr is streamed to a VS Code Output Channel ("Nexus Backend") for debugging
- [ ] **SIDE-05**: If a backend is already running at `localhost:8000`, extension skips spawning (dev mode compatibility)
- [ ] **SIDE-06**: GitHub Actions builds PyInstaller binaries for Mac and Windows and packages them into `.vsix`

### Provider Configuration

- [ ] **PROV-01**: User can select chat provider from: OpenAI, Mistral, Anthropic, Ollama, Gemini via VS Code settings
- [ ] **PROV-02**: User can select embedding provider from: OpenAI, Mistral, Ollama, Gemini via VS Code settings (Anthropic excluded — no embedding API)
- [ ] **PROV-03**: User can set chat model name (free text) via VS Code settings
- [ ] **PROV-04**: User can set embedding model name (free text) via VS Code settings
- [ ] **PROV-05**: User can set Ollama base URL via VS Code settings (default: `http://localhost:11434`)

### API Key Management

- [ ] **KEYS-01**: User can enter an API key per provider via `Nexus: Set API Key` command (stored in SecretStorage)
- [ ] **KEYS-02**: User can clear an API key per provider via `Nexus: Clear API Key` command
- [ ] **KEYS-03**: API keys are never written to `settings.json` or any plaintext file

### Dynamic Backend Config

- [ ] **CONF-01**: Extension pushes provider, model, and API key config to backend via `POST /api/config` on activate and on settings change
- [ ] **CONF-02**: Backend stores config in memory and uses it for all LLM and embedding calls (replaces `.env` singleton)
- [ ] **CONF-03**: Backend `model_factory.py` supports all 5 providers for chat; 4 providers for embedding
- [ ] **CONF-04**: Backend exposes `GET /health` endpoint for sidecar readiness polling

### Embedding Safety

- [ ] **EMBD-01**: Backend stores active embedding provider, model, and dimensions in a `nexus_meta` table in `graph.db`
- [ ] **EMBD-02**: On `POST /api/config`, backend detects embedding model mismatch and returns `reindex_required: true`
- [ ] **EMBD-03**: Extension warns user before they save an embedding model change that a reindex will be required
- [ ] **EMBD-04**: Chat is blocked with a warning banner when `reindex_required` is true, until a successful index completes
- [ ] **EMBD-05**: Chat is blocked on first install until at least one successful index has been completed

### Webview Status

- [ ] **VIEW-01**: Sidebar shows active chat provider and model
- [ ] **VIEW-02**: Sidebar shows active embedding provider and model
- [ ] **VIEW-03**: Sidebar shows a `[Configure Keys]` button that triggers `nexus.setApiKey` command
- [ ] **VIEW-04**: Sidebar shows index status (valid / reindex required / never indexed)

## Traceability (v4.1)

| Requirement | Phase | Status |
|-------------|-------|--------|
| DIST-01 | Phase 36 | Complete |
| DIST-02 | Phase 36 | Complete |
| DIST-03 | Phase 36 | Complete |
| DIST-04 | Phase 36 | Complete |
| DIST-05 | Phase 36 | Complete |
| DIST-06 | Phase 37 | Complete |
| DIST-07 | Phase 37 | Complete |
| DIST-08 | Phase 37 | Complete |
| PRES-01 | Phase 36 | Complete |
| PRES-02 | Phase 36 | Complete |
| PRES-03 | Phase 36 | Complete |

**Coverage:** 11 requirements · 2 phases · 0 unmapped

## Future Requirements (v5+)

### Distribution
- Linux sidecar binary — deferred, reduces v4 build complexity
- Auto-update mechanism for sidecar binary

### Provider Expansion
- MCP protocol model server connection (alternative to API key)
- Additional providers as ecosystem evolves

### Observability
- Bug localisation accuracy benchmark
- Provider latency/cost comparison dashboard

## Out of Scope

| Feature | Reason |
|---------|--------|
| Linux sidecar binary | Deferred to v5 — Mac + Windows covers primary user base |
| MCP model server connection | API key sufficient for v4; MCP adds protocol complexity |
| Cloud-hosted backend | Violates local-first privacy story |
| Real-time collaboration | Not core to single-developer use case |
| Java, Go language support | AST parser scope creep |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| SIDE-01 | Phase 33 | Pending |
| SIDE-02 | Phase 33 | Pending |
| SIDE-03 | Phase 33 | Pending |
| SIDE-04 | Phase 33 | Pending |
| SIDE-05 | Phase 33 | Pending |
| SIDE-06 | Phase 35 | Pending |
| PROV-01 | Phase 32 | Pending |
| PROV-02 | Phase 32 | Pending |
| PROV-03 | Phase 32 | Pending |
| PROV-04 | Phase 32 | Pending |
| PROV-05 | Phase 32 | Pending |
| KEYS-01 | Phase 32 | Pending |
| KEYS-02 | Phase 32 | Pending |
| KEYS-03 | Phase 32 | Pending |
| CONF-01 | Phase 32 | Pending |
| CONF-02 | Phase 30 | Pending |
| CONF-03 | Phase 30 | Pending |
| CONF-04 | Phase 30 | Pending |
| EMBD-01 | Phase 31 | Pending |
| EMBD-02 | Phase 31 | Pending |
| EMBD-03 | Phase 34 | Pending |
| EMBD-04 | Phase 34 | Pending |
| EMBD-05 | Phase 34 | Pending |
| VIEW-01 | Phase 34 | Pending |
| VIEW-02 | Phase 34 | Pending |
| VIEW-03 | Phase 34 | Pending |
| VIEW-04 | Phase 34 | Pending |

**Coverage:**
- v4 requirements: 27 total
- Mapped to phases: 27
- Unmapped: 0

---
*Requirements defined: 2026-03-26*
*Last updated: 2026-03-26 — traceability populated by roadmapper*
