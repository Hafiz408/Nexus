# Phase 36: sidecar-download - Context

**Gathered:** 2026-04-01
**Status:** Ready for planning

<domain>
## Phase Boundary

SidecarManager resolves the backend binary via a cache-first strategy — using a locally cached copy when available and downloading from GitHub Releases on a version miss — with SHA256 integrity verification, a progress notification on first use, and graceful failure with a manual fallback link.

The change is scoped to `extension/src/SidecarManager.ts`: replace the `archivePath = path.join(extensionPath, 'bin', archiveName)` lookup with a download-from-releases flow. The extracted-binary cache check (`globalStoragePath/backend/<version>/`) already exists and remains the warm path.

</domain>

<decisions>
## Implementation Decisions

### Download URL & Release Naming
- Hardcoded URL template: `https://github.com/Hafiz408/Nexus/releases/download/v{version}/{archive}` using `_getVersion()` — consistent with existing pattern (no runtime parsing of `package.json` `repository.url`)
- Checksums manifest: `checksums.sha256` as a Release asset at the same URL base (`…/download/v{version}/checksums.sha256`) — matches DIST-08
- Dev build / no-matching-release fallback: log warning + use fallback port 8000 (reuse existing dev-mode path) rather than failing hard
- Downloaded archive is deleted after successful extraction — no permanent copy kept

### Progress & UX
- Notification wording: "Downloading Nexus backend…" — exact match to success criteria
- Progress bar: show percentage using `Content-Length` header when available; fall back to indeterminate if header absent
- No cancellation option — binary is required for extension to function
- Silent on warm path (cache hit) — no toast; DIST-02 requires no noticeable delay

### SHA256 Verification
- Sequential fetch: download `checksums.sha256` as a separate HTTP GET before downloading the binary archive
- Fail closed: if the checksum file itself fails to download, abort activation with an error (no unverified binary allowed)
- Checksum file format: standard `sha256sum` line format `<hash>  <filename>` (two spaces, matches POSIX `sha256sum` output — CI generates it with `sha256sum`)
- Delete corrupted archive before aborting on mismatch — success criteria 4 explicitly requires this

### Error Handling & Fallback
- Error notification: `vscode.window.showErrorMessage(message, "Open GitHub Releases")` — action button opens browser at releases page
- Fallback link: `https://github.com/Hafiz408/Nexus/releases` (releases index — always valid; avoids 404 on dev builds)
- Extension state after failure: extension stays loaded, sidecar not started — user sees the error and can decide (no silent port 8000 fallback on cold path)
- No explicit download timeout — rely on Node `fetch` defaults (~2 min connection reset)

### Claude's Discretion
- Internal helper method naming and structure within SidecarManager
- How to pipe download chunks for progress reporting (Node fetch readable stream vs. alternative)
- Whether `_ensureExtracted` is refactored or a new `_ensureDownloaded` helper extracted

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `SidecarManager._getVersion()` — reads `package.json` version field; already used for cache dir naming
- `SidecarManager._archiveName()` / `_executableName()` — platform archive/executable name resolution; reuse as-is
- Extracted binary cache check: `fs.existsSync(executablePath)` guard in `_ensureExtracted` — warm path already handled
- `this._channel.appendLine(...)` — Output Channel logging pattern used throughout

### Established Patterns
- `globalStoragePath/backend/<version>/` — cache directory already established by `_ensureExtracted`
- `fs.mkdirSync(cacheDir, { recursive: true })` — directory creation pattern already used
- `cp.execFile('tar', tarArgs, ...)` — tar extraction already implemented
- Error handling: silent catch blocks `catch { /* non-fatal */ }` for lock operations; fatal errors throw / return `undefined`

### Integration Points
- `SidecarManager.start()` calls `_ensureExtracted(version)` — this is the entry point to replace with download logic
- `archivePath = path.join(this._extensionPath, 'bin', archiveName)` — this lookup is what phase 36 removes (archive no longer bundled in `bin/`)
- `globalStoragePath` is passed via constructor as `path.dirname(this._lockfilePath)` parent — already in scope

</code_context>

<specifics>
## Specific Ideas

- The GitHub repo URL is `https://github.com/Hafiz408/Nexus` (from `package.json` `repository.url`)
- Extension version `4.0.10` confirmed in `package.json`; the download URL will use this at runtime via `_getVersion()`
- Archive names already defined: `nexus-backend-mac.tar.gz` (darwin), `nexus-backend-win.tar.gz` (win32)
- Node `crypto` module available for SHA256 hashing (no external dependency needed)
- `vscode.window.withProgress` with `ProgressLocation.Notification` is the standard VS Code download UX

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>
