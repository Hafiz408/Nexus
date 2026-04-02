---
phase: 36-sidecar-download
verified: 2026-04-01T19:45:00Z
status: passed
score: 9/9 must-haves verified
re_verification: false
---

# Phase 36: sidecar-download Verification Report

**Phase Goal:** SidecarManager resolves the backend binary via a cache-first strategy — using a locally cached copy when available and downloading from GitHub Releases on a version miss — with SHA256 integrity verification, a progress notification on first use, and graceful failure with a manual fallback link
**Verified:** 2026-04-01T19:45:00Z
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | SidecarManager can fetch a checksums.sha256 file from a URL and parse the hash for a given archive name | VERIFIED | `_fetchChecksum` at line 116 fetches `${baseUrl}/checksums.sha256`, parses sha256sum line format, returns hash or throws |
| 2 | SidecarManager can stream-download a file with incremental SHA256 hashing and VS Code progress reporting | VERIFIED | `_downloadAndVerify` at line 144 iterates `res.body` as `AsyncIterable<Uint8Array>`, calls `hash.update(chunk)` per chunk, calls `progress.report({ increment: pct - lastPct })` when percentage advances |
| 3 | A SHA256 mismatch deletes the corrupt temp file and throws an error | VERIFIED | Lines 178-179: `fs.rmSync(destPath, { force: true })` followed by `throw new Error(\`SHA256 mismatch: expected ${expectedHash}, got ${digest}\`)` |
| 4 | A download failure produces an error notification with an Open GitHub Releases action button | VERIFIED | `_showDownloadError` at lines 190-197 calls `vscode.window.showErrorMessage` with `'Open GitHub Releases'` button; `vscode.env.openExternal` opens `https://github.com/Hafiz408/Nexus/releases` on click |
| 5 | On first activation (cache miss), the extension downloads the backend binary from GitHub Releases with a progress notification | VERIFIED | `_ensureExtracted` cold path (lines 223-268): constructs `github.com/Hafiz408/Nexus/releases/download/v${version}` URL, wraps `_downloadAndVerify` in `vscode.window.withProgress` with `title: 'Downloading Nexus backend\u2026'` and `cancellable: false` |
| 6 | On subsequent activations (cache hit), the extension uses the cached binary with no network call and no notification | VERIFIED | Lines 218-221: `if (fs.existsSync(executablePath))` returns immediately with no fetch call — warm path confirmed silent |
| 7 | Dev-mode (backend already running on port) skips spawning entirely | VERIFIED | `start()` reuse path (lines 289-298): lockfile + version match + `_checkHealth` passing returns existing URL without entering spawn path |
| 8 | Dev-build / no-matching-release: checksum fetch 404 logs warning and falls back silently to port 8000 | VERIFIED | `_ensureExtracted` catch block at lines 231-234 returns `undefined`; `start()` line 322-323 maps `undefined` to `http://127.0.0.1:8000` without notification |
| 9 | TypeScript compilation passes with zero errors after @types/node is installed | VERIFIED | `npm run typecheck` exits 0 — `tsc --noEmit` and `tsc --noEmit -p tsconfig.webview.json` both pass |

**Score:** 9/9 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `extension/package.json` | @types/node devDependency | VERIFIED | `"@types/node": "^20.19.37"` present in devDependencies |
| `extension/src/SidecarManager.ts` | _fetchChecksum, _downloadAndVerify, _showDownloadError, refactored _ensureExtracted | VERIFIED | All four methods present; file is 402 lines, fully substantive |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `SidecarManager.ts` | `crypto` module | `import * as crypto from 'crypto'` | VERIFIED | Line 7; `crypto.createHash('sha256')` at line 158 |
| `SidecarManager.ts` | `vscode.window.withProgress` | progress notification wrapper in `_ensureExtracted` | VERIFIED | Lines 241-250; wraps `_downloadAndVerify` call |
| `_ensureExtracted` | `_fetchChecksum` + `_downloadAndVerify` | method calls on cache miss | VERIFIED | `this._fetchChecksum(baseUrl, archiveName)` at line 230; `this._downloadAndVerify(archiveUrl, tmpPath, expectedHash, progress)` at line 248 |
| `start()` | `_showDownloadError` | catch block when `_ensureExtracted` throws | VERIFIED | Lines 311-318: try/catch around `this._ensureExtracted(version)`, `await this._showDownloadError(errMsg)` on error |

---

### Data-Flow Trace (Level 4)

