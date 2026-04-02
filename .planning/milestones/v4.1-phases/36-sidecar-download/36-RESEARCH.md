# Phase 36: sidecar-download - Research

**Researched:** 2026-04-01
**Domain:** VS Code extension — Node.js HTTP download, SHA256 integrity verification, VS Code Progress API
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Download URL & Release Naming
- Hardcoded URL template: `https://github.com/Hafiz408/Nexus/releases/download/v{version}/{archive}` using `_getVersion()` — consistent with existing pattern (no runtime parsing of `package.json` `repository.url`)
- Checksums manifest: `checksums.sha256` as a Release asset at the same URL base (`…/download/v{version}/checksums.sha256`) — matches DIST-08
- Dev build / no-matching-release fallback: log warning + use fallback port 8000 (reuse existing dev-mode path) rather than failing hard
- Downloaded archive is deleted after successful extraction — no permanent copy kept

#### Progress & UX
- Notification wording: "Downloading Nexus backend…" — exact match to success criteria
- Progress bar: show percentage using `Content-Length` header when available; fall back to indeterminate if header absent
- No cancellation option — binary is required for extension to function
- Silent on warm path (cache hit) — no toast; DIST-02 requires no noticeable delay

#### SHA256 Verification
- Sequential fetch: download `checksums.sha256` as a separate HTTP GET before downloading the binary archive
- Fail closed: if the checksum file itself fails to download, abort activation with an error (no unverified binary allowed)
- Checksum file format: standard `sha256sum` line format `<hash>  <filename>` (two spaces, matches POSIX `sha256sum` output — CI generates it with `sha256sum`)
- Delete corrupted archive before aborting on mismatch — success criteria 4 explicitly requires this

#### Error Handling & Fallback
- Error notification: `vscode.window.showErrorMessage(message, "Open GitHub Releases")` — action button opens browser at releases page
- Fallback link: `https://github.com/Hafiz408/Nexus/releases` (releases index — always valid; avoids 404 on dev builds)
- Extension state after failure: extension stays loaded, sidecar not started — user sees the error and can decide (no silent port 8000 fallback on cold path)
- No explicit download timeout — rely on Node `fetch` defaults (~2 min connection reset)

### Claude's Discretion
- Internal helper method naming and structure within SidecarManager
- How to pipe download chunks for progress reporting (Node fetch readable stream vs. alternative)
- Whether `_ensureExtracted` is refactored or a new `_ensureDownloaded` helper extracted

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DIST-01 | Backend binary downloaded automatically from GitHub Releases on first activation | Download flow via `fetch` + `_ensureDownloaded` helper; replace `archivePath = path.join(extensionPath, 'bin', archiveName)` lookup |
| DIST-02 | Binary served from `globalStorage/<version>/` on subsequent activations — no network call | Existing `fs.existsSync(executablePath)` warm-path guard in `_ensureExtracted` already handles this |
| DIST-03 | VS Code progress notification "Downloading Nexus backend…" shown during first fetch | `vscode.window.withProgress` with `ProgressLocation.Notification`; `progress.report({ increment })` for deterministic or `{ message }` for indeterminate |
| DIST-04 | Download failure shows error notification with link to GitHub Releases | `vscode.window.showErrorMessage(msg, "Open GitHub Releases")` → `vscode.env.openExternal(vscode.Uri.parse(...))` |
| DIST-05 | Downloaded archive verified against SHA256 before extraction; mismatch aborts | Node `crypto.createHash('sha256')` fed incrementally through stream chunks; compare with value parsed from `checksums.sha256` asset |
| PRES-01 | All existing features work identically after binary is cached | No changes to spawn/health/config logic downstream of `_ensureExtracted` — only binary sourcing changes |
| PRES-02 | Activation time unaffected on warm path (no network call) | Warm-path guard (`fs.existsSync(executablePath)`) runs before download logic; returns immediately |
| PRES-03 | Dev-mode: backend already running on configured port → spawning skipped | Existing `_checkHealth` reuse-path in `start()` is untouched |
</phase_requirements>

---

## Summary

Phase 36 is a focused surgical change to `SidecarManager.ts`: the `_ensureExtracted` method currently reads an archive from `extension/bin/` (bundled). After this phase it must instead fetch the archive from GitHub Releases when a cache miss occurs, verify the download against a published SHA256 checksum, and only then extract. The warm path (cached binary exists) is completely unchanged and requires zero network I/O.

