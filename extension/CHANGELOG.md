# Changelog

All notable changes to Nexus AI are documented here.

## [4.2.3] - 2026-04-04

### Changed
- **Cross-encoder reranking in `graph_rag_retrieve`** — the MMR candidate pool is now passed through `cross_encode_rerank` from `backend/app/retrieval/reranker.py` before final node selection. `use_cross_encoder=True` is the new default; the pipeline records `cross_encoder_used` in retrieval stats and falls back gracefully if the CE model raises an error, so existing behaviour is fully preserved on failure.

### Added
- **Cross-encoder model pre-warm on startup** — `backend/app/main.py` launches a daemon thread at startup that calls `_get_reranker()`, loading the 66 MB `cross-encoder/ms-marco-MiniLM-L-6-v2` model into memory before the first query arrives. Cold-start latency on the initial request is eliminated.
- **CE integration tests** — 4 new unit tests in `backend/tests/test_graph_rag.py` covering the CE rerank path; existing calls that do not exercise CE are opted out via the `use_cross_encoder=False` flag.
- **`eval/run_ragas_redesign.py` v2+CE column** — the redesign eval script now includes a Graph RAG v2+CE pipeline column alongside the v2 baseline. A `--ce-only` flag skips re-running v2 and loads prior results from disk.

### Eval results (RAGAS, 30Q, qwen2.5:7b, fastapi corpus)
| Run | Pipeline | Faithfulness | Answer Relevancy | Context Precision |
|-----|----------|-------------|-----------------|-------------------|
| B | Graph RAG v2 | 0.5389 | 0.4121 | 0.2532 |
| C | Graph RAG v2 + CE | 0.5417 | 0.4827 | 0.3706 |

Context Precision: **+46%** (0.2532 → 0.3706). Answer Relevancy: **+17%** (0.4121 → 0.4827).

## [4.2.2] - 2026-04-03

### Changed
- **Graph RAG v2 retrieval pipeline** — complete rewrite of `graph_rag_retrieve` replacing the v1 BFS+PageRank pipeline with a five-step design:
  1. **RRF merge** — Reciprocal Rank Fusion replaces `max(semantic, fts)` score merging. Rank-based and immune to scale differences between cosine similarity and BM25, so nodes appearing highly in both lists score higher than those topping only one.
  2. **CALLS-depth-1 expansion** — BFS over undirected `ego_graph` replaced with direct CALLS-edge traversal from semantic seeds only. IMPORTS edges excluded to prevent cross-file pollution (e.g. querying about `Depends()` no longer expands into `logging` and `typing` modules).
  3. **Propagated scoring** — BFS-expanded non-seed nodes previously received a flat `0.3` fallback score independent of query relevance. Neighbors now score `parent_rrf_score × 0.6`, keeping their competitiveness anchored to how relevant their parent seed was.
  4. **Per-seed neighbor cap** — 5 callers + 5 callees per seed (ordered by pagerank), preventing BFS cluster overlap from a single high-centrality node.
  5. **MMR diversity selection** — iterative Maximal Marginal Relevance replaces score-rank cutoff; subtracts `0.35 × same-file-count` at each selection step so one class's methods cannot monopolise the result set.
- **`improved_rag.py` and `query_expansion.py` removed** — superseded by the v2 pipeline and no longer referenced anywhere in the codebase.

### Eval results (RAGAS, 30Q, qwen2.5:7b, fastapi corpus)
| Metric | Naive baseline | Graph RAG v2 | Δ |
|---|---|---|---|
| Faithfulness | 0.364 | 0.539 | **+48%** |
| Answer Relevancy | 0.250 | 0.412 | **+65%** |
| Context Precision | 0.118 | 0.253 | **+115%** |

### Added
- **`eval/run_ragas_redesign.py`** — RAGAS evaluation script for the v2 pipeline; loads the naive baseline from the most recent three-way run rather than re-running it.
- **`eval/test_e2e_smoke.py`** — fast retrieval smoke test (no LLM, no API keys); verifies `graph_rag_retrieve` returns nodes and correct stats keys against the fastapi corpus.
- **`eval/test_e2e_http.py`** — full integration test; starts the backend, pushes config, and fires all four intents (explain / debug / review / test) via real HTTP + SSE with live LLM calls.

