# Changelog

All notable changes to Nexus AI are documented here.

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