Not applicable — SidecarManager is infrastructure (no rendered dynamic UI data). All key behaviors are procedural flows, not render pipelines.

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| TypeScript compiles with 0 errors | `npm run typecheck` | Exit 0, no errors | PASS |
| `_fetchChecksum` method defined | `grep '_fetchChecksum' extension/src/SidecarManager.ts` | Line 116, 230 (definition + call site) | PASS |
| `_downloadAndVerify` method defined | `grep '_downloadAndVerify' extension/src/SidecarManager.ts` | Line 144, 248 (definition + call site) | PASS |
| `_showDownloadError` method defined | `grep '_showDownloadError' extension/src/SidecarManager.ts` | Line 190, 317 (definition + call site) | PASS |
| Old `bin/` lookup removed | `grep 'extensionPath.*bin' extension/src/SidecarManager.ts` | No output | PASS |
| GitHub Releases URL present | `grep 'github.com/Hafiz408/Nexus/releases' extension/src/SidecarManager.ts` | Lines 196, 224 | PASS |
| Phase commits exist in git | `git log --oneline 6b4df0a 6c1e03b 7ee328f 09bee73` | All 4 commits found | PASS |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| DIST-01 | 36-02 | Backend downloaded automatically from GitHub Releases on first activation | SATISFIED | `_ensureExtracted` cold path constructs `github.com/Hafiz408/Nexus/releases/download/v${version}` URL and downloads on cache miss |
| DIST-02 | 36-02 | Binary served from `globalStorage/<version>/` cache on subsequent activations without network call | SATISFIED | `existsSync(executablePath)` guard at line 218 returns immediately on cache hit — no fetch |
| DIST-03 | 36-01 | VS Code progress notification ("Downloading Nexus backend…") while binary is being fetched | SATISFIED | `vscode.window.withProgress` with `title: 'Downloading Nexus backend\u2026'` at lines 241-250 |
| DIST-04 | 36-02 | Error notification with direct link to manually download on failure | SATISFIED | `_showDownloadError` called from `start()` catch block; button opens GitHub Releases page |
| DIST-05 | 36-01 | SHA256 checksum verified before extraction; mismatch aborts activation | SATISFIED | `_downloadAndVerify` computes digest, calls `fs.rmSync` + throws on mismatch; `_ensureExtracted` aborts before tar extraction |
| PRES-01 | 36-02 | All existing features work identically after binary downloaded | SATISFIED | Spawn path, health-check, lockfile, stdout/stderr piping, and `waitForHealth` are all unchanged — only binary sourcing changed |
| PRES-02 | 36-02 | Extension activation time unaffected when cached binary exists | SATISFIED | Warm path guard returns before any network call; no notification shown |
| PRES-03 | 36-02 | Dev-mode compatibility preserved — existing backend skips spawning | SATISFIED | Reuse path in `start()` (lockfile + `_checkHealth`) is untouched; dev-mode skips spawn as before |

**All 8 required requirements satisfied. No orphaned requirements detected.**

Traceability cross-check: REQUIREMENTS.md v4.1 traceability table maps DIST-01 through DIST-05 and PRES-01 through PRES-03 to Phase 36, all marked "Complete." This matches the phase plan `requirements` fields exactly (36-01 claims DIST-03, DIST-04, DIST-05; 36-02 claims DIST-01, DIST-02, PRES-01, PRES-02, PRES-03).

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| None | — | — | — | — |

No TODO, FIXME, placeholder comments, empty return statements, hardcoded empty collections, or stub implementations found in `extension/src/SidecarManager.ts`. All methods have substantive implementations.

---

### Human Verification Required

#### 1. Cold-Path Download Flow (live network)

**Test:** Activate the extension in a clean VS Code window where no cached binary exists for the current version (`~/.vscode/globalStorage/.../backend/4.0.10/` does not exist). Observe the notification panel.
**Expected:** A VS Code progress notification appears at the bottom right with the title "Downloading Nexus backend…" and increments from 0 to 100%. The backend starts successfully after extraction.
**Why human:** Requires a live network connection to GitHub Releases and a real VS Code activation; cannot be tested with grep/typecheck.

#### 2. Download Failure Error Notification

**Test:** With network blocked (or an invalid release URL), trigger a cold-path activation.
**Expected:** A VS Code error message appears: "Nexus: Failed to download backend — [error message]. Download manually or check your network." with an "Open GitHub Releases" button. Clicking the button opens `https://github.com/Hafiz408/Nexus/releases` in the browser.
**Why human:** Requires a network failure scenario; error notification UI cannot be verified programmatically.

#### 3. Warm-Path Speed (activation time)

**Test:** Activate the extension twice in sequence — the second activation should use the cached binary.
**Expected:** Second activation is noticeably faster (no progress notification, no network activity in VS Code's network inspector).
**Why human:** Activation latency requires subjective observation; the absence of a notification needs to be confirmed visually.

---

### Gaps Summary

No gaps found. All 9 observable truths are verified, all 8 requirements are satisfied, all 4 key links are wired, and TypeScript typecheck passes with 0 errors. The 3 human verification items above are for live-environment confirmation only — they do not block phase completion.

---

_Verified: 2026-04-01T19:45:00Z_
_Verifier: Claude (gsd-verifier)_