## [4.2.1] - 2026-04-03

### Fixed
- **Token-aware embedding batching** — replaced the fixed `EMBED_BATCH_SIZE=100` constant with a dynamic token-budget approach (`EMBED_TOKEN_BUDGET=12_000`, `MAX_EMBED_TEXT_CHARS=6_000`). Large-repo indexing runs that previously failed with `TypeError: fetch failed` due to oversized API payloads now batch correctly.
- **Connection leaks in ingestion pipeline** — `sqlite_vec.load()` failures in the embedder and semantic search paths left DB connections open. All connection setup paths now use `try/finally` to guarantee close on error.
- **`graph_store` / `meta_store` DDL failures** — `_get_conn` in both stores now wraps schema initialisation in `try/except` and closes the connection on failure, preventing leaked handles during first-run setup.
- **`delete_index` blocking the event loop** — DB deletion calls are now dispatched via `asyncio.to_thread`; errors return HTTP 500 instead of crashing the route.
- **Checkpoint connection not closed after v2 streaming** — `v2_event_generator` now closes the LangGraph checkpoint connection in a `finally` block.
- **`post_review_to_pr` unhandled exceptions** — GitHub post calls are now wrapped in `try/except` to prevent unhandled errors surfacing as 500s.
- **Corrupt config DB crash** — `config_router/set_config` guards `get_embedding_meta` against a corrupt or empty config database.

### Changed
- **Walker `SKIP_DIRS` expanded** — coverage increased from 9 to 30+ entries, now including Python venv directories, JS/TS caches (`node_modules`, `.next`, `.nuxt`), build outputs (`dist`, `build`, `out`), framework dirs, temp/log dirs, and all common VCS metadata directories. A `.dist-info` suffix guard was added alongside the existing `.egg-info` guard.

## [4.2.0] - 2026-04-02

### Added
- **FTS5 dual-search pipeline** — retrieval now runs a BM25 keyword search over indexed symbol names in parallel with the semantic vector search. Results are merged (per-node score = max of the two sources). FTS5 scores are capped at 0.85 so perfect semantic matches (1.0) always rank above perfect keyword matches. This catches exact/prefix function-name queries that embedding similarity alone can miss.
- **Backend unit tests in CI** — all 244 pytest tests now run as a required gate (`backend-unit-tests` job) before the binary build steps, alongside the smoke test and extension build check.

### Changed
- **Default context nodes raised to 15** — `nexus.maxNodes` default increased from 10 to 15, wired through all query paths (v1 streaming and v2 LangGraph). More context for the LLM with minimal latency impact on modern models.
- **Test-file seed penalty** — seed nodes that come from test/spec files receive a 0.5× score multiplier so source implementation files consistently rank above test files that share vocabulary with the query.
- **Robot-heart sidebar icon** — replaced the placeholder icon with a custom SVG silhouette in the Activity Bar.

### Fixed
- **Virtual document paths dropped cleanly** — VS Code output panel and untitled buffer URIs (e.g. `extension-output-publisher.name-#1-label`) passed as `selected_file` are now silently discarded rather than treated as real filesystem paths.
- **Unsupported file types give a clear error** — selecting a `.rb`, `.go`, or other unindexed file type now returns an informative error message instead of silently answering "I'm not certain" from unrelated context.
- **Empty index gives a clear error** — if the repository contains no indexed source files, the explain path raises a descriptive message rather than silently producing an empty answer.
- **Rate-limit errors surface in chat** — `429` / rate-limit / capacity errors from the LLM provider were previously swallowed by the retrieval fallback. They now propagate to the SSE `error` event so the user sees the actual provider error.

## [4.1.2] - 2026-04-02

