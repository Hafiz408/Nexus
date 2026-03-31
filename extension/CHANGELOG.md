# Changelog

All notable changes to Nexus AI are documented here.

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
