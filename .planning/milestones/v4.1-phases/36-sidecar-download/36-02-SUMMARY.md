---
phase: 36-sidecar-download
plan: "02"
subsystem: infra
tags: [typescript, vscode-extension, github-releases, sha256, streaming-download, sidecar, progress-notification]

# Dependency graph
requires:
  - phase: 36-sidecar-download/36-01
    provides: _fetchChecksum, _downloadAndVerify, _showDownloadError helpers in SidecarManager

provides:
  - "_ensureExtracted refactored: cold path downloads from GitHub Releases with SHA256 verification and progress UI"
  - "start() try/catch: download failures surface via _showDownloadError error notification"
  - "bin/ directory no longer read at runtime — only GitHub Releases used as binary source"

affects:
  - 36-03-or-later: _ensureExtracted and start() are now the complete download-from-releases flow

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Cache-first guard: existsSync(executablePath) before any network call — warm path returns immediately"
    - "URL construction: baseUrl = github.com/Hafiz408/Nexus/releases/download/v${version}"
    - "Dev-build 404 fallback: catch block in _ensureExtracted returns undefined for silent port 8000 fallback"
    - "try/catch in start() separates thrown errors (show notification) from undefined returns (silent fallback)"

key-files:
  created: []
  modified:
    - extension/src/SidecarManager.ts

key-decisions:
  - "Dev-build 404 returns undefined from _ensureExtracted (not throw) so start() silently falls back to port 8000 — no user-facing error for dev builds"
  - "Thrown errors from _ensureExtracted (network failure, SHA256 mismatch) propagate to start() catch where _showDownloadError is called"
  - "Archive temp file uses .tmp suffix during download, deleted after successful extraction per CONTEXT.md"

patterns-established:
  - "Pattern 3: withProgress wrapping _downloadAndVerify — progress UI during cold-path download"
  - "Pattern 4: try/catch separation in start() — thrown = show error, undefined = silent fallback"

requirements-completed: [DIST-01, DIST-02, PRES-01, PRES-02, PRES-03]

# Metrics
duration: 4min
completed: 2026-04-01
---

# Phase 36 Plan 02: sidecar-download Core Flow Summary

**_ensureExtracted replaced bin/ lookup with GitHub Releases download-on-cache-miss flow — SHA256 verified, progress notification, dev-build 404 silent fallback; start() wired with try/catch for user-facing download error notification**

## Performance

- **Duration:** 4 min
- **Started:** 2026-04-01T19:23:27Z
- **Completed:** 2026-04-01T19:27:00Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments
- Replaced the `bin/` archive lookup in `_ensureExtracted` entirely — the extension no longer reads from `extension/bin/` at runtime
- Cold path: constructs GitHub Releases URL from version, fetches checksum, streams binary with `vscode.window.withProgress`, verifies SHA256, extracts via tar, deletes temp archive
- Warm path unchanged: `existsSync(executablePath)` returns immediately with no network call or notification (DIST-02, PRES-02)
- Dev-build / no-matching-release: checksum fetch failure returns `undefined` silently — caller falls back to port 8000 without error toast
- Wired try/catch in `start()` — thrown errors from download/verify call `_showDownloadError` for user-facing notification with "Open GitHub Releases" button (DIST-04)
- TypeScript typecheck passes with 0 errors

## Task Commits

Each task was committed atomically:

1. **Task 1: Refactor _ensureExtracted to download from GitHub Releases on cache miss** - `7ee328f` (feat)
2. **Task 2: Wire download error handling into start() method** - `09bee73` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified
- `extension/src/SidecarManager.ts` - Replaced _ensureExtracted with download-from-releases flow; added try/catch in start()

## Decisions Made
- Dev-build 404 returns `undefined` from `_ensureExtracted` (not a throw) so `start()` silently falls back to port 8000. Only actual download/verify failures throw and trigger the error notification. This cleanly separates "no release for this version" (expected in dev) from "download failed" (unexpected, user must be informed).
- Archive temp path uses `archiveName + '.tmp'` suffix — download writes here, tar extracts from here, then it is deleted. If VS Code crashes mid-download, the orphaned `.tmp` will be overwritten on next activation (not left as a corrupt permanent file).

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Worktree branch `worktree-agent-a504fc1c` needed to be merged from `feature/v4.1-gh-release-distribution` to obtain the Plan 01 commits (6b4df0a, 6c1e03b) before Plan 02 implementation. Resolved via `git merge feature/v4.1-gh-release-distribution` (fast-forward). This is a standard parallel-worktree setup requirement, not a code issue.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All behavioral changes for Phase 36 are complete in `SidecarManager.ts`
- Binary sourcing now exclusively from GitHub Releases — `extension/bin/` directory can be emptied in a future plan (build pipeline change)
- `_fetchChecksum`, `_downloadAndVerify`, `_showDownloadError`, `_ensureExtracted`, and `start()` are all wired and typechecked
- Phase 36 success criteria met: cold path downloads, warm path skips, download failures notify, dev-build 404 silent, checksum mismatch deletes + notifies

## Self-Check: PASSED

- SUMMARY.md: FOUND (this file)
- SidecarManager.ts modified: FOUND
- Commit 7ee328f: FOUND (feat(36-02): refactor _ensureExtracted to download from GitHub Releases)
- Commit 09bee73: FOUND (feat(36-02): wire download error handling into start() method)

---
*Phase: 36-sidecar-download*
*Completed: 2026-04-01*