### Fixed
- **Backend stays alive while VS Code is open** — the sidecar now auto-restarts immediately when the backend exits unexpectedly (SIGTERM from idle watchdog, crash, etc.). The spawning window restarts via an `onUnexpectedExit` callback; secondary windows (which reuse the backend) recover within one 30-second keepalive cycle.
- **Stale lockfile after backend exit** — the lockfile is now deleted when the backend process exits, preventing a second VS Code window from reading a dead PID/port and logging "Reusing existing backend" before all API calls fail.
- **"fetch failed" after SIGTERM** — `BackendClient.backendUrl` was `readonly` and frozen at the original port forever. It is now updated to the new port after each restart, so index and chat calls recover without a window reload.
- **Keepalive could not detect a dead backend** — `ping()` previously returned `void` and silently swallowed errors. It now returns `Promise<boolean>`, allowing the keepalive to trigger a restart when the backend is unreachable.
- **`_log()` throw after dispose** — calling `_log()` on a disposed VS Code `OutputChannel` (when the process exits after the extension deactivates) now returns silently instead of throwing.
- **Infinite restart loop** — consecutive restart failures are now counted; after 5 failures the extension stops retrying and shows a "Reload Window" notification instead of restarting every 30 seconds indefinitely.
- **Overlapping keepalive pings** — an in-flight guard prevents keepalive ticks from piling up when the backend is slow to respond.
- **`waitForHealth` race during restart** — the health-check URL is now snapshotted at call time rather than read from the mutable `_backendUrl` field, preventing it from polling the wrong address during a concurrent restart.
- **`isStreaming` stuck after stream error** — if the SSE stream was interrupted mid-response (backend crash, network drop), the UI chat input remained locked. The webview now receives an error event on stream interruption and resets the streaming state.
- **Settings button opened API key prompt instead of settings panel** — the gear icon in the status bar now opens the VS Code extension settings page (`nexus.openSettings`) as labelled.
- **Key status not shown on sidebar load** — `broadcastKeyStatus` is now called during `resolveWebviewView` so the setup guide renders correctly on first load without waiting for an async round-trip.

### Changed
- **Idle watchdog timeout** raised from 15 minutes to 120 minutes — the backend now stays running for 2 hours of inactivity before self-terminating.
- **Keepalive interval** reduced from 3 minutes to 30 seconds — faster dead-backend detection and recovery for reuse-path windows.
- **Timestamps added to all log output** — every line in the "Nexus Backend" output channel now includes a `YYYY-MM-DD HH:MM:SS` prefix. Python `warnings.warn()` output (graph builder unresolvable-edge warnings) is routed through the logging system and timestamped as well.

### Internal
- `pollUntilComplete` gained an in-flight guard and a 10-minute timeout cap to prevent zombie polling intervals.
- Citation file tabs now open as preview tabs (not pinned) to avoid filling the tab bar.
- Test suite: patched `_check_sqlite_vec` and `init_vec_table` in `conftest.py` so all 235 tests pass on Python builds without `--enable-loadable-sqlite-extensions`.

## [4.1.0] - 2026-04-02

### Changed
- **Backend binary no longer bundled in VSIX** — the PyInstaller binary has been removed from the extension package. The VSIX now downloads to ~200 KB (down from ~62 MB). On first activation, the extension downloads the backend binary for your platform from GitHub Releases, verifies its SHA256 checksum, and caches it permanently in VS Code's global storage. Subsequent activations start from the local cache with no network call.

### Added
- **Download progress notification** — a VS Code progress notification ("Downloading Nexus backend...") appears during the first-time binary download, with percentage tracking via the file's `Content-Length`.
- **Download failure handling** — if the download fails (network error, 404, or checksum mismatch), a clear error notification is shown with an "Open GitHub Releases" button linking to the manual download page.
- **GitHub Release assets** — each tagged release now publishes `nexus-backend-mac.tar.gz`, `nexus-backend-win.tar.gz`, and `checksums.sha256` as permanent Release assets via CI.

## [4.0.10] - 2026-04-01