All required VS Code and Node.js APIs are already in use elsewhere in the extension or verified against the installed type definitions. The only prerequisite gap is `@types/node` — currently missing from `devDependencies`, causing 22 typecheck errors on the current branch. This must be added in Wave 0 before any implementation work begins.

The implementation splits cleanly into three helpers: `_fetchChecksum` (GET checksums.sha256, parse for our archive name), `_downloadAndVerify` (streaming GET with progress, incremental SHA256, write to temp path), and a refactored `_ensureExtracted` that orchestrates them when the cache misses.

**Primary recommendation:** Wave 0 installs `@types/node@^20`; Wave 1 adds `_fetchChecksum` + `_downloadAndVerify`; Wave 2 wires them into `_ensureExtracted`; Wave 3 validates typecheck green + smoke test.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Node `crypto` (built-in) | Node 18+ (bundled in VS Code Electron) | SHA256 hashing via `createHash('sha256')` | Zero external dependency; already available in extension host |
| Node `fs` (built-in) | Node 18+ | File write, existsSync, mkdirSync, rmSync | Already imported in SidecarManager |
| `fetch` (global) | Available in VS Code extension host (confirmed by existing use in BackendClient.ts, SseStream.ts, SidecarManager.ts) | HTTP GET for checksums + archive | Already used; no polyfill needed |
| `vscode.window.withProgress` | @types/vscode ^1.74.0 | Download progress notification | Official VS Code UX pattern for long operations |
| `vscode.window.showErrorMessage` | @types/vscode ^1.74.0 | Error notification with action button | Already used in extension.ts |
| `vscode.env.openExternal` | @types/vscode ^1.74.0 | Open browser to GitHub Releases fallback URL | Standard VS Code API for external links |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `@types/node` | `^20.19.37` (latest 20.x as of 2026-04-01) | TypeScript types for `crypto`, `process`, `Buffer`, `child_process`, `fs`, `net` | Wave 0 prerequisite — fixes 22 existing typecheck errors |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Node `crypto` built-in | `sha256` npm package | External dep adds bundle weight; built-in is sufficient |
| Streaming `for await...of` on `response.body` | `response.arrayBuffer()` then hash all-at-once | arrayBuffer() buffers entire archive in memory before hashing; streaming is memory-efficient and allows progress reporting |
| `vscode.window.withProgress` | Custom status bar item | withProgress is idiomatic VS Code UX for one-shot long operations; auto-dismisses on promise resolution; handles indeterminate case |

**Installation (Wave 0):**
```bash
cd extension && npm install --save-dev @types/node@^20
```

**Version verified:** `@types/node` latest 20.x = `20.19.37` (verified via `npm view @types/node@20 version` on 2026-04-01).

---

## Architecture Patterns

### Recommended Structure

The change is entirely within `extension/src/SidecarManager.ts`. No new files.

