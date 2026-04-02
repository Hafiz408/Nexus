---
phase: 36-sidecar-download
plan: "01"
subsystem: infra
tags: [typescript, vscode-extension, crypto, sha256, fetch, streaming-download, sidecar]

# Dependency graph
requires:
  - phase: 35-build-pipeline
    provides: SidecarManager.ts with _ensureExtracted + lockfile helpers
provides:
  - _fetchChecksum method: fetches and parses checksums.sha256 from GitHub Release URL
  - _downloadAndVerify method: streaming download with incremental SHA256 + vscode.Progress reporting
  - _showDownloadError method: error notification with Open GitHub Releases action button
  - "@types/node installed: Node.js types for crypto, fs, net, os, path, child_process"
affects:
  - 36-02: _downloadAndVerify and _fetchChecksum are wired into _ensureExtracted in plan 02

# Tech tracking
tech-stack:
  added: ["@types/node@^20"]
  patterns:
    - "Incremental SHA256 via crypto.createHash('sha256') + hash.update(chunk) in stream loop"
    - "vscode.Progress<{ message?: string; increment?: number }> for download UX"
    - "res.body as unknown as AsyncIterable<Uint8Array> for TypeScript-safe fetch streaming"
    - "fs.rmSync(destPath, { force: true }) to delete corrupt temp file on hash mismatch"

key-files:
  created: []
  modified:
    - extension/package.json
    - extension/package-lock.json
    - extension/src/SidecarManager.ts

key-decisions:
  - "Remove invalid stdio option from cp.execFile calls — ExecFileOptions does not extend CommonSpawnOptions in @types/node@20"
  - "Use 'as unknown as AsyncIterable<Uint8Array>' for res.body to satisfy TypeScript DOM lib vs Node fetch typing"

patterns-established:
  - "Pattern 1: Streaming fetch with incremental SHA256 — update hash per chunk, verify after loop, write only on success"
  - "Pattern 2: vscode.Progress increment reporting — track lastPct, only report positive delta"

requirements-completed: [DIST-03, DIST-04, DIST-05]

# Metrics
duration: 7min
completed: 2026-04-01
---

# Phase 36 Plan 01: sidecar-download Helpers Summary

**@types/node installed and three SHA256-verified streaming download helpers added to SidecarManager — _fetchChecksum, _downloadAndVerify (with vscode.Progress), _showDownloadError**

## Performance

- **Duration:** 7 min
- **Started:** 2026-04-01T19:07:50Z
- **Completed:** 2026-04-01T19:15:29Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Installed `@types/node@^20` to unlock Node.js type definitions for all SidecarManager imports (crypto, fs, net, os, path, child_process)
- Added `_fetchChecksum(baseUrl, archiveName)` — fetches `checksums.sha256` from GitHub Release, parses sha256sum line format, returns hash
- Added `_downloadAndVerify(url, destPath, expectedHash, progress)` — streaming fetch with incremental SHA256 hashing, vscode.Progress percentage reporting via Content-Length, deletes corrupt file on mismatch
- Added `_showDownloadError(errMsg)` — error notification with "Open GitHub Releases" action button opening `https://github.com/Hafiz408/Nexus/releases`
- TypeScript typecheck passes with 0 errors; no existing methods modified

## Task Commits

Each task was committed atomically:

1. **Task 1: Install @types/node and verify typecheck baseline** - `6b4df0a` (chore)
2. **Task 2: Add _fetchChecksum and _downloadAndVerify helpers to SidecarManager** - `6c1e03b` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified
- `extension/package.json` - Added `@types/node@^20` devDependency
- `extension/package-lock.json` - Updated lockfile for @types/node install
- `extension/src/SidecarManager.ts` - Added crypto import + 3 new private helper methods; fixed pre-existing execFile type errors

## Decisions Made
- Removed `stdio` option from `cp.execFile` calls — `ExecFileOptions` in `@types/node@20` does not include `stdio` (only `CommonSpawnOptions` does). The default piped streams still work for stdout/stderr event listeners.
- Used `as unknown as AsyncIterable<Uint8Array>` double cast for `res.body` — TypeScript's DOM lib `ReadableStream` does not declare `[Symbol.asyncIterator]` in ES2022 target; double cast is the standard safe workaround.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed pre-existing cp.execFile TS2769 type errors**
- **Found during:** Task 1 (typecheck verification after @types/node install)
- **Issue:** Both `cp.execFile` calls passed `stdio` option — this property exists in `CommonSpawnOptions` but NOT in `ExecFileOptions`. Without @types/node the parameter was `any`; with types installed, TypeScript correctly flagged TS2769.
- **Fix:** Removed `stdio` option from both `cp.execFile` calls. Default behavior is already piped, so stdout/stderr listeners still function correctly.
- **Files modified:** `extension/src/SidecarManager.ts`
- **Verification:** `npm run typecheck` exits 0
- **Committed in:** `6b4df0a` (Task 1 commit)

**2. [Rule 1 - Bug] Added `as unknown` intermediate cast for res.body AsyncIterable**
- **Found during:** Task 2 (typecheck after adding _downloadAndVerify)
- **Issue:** TypeScript DOM lib `ReadableStream<Uint8Array>` does not expose `[Symbol.asyncIterator]` in ES2022, causing TS2352 when casting directly to `AsyncIterable<Uint8Array>`.
- **Fix:** Used `res.body as unknown as AsyncIterable<Uint8Array>` double cast — standard TypeScript pattern for overlapping but non-overlapping types.
- **Files modified:** `extension/src/SidecarManager.ts`
- **Verification:** `npm run typecheck` exits 0
- **Committed in:** `6c1e03b` (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (2 × Rule 1 - Bug)
**Impact on plan:** Both fixes were necessary side effects of installing @types/node. The pre-existing code was untyped and silently wrong; the fixes restore correct behavior with proper types. No scope creep.

## Issues Encountered
- None beyond the two auto-fixed type issues above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All three helper methods are ready for Plan 02 to wire into `_ensureExtracted`
- `_fetchChecksum` accepts `baseUrl` + `archiveName` — Plan 02 will pass the constructed GitHub Release URL
- `_downloadAndVerify` accepts `vscode.Progress` — Plan 02 will wrap in `vscode.window.withProgress`
- `_showDownloadError` is standalone — Plan 02 calls it from the catch block
- TypeScript typecheck is clean (0 errors) — Plan 02 can add methods without baseline noise

## Self-Check: PASSED

- SUMMARY.md: FOUND
- SidecarManager.ts: FOUND
- package.json: FOUND
- Commit 6b4df0a: FOUND
- Commit 6c1e03b: FOUND

---
*Phase: 36-sidecar-download*
*Completed: 2026-04-01*