### Fixed
- **VS Marketplace virus scan false positive** — the VSIX was rejected by the Marketplace AV scanner due to YARA rule matches. Three root causes addressed:
  - Switched sidecar process launch from `spawn` to `execFile` (avoids the `SUSP_JS_Child_Process_Variable_Jan25` rule match on variable-argument process invocations).
  - Removed post-extraction `chmodSync` call — the executable bit is now set on the binary before archiving in `build.py`, making the runtime chmod unnecessary. This eliminates the `LOADER_JS_Download_Write_Execute_Jan25` dropper pattern match.
  - Disabled source map emission in production builds and added a post-build clean step to remove stale `.map` files. Source maps were doubling every YARA hit by embedding verbatim source strings in `.js.map` files shipped inside the VSIX.
- **PIL/Pillow excluded from Windows binary** — Pillow was bundled as a transitive LangChain dependency despite not being used by Nexus. The native image codec DLLs triggered additional AV false positives. Excluded via `--exclude-module PIL` in `build.py`.

---

## [4.0.9] - 2026-04-01

### Fixed
- **Module-level code selection now answered correctly** — when a user selects code that is not a function or class (e.g. module-level initialisation, `if __name__ == "__main__"` blocks), the explain path previously answered from unrelated graph-RAG context with no indication the selection was missed. The backend now reads the selected lines directly from disk and answers based on those lines, with an explicit note in the response that the code is not in the graph index.
- **Backend killed after 10 minutes of idle typing** — the idle watchdog fired after 600 s of no HTTP traffic, which affected users who left VS Code open without querying for a while. The extension now sends a keepalive ping to the backend every 3 minutes, and the watchdog threshold has been raised to 15 minutes as a fallback for truly closed/crashed windows.

---

## [4.0.8] - 2026-04-01

### Fixed
- **Chat "Cannot reach backend" error across all intents (Explain, Debug, Review, Test, Auto)** — `SidebarProvider` was reading `nexus.backendUrl` from VS Code settings (default `http://localhost:8000`) for all query and PR-review calls, but the sidecar backend runs on a dynamically allocated free port. All query paths now use the URL resolved by `SidecarManager` at startup.
- **PR review post-to-GitHub failing silently** — same root cause as above; `postReviewToPR` was also hitting the wrong port.

### Added
- **API key gate before querying** — if the configured chat or embedding provider has no stored key, chat is blocked with an inline error message and a VS Code notification offering a "Set API Key" shortcut. Prevents confusing backend errors from reaching the user.

### Improved
- **Extension bundle size reduced** — backend binary strips debug symbols (`--strip`), Python bytecode is optimised (`--optimize 2`), scipy/numpy test data excluded, and tarball uses maximum compression. VSIX: 72 MB → 62.6 MB; installed on disk: ~215 MB → ~161 MB.
- **Readme updated** — commands and settings tables now reflect all registered commands (`Nexus: Setup`, `Nexus: Open Settings`) and settings (`nexus.backendUrl`).

---

## [4.0.7] - 2026-04-01

### Fixed
- **ModuleNotFoundError: No module named 'numpy'** — numpy and scipy were missing from the production build requirements, causing the graph analysis step (PageRank) to crash during indexing.
- **First-time index failure on fresh workspaces** — the database schema was not initialised before the embeddings cleanup step, causing a "no such table" error on the very first index run.

### Improved
- **Backend startup time reduced from ~24s to ~1s** — switched from a single self-extracting binary (PyInstaller `--onefile`) to a pre-extracted directory bundle (`--onedir`) shipped as a `.tar.gz`. The archive is extracted once on first launch and reused on all subsequent launches.

---

## [4.0.6] - 2026-03-30

### Added
- **Multi-window support** — a single backend process is now shared across all VS Code windows; opening a second window reuses the running backend instead of spawning a new one.
- **Dynamic port allocation** — the backend picks a free OS port automatically, eliminating conflicts with other local services.
- **Detached backend process** — the backend continues running after closing a VS Code window and is reused when a new window opens.

---

## [4.0.5] - 2026-03-28