Logical helper decomposition (Claude's discretion per CONTEXT.md):

```
SidecarManager
├── _fetchChecksum(baseUrl, archiveName)          NEW — GET checksums.sha256, return expected hash string
├── _downloadAndVerify(url, tmpPath, hash, progress)  NEW — streaming download + incremental hash verify
└── _ensureExtracted(version)                     MODIFIED — replaces bin/ lookup with download flow
```

### Pattern 1: Streaming Fetch with Incremental Hash + Progress

**What:** Single pass over the response body stream — simultaneously hash each chunk and accumulate into a buffer for writing. Report progress to VS Code notification.

**When to use:** Any time a file is fetched that needs integrity verification and the user should see download progress.

**Key points (verified against Node 25 / Web Streams API):**
- `response.body` is a `ReadableStream<Uint8Array>` — supports `for await...of` in Node 21+ via `Symbol.asyncIterator`
- Must cast to `AsyncIterable<Uint8Array>` for TypeScript to accept the `for await` loop
- `crypto.createHash('sha256').update(chunk)` can be called incrementally on each chunk
- Track `lastReportedPct` and pass `pct - lastReportedPct` as the `increment` (VS Code sums deltas, not absolute values)
- Write with `fs.writeFileSync(destPath, Buffer.concat(chunks))` after hash verification passes
- Delete temp file with `fs.rmSync(tmpPath, { force: true })` on mismatch (force prevents throw if already gone)

```typescript
// Verified pattern — incremental hash + progress delta reporting
import * as crypto from 'crypto';
import * as fs from 'fs';

// Inside _downloadAndVerify:
const res = await fetch(url);
if (!res.ok) { throw new Error(`HTTP ${res.status}`); }

const contentLength = parseInt(res.headers.get('content-length') ?? '0', 10);
const hash = crypto.createHash('sha256');
const chunks: Uint8Array[] = [];
let received = 0;
let lastPct = 0;

for await (const chunk of res.body as AsyncIterable<Uint8Array>) {
  hash.update(chunk);
  chunks.push(chunk);
  received += chunk.length;
  if (contentLength > 0) {
    const pct = Math.floor((received / contentLength) * 100);
    if (pct > lastPct) {
      progress.report({ increment: pct - lastPct });
      lastPct = pct;
    }
  }
}

const digest = hash.digest('hex');
if (digest !== expectedHash) {
  fs.rmSync(destPath, { force: true });
  throw new Error(`SHA256 mismatch: expected ${expectedHash}, got ${digest}`);
}
fs.writeFileSync(destPath, Buffer.concat(chunks));
```

### Pattern 2: Checksum File Parsing

**What:** Fetch `checksums.sha256`, parse standard `sha256sum` format (`<hash>  <filename>`), extract hash for our archive name.

**When to use:** Before every cold-path download. Sequential — must complete before download begins.

**Key points (verified in Node REPL):**
- Split each line on first whitespace run: `trimmed.indexOf(' ')` gives position of the space boundary
- Slice hash = `trimmed.slice(0, spaceIdx)`, slice filename = `trimmed.slice(spaceIdx).trim()` (trims both 1-space and 2-space variants)
- Return just the hash string for the matching `archiveName`; throw if not found

```typescript
// Verified parsing — handles both single-space and double-space sha256sum format
async function _fetchChecksum(baseUrl: string, archiveName: string): Promise<string> {
  const res = await fetch(`${baseUrl}/checksums.sha256`);
  if (!res.ok) { throw new Error(`Failed to fetch checksums: HTTP ${res.status}`); }
  const text = await res.text();
  for (const line of text.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed) { continue; }
    const spaceIdx = trimmed.indexOf(' ');
    if (spaceIdx === -1) { continue; }
    const hashValue = trimmed.slice(0, spaceIdx);
    const filename = trimmed.slice(spaceIdx).trim();
    if (filename === archiveName) { return hashValue; }
  }
  throw new Error(`No checksum found for ${archiveName} in checksums.sha256`);
}
```

### Pattern 3: withProgress Wrapping the Download

**What:** Wrap the entire cold-path download sequence inside `vscode.window.withProgress`.

**Verified API signature (from `@types/vscode` installed types):**
```
withProgress<R>(
  options: ProgressOptions,
  task: (progress: Progress<{ message?: string; increment?: number }>, token: CancellationToken) => Thenable<R>
): Thenable<R>
```

- `ProgressLocation.Notification = 15`
- `cancellable: false` — no cancel button
- `increment` is a delta (not absolute); only `ProgressLocation.Notification` supports discrete progress
- If `Content-Length` is absent, do not report `increment` — notification shows as indeterminate spinner

```typescript
await vscode.window.withProgress(
  {
    location: vscode.ProgressLocation.Notification,
    title: 'Downloading Nexus backend…',
    cancellable: false,
  },
  async (progress) => {
    await this._downloadAndVerify(archiveUrl, tmpPath, expectedHash, progress);
  }
);
```

### Pattern 4: Error Notification with Action Button

**What:** Show error with a clickable button that opens the GitHub Releases page.

**Verified API signature (from `@types/vscode`):**
```
showErrorMessage<T extends string>(message: string, ...items: T[]): Thenable<T | undefined>
```

Returns the clicked item string or `undefined` if dismissed.

```typescript
const action = await vscode.window.showErrorMessage(
  `Nexus: Failed to download backend — ${errMsg}. Download manually or check your network.`,
  'Open GitHub Releases'
);
if (action === 'Open GitHub Releases') {
  await vscode.env.openExternal(vscode.Uri.parse('https://github.com/Hafiz408/Nexus/releases'));
}
```

### Pattern 5: Cache-First Guard (warm path — unchanged)

**What:** Check for the extracted executable before any network activity. Return immediately on hit.

```typescript
// Existing guard in _ensureExtracted — must remain the first check
const executablePath = path.join(cacheDir, executableName);
if (fs.existsSync(executablePath)) {
  this._channel.appendLine(`[SidecarManager] Using cached backend at ${executablePath}`);
  return executablePath;
}
// Only reach download logic on cache miss
```

### Anti-Patterns to Avoid

- **Hash-all-at-once after buffering:** `const buf = await res.arrayBuffer(); crypto.createHash...update(buf)` — works but buffers entire archive (tens of MB) in memory before hashing. Use the streaming pattern instead.
- **Writing archive to final path before verifying:** Write to a `.tmp` path, verify hash, then pass the verified path to `tar`. If mismatch, delete `.tmp` and throw. This prevents a partial or corrupt file from surviving a crash between write and verify.
- **Silently falling back to port 8000 on cold-path failure:** CONTEXT.md explicitly requires the extension to show an error and leave the sidecar not started. Do not re-use the unsupported-platform `return 'http://127.0.0.1:8000'` path for download failures.
- **Forgetting to delete temp archive on mismatch:** Success criterion 4 explicitly requires the corrupted file not survive. Use `fs.rmSync(tmpPath, { force: true })` before throwing.
- **Using `withProgress` without `cancellable: false`:** The binary is required for the extension to function; do not present a cancel button.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| SHA256 hashing | Custom byte-by-byte implementation | Node `crypto.createHash('sha256')` | Built-in, handles streaming, constant-time digest comparison |
| HTTP download with redirect following | Manual 301/302 handling | `fetch` (global) | GitHub Releases assets redirect via CDN; native `fetch` follows redirects automatically |
| Progress notification UI | Custom notification approach | `vscode.window.withProgress` + `ProgressLocation.Notification` | Official VS Code pattern; auto-dismisses on promise resolution; handles indeterminate case |
| Opening browser | Platform-specific shell command | `vscode.env.openExternal(vscode.Uri.parse(...))` | Cross-platform; works in remote extensions too |

**Key insight:** GitHub Release asset downloads redirect (302) from `github.com` to `objects.githubusercontent.com`. Node's native `fetch` follows redirects transparently — no special handling needed.

---

## Runtime State Inventory

This is a code-only change to a TypeScript source file. No databases, stored data, live service config, OS-registered state, secrets, or build artifacts contain a path that is being renamed.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — globalStorage cache dir `backend/<version>/` already uses version as key; no string changes | None |
| Live service config | None | None |
| OS-registered state | None | None |
| Secrets/env vars | None | None |
| Build artifacts | `extension/bin/` — archive no longer read by extension code after this phase; actual removal from VSIX is Phase 37 scope | None in Phase 36 |

---

## Common Pitfalls

### Pitfall 1: `@types/node` Missing — Typecheck Fails on Day 1

**What goes wrong:** The current branch already has 22 typecheck errors because `@types/node` is not in `devDependencies`. Any new code using `crypto`, `Buffer`, or `process` adds more errors.

**Why it happens:** `SidecarManager.ts` uses `child_process`, `fs`, `net`, `os`, `path`, `process`, `Buffer` — all Node built-ins — but the only `@types/*` packages installed are `@types/react`, `@types/react-dom`, and `@types/vscode`.

**How to avoid:** Wave 0 task: `npm install --save-dev @types/node@^20` inside `extension/`. This must be the first task before writing any new code.

**Warning signs:** `error TS2307: Cannot find module 'child_process'` or `error TS2580: Cannot find name 'process'` in typecheck output. Currently 22 such errors exist.

### Pitfall 2: GitHub Releases Assets Redirect — `response.ok` Check Must Follow Redirect

**What goes wrong:** GitHub Release asset URLs (`github.com/…/releases/download/…`) return a 302 redirect to `objects.githubusercontent.com`. If the redirect isn't followed, the body is empty and the hash will be wrong.

**Why it happens:** Some HTTP clients don't follow redirects by default.

**How to avoid:** Use the global `fetch` (already used throughout the extension) — it follows redirects automatically. Always check `res.ok` after `await fetch(...)`.

**Warning signs:** Empty download buffer, hash mismatch on every attempt.

### Pitfall 3: `response.body` Type Assertion Required for TypeScript

**What goes wrong:** TypeScript's DOM lib types `response.body` as `ReadableStream<Uint8Array> | null`, but the `for await...of` pattern needs `AsyncIterable<Uint8Array>`. TypeScript will complain without a cast.

**Why it happens:** The Web Streams `ReadableStream` implements `AsyncIterator` in Node 21+ but the DOM type definitions are conservative.

**How to avoid:** Cast `response.body` explicitly: `for await (const chunk of res.body as AsyncIterable<Uint8Array>)`. Verified: `response.body[Symbol.asyncIterator]` is `'function'` in Node 25.

**Warning signs:** `error TS2488: Type 'ReadableStream<Uint8Array> | null' must have a '[Symbol.asyncIterator]()' method` during typecheck.

### Pitfall 4: Progress `increment` Accumulates to 100 — Must Track Delta, Not Absolute

**What goes wrong:** `progress.report({ increment: X })` adds X to the running total. If you report cumulative percentage instead of delta, progress jumps past 100%.

**Why it happens:** `withProgress` increment is a delta. From `@types/vscode`: "Each call with an increment value will be summed up and reflected as overall progress until 100% is reached."

**How to avoid:** Track `lastPct` and report `pct - lastPct` as the increment. Update `lastPct = pct` after each report.

**Warning signs:** Progress bar fills instantly or animation looks wrong (VS Code clamps at 100 but the visual jumps).

### Pitfall 5: Writing to Final Cache Path Before Verification

**What goes wrong:** If the extension writes the archive to the final cache path and then crashes after write but before verification, the next activation finds the corrupt file and skips download (warm-path guard hit), then fails to extract.

**Why it happens:** Writing archive to the final path before hash check leaves a permanent corrupt file.

**How to avoid:** Download to a `.tmp` path (e.g., `path.join(cacheDir, archiveName + '.tmp')`), verify hash, then pass the verified path to `tar`. Delete `.tmp` on mismatch. Archive is deleted after successful extraction per CONTEXT.md, so the `.tmp` path is always cleaned up.

**Warning signs:** Extraction failures on second activation with no network activity.

### Pitfall 6: `checksums.sha256` 404 on Dev Builds Blocks Developers

**What goes wrong:** When running from a dev build (no matching GitHub Release), the `checksums.sha256` GET returns 404, triggering the "fail closed" abort. Developer can't use the extension.

**Why it happens:** Dev builds don't push to GitHub Releases.

**How to avoid:** The existing reuse-path in `start()` (`_checkHealth` on lockfile port) and the dev override check in `extension.ts` both run before `_ensureExtracted`. If a backend is already running on port 8000, `start()` returns early via the health check before reaching download logic. For the case where no backend is running AND no GitHub Release exists, handle the 404 from `_fetchChecksum` gracefully: log a warning and return `undefined` from `_ensureExtracted` (caller falls back to port 8000), rather than showing an error toast.

**Warning signs:** Developers see "Failed to download backend" error notification on every cold activate.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Archive bundled in extension `bin/` | Archive downloaded from GitHub Releases on first use | Phase 36 (v4.1) | VSIX size drops dramatically; AV false positives eliminated |
| No integrity check | SHA256 verified against published checksum before extraction | Phase 36 (v4.1) | Prevents supply chain attacks; aborts on CDN corruption |
| Silent extraction (no UX) | Progress notification on first download | Phase 36 (v4.1) | User understands why there's a delay on first activate |

**Deprecated/outdated after this phase:**
- `archivePath = path.join(this._extensionPath, 'bin', archiveName)`: Line removed. The `bin/` directory is no longer read at runtime.

---

## Open Questions

1. **`response.body` async iteration — null guard needed?**
   - What we know: `response.body` is typed as `ReadableStream<Uint8Array> | null`; for a successful response it should never be null
   - What's unclear: Whether a null guard is needed in strict TypeScript mode after adding `@types/node`
   - Recommendation: Add a null guard before the `for await` loop: `if (!res.body) { throw new Error('Response body is null'); }` — then the cast is clean

2. **404 on dev builds — warning vs. hard abort**
   - What we know: CONTEXT.md says "log warning + use fallback port 8000" for dev builds
   - What's unclear: Whether the 404 case (no GitHub Release) should be distinguished from a network error (no internet) in the log message
   - Recommendation: Use different log messages for the two cases; only show an error toast for network errors and checksum mismatches, not for the "no release found" case

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `tar` CLI | Archive extraction (existing code) | Yes | bsdtar 3.5.3 (macOS); available on Win 10+ natively | — |
| `fetch` (global) | HTTP download | Yes — confirmed by existing extension code | Node 25.1.0 on dev machine; available in VS Code extension host | — |
| Node `crypto` | SHA256 hashing | Yes | Built into Node 25.1.0 | — |
| `@types/node` | TypeScript compilation | No — must be installed in Wave 0 | 20.19.37 (latest 20.x) | None — required for typecheck to pass |
| GitHub Releases | Cold-path binary download | Yes (https://github.com/Hafiz408/Nexus/releases) | — | Dev fallback: return undefined → port 8000 if 404 |

**Missing dependencies with no fallback:**
- `@types/node`: Wave 0 must install this. Command: `cd extension && npm install --save-dev @types/node@^20`

**Missing dependencies with fallback:**
- GitHub Releases when no release exists (dev build / 404): Log warning, return `undefined` from `_ensureExtracted`, caller uses port 8000.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | TypeScript compiler (`tsc --noEmit`) — no runtime test framework exists for the extension |
| Config file | `extension/tsconfig.json` |
| Quick run command | `cd extension && npm run typecheck` |
| Full suite command | `cd extension && npm run typecheck` (no separate suite for extension) |

Note: Backend Python tests use pytest (`cd backend && python3 -m pytest`). Phase 36 makes no backend changes.

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DIST-01 | Extension downloads binary on first activation | manual smoke | Install VSIX in fresh VS Code profile, observe download notification | N/A |
| DIST-02 | No network call on warm path (cached binary exists) | manual smoke | Reactivate after first download; observe no notification | N/A |
| DIST-03 | Progress notification "Downloading Nexus backend…" shown | manual smoke | Same as DIST-01 smoke test | N/A |
| DIST-04 | Error notification + link on download failure | manual smoke | Point download URL to invalid release version, observe error message | N/A |
| DIST-05 | SHA256 mismatch aborts with error, corrupt file deleted | compile-time | `cd extension && npm run typecheck` verifies hash-compare code compiles | N/A |
| PRES-01 | All features work after download | manual smoke | Run chat/index/explain after cold-start download | N/A |
| PRES-02 | No activation delay on warm path | manual smoke | Time activation when cache exists | N/A |
| PRES-03 | Dev mode (running backend) → skip spawning | manual smoke | Start backend manually, activate extension | N/A |

### Sampling Rate
- **Per task commit:** `cd extension && npm run typecheck`
- **Per wave merge:** `cd extension && npm run typecheck`
- **Phase gate:** Typecheck green (0 errors) + manual VSIX smoke test before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `extension/package.json` — add `@types/node@^20` to `devDependencies`; run `npm install`
- [ ] Verify `npm run typecheck` passes with 0 errors after `@types/node` install (currently 22 errors)

---

## Project Constraints (from CLAUDE.md)

No `CLAUDE.md` found in the project root. No project-specific constraints to carry forward.

---

## Sources

### Primary (HIGH confidence)
- `extension/node_modules/@types/vscode/index.d.ts` — `withProgress`, `ProgressLocation`, `showErrorMessage`, `env.openExternal`, `Uri.parse` signatures verified directly from installed types
- `extension/src/SidecarManager.ts` (current file) — existing patterns for `_ensureExtracted`, `_getVersion`, `_archiveName`, `_executableName`, warm-path guard
- Node 25 REPL verification — `fetch` global, `response.body[Symbol.asyncIterator]` is `'function'`, `crypto.createHash('sha256')`, `fs.rmSync({ force: true })`, `Buffer.concat`, `fs.writeFileSync(path, Buffer)`, checksum line parsing
- `extension/package.json` — confirmed version `4.0.10`, `engines.vscode: ^1.74.0`, no `@types/node` in devDependencies
- `npm view @types/node@20 version` (2026-04-01) — confirmed latest 20.x is `20.19.37`
- `cd extension && npx tsc --noEmit` (2026-04-01) — confirmed 22 existing typecheck errors, all caused by missing `@types/node`

### Secondary (MEDIUM confidence)
- Existing codebase (`BackendClient.ts`, `SseStream.ts`, `SidecarManager.ts`) — confirms `fetch` is used throughout without polyfill; proves it is available in the VS Code extension host for this project

### Tertiary (LOW confidence)
- None — all critical claims are PRIMARY or SECONDARY confidence

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all APIs verified against installed type definitions and Node 25 REPL
- Architecture: HIGH — based on existing SidecarManager patterns + verified Node streaming API patterns
- Pitfalls: HIGH — typecheck failure confirmed by running `npm run typecheck`; other pitfalls verified via Node REPL

**Research date:** 2026-04-01
**Valid until:** 2026-07-01 (VS Code API is stable; `@types/node` version may drift but `^20` range is safe)