### Fixed
- Self-contained binary now ships with all dependencies bundled — no Python installation required on the user's machine.
- Settings button restored in the sidebar UI.
- SQLite robustness improvements to prevent database corruption on unclean shutdown.

---

## [4.0.4] - 2026-03-26

### Added
- First-run setup guide walks new users through API key configuration.
- Role-aware API key flow — the UI adapts based on whether a chat or embedding provider key is missing.

### Fixed
- SQLite extension loading crash on certain macOS Python builds.

---

## [4.0.0] - 2026-03-26

*Milestone: Model & Provider Agnostic + Zero-Setup Distribution*

### Added
- **Dynamic provider/model configuration** — `POST /api/config` replaces the static `.env` singleton. Supports OpenAI, Mistral, Anthropic, Ollama, and Gemini; hot-swappable at runtime without a server restart.
- **SidecarManager** — the extension automatically spawns the bundled PyInstaller backend binary on activate and shuts it down on deactivate. Uses a lockfile for multi-window reuse so only one backend process runs across all VS Code windows.
- **SecretStorage API key management** — provider API keys are stored in VS Code's `SecretStorage` and never written to disk or `settings.json`.
- **Embedding model mismatch detection** — the backend detects when the active embedding model differs from the one used to build the current index and blocks chat until the index is rebuilt.
- **GitHub Actions build pipeline** — parallel Mac and Windows PyInstaller jobs produce platform-specific backend binaries and package them into a single `.vsix`.

---

## [3.0.0] - 2026-03-25

*Milestone: Local-First Privacy*

### Changed
- **Workspace-local storage** — all graph data now lives in `.nexus/graph.db` (sqlite-vec + SQLite) inside the open workspace. PostgreSQL and Docker are no longer required.
- **Stateless backend** — the backend is compute-only; it holds no persistent state between requests. `db_path` is threaded through all API endpoints and `BackendClient` methods.

### Fixed
- `target_node_id` wired correctly from extension to backend; reviewer and tester end-to-end flows now resolve the correct node.

---

## [2.0.0] - 2026-03-22

*Milestone: Multi-Agent Team*

### Added
- **LangGraph orchestrator** — a `StateGraph` with `SqliteSaver` checkpointing routes queries through specialist agents: Router → specialist → Critic → MCP/done (Phases 22, 24).
- **Router agent** — intent classifier with 100% accuracy on 12 labelled queries; supports an `intent_hint` bypass path for direct routing.
- **Debugger agent** — BFS call-graph traversal with 5-factor anomaly scoring and top-5 suspect ranking with impact radius.
- **Reviewer agent** — 1-hop caller/callee context assembly with structured `Finding` schema and groundedness post-filter.
- **Tester agent** — marker-file framework detection, `CALLS`-edge mock target resolution, and deterministic test-file path derivation.
- **Critic agent** — quality scoring (0.40× groundedness + 0.35× relevance + 0.25× actionability) with a 2-loop hard cap.
- **MCP integrations** — GitHub MCP (tenacity retry, 422-skip) and Filesystem MCP (path traversal guard, extension allowlist).
- **Intent selector UI** — 5-pill intent selector in the sidebar; `DebugPanel`, `ReviewPanel`, and `TestPanel` render structured agent results.

---

## [1.0.0] - 2026-03-21

*Milestone: MVP*

### Added
- **Graph RAG retrieval pipeline** — 3-step retrieval: semantic vector search → BFS graph expansion → score reranking.
- **Streaming explorer agent** — LangChain LCEL agent with LangSmith tracing; streams responses over SSE via `POST /query`.
- **VS Code extension** — esbuild dual-bundle (extension host + webview), `fetch` + `ReadableStream` SSE consumer, React 18 webview panel.
- **Citation highlighting** — `TextEditorDecorationType` decorates cited symbol ranges in the active editor.
- **Incremental re-index** — file watcher triggers a partial re-index on save without a full rebuild.
- **RAGAS evaluation harness** — 30-entry golden dataset with an 80% baseline (8/10 questions answered correctly).
- **Extension UI** — auto-grow textarea, citation chips with expand/collapse, indeterminate progress bar.
