# Phase 13: File Watcher - Research

**Researched:** 2026-03-19
**Domain:** VS Code Extension API — FileSystemWatcher, debounce, incremental re-index
**Confidence:** HIGH

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| WATCH-01 | `FileWatcher` watches `**/*.{py,ts,tsx,js,jsx}` via `vscode.workspace.createFileSystemWatcher` | API signature, RelativePattern glob, onDidChange/onDidCreate events documented |
| WATCH-02 | Debounces 2 seconds after last file change before triggering re-index | Debounce-with-timer pattern verified; standard `setTimeout`/`clearTimeout` approach works cleanly in extension host |
| WATCH-03 | Sends `POST /index` with `changed_files: [filePath]` for incremental re-index | Backend `IndexRequest.changed_files: list[str] | None` already exists; `BackendClient.startIndex` needs a new overload or second method |
</phase_requirements>

---

## Summary

Phase 13 adds a `FileWatcher` class to the VS Code extension that monitors source files for changes and triggers incremental re-indexing automatically. The entire feature lives in the extension host (TypeScript), not the backend — the backend already supports incremental indexing via the `changed_files` field on `POST /index` (see `IndexRequest` in `backend/app/models/schemas.py`).

The VS Code API provides `vscode.workspace.createFileSystemWatcher(pattern)` which fires `onDidChange`, `onDidCreate`, and `onDidDelete` events. For this phase, only `onDidChange` and `onDidCreate` are relevant (file saves and new file additions both invalidate the index). Deletion is not required by the success criteria.

The debounce requirement (2-second quiet period, WATCH-02) is straightforward using native `setTimeout`/`clearTimeout` — no external library needed. A single timer is reset on each incoming event; when the timer fires, one `POST /index` call is made with the accumulated changed file paths. The `BackendClient` needs a new method or extended signature to pass `changed_files`.

**Primary recommendation:** Create `FileWatcher.ts` as a standalone class following the same `dispose()` lifecycle pattern as `HighlightService.ts`. Wire it into `extension.ts` activation, pushing to `context.subscriptions`.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `vscode` (built-in) | ^1.74.0 (already in package.json) | `createFileSystemWatcher`, `RelativePattern`, `Uri` | It IS the VS Code extension API — no alternative |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Native `setTimeout`/`clearTimeout` | Node.js built-in | Debounce timer | No external dependency needed; extension host is Node.js |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `setTimeout` debounce | `lodash.debounce` | lodash adds a dependency; the single-timer pattern is 10 lines and zero risk — use native |
| `onDidChange` + `onDidCreate` separate handlers | Single handler for both events | Two separate subscriptions on the same watcher is cleaner and explicit; both feed the same debounce accumulator |

**Installation:**
No new packages required. Everything is available via the existing `vscode` engine dependency.

---

## Architecture Patterns

### Recommended Project Structure
```
extension/src/
├── FileWatcher.ts       # NEW — FileSystemWatcher + debounce logic
├── BackendClient.ts     # MODIFY — add indexFiles(repoPath, changedFiles) method
├── extension.ts         # MODIFY — instantiate FileWatcher, push to subscriptions
├── HighlightService.ts  # unchanged
├── SidebarProvider.ts   # unchanged
├── SseStream.ts         # unchanged
└── types.ts             # unchanged
```

### Pattern 1: Standalone Disposable Class (mirrors HighlightService)

**What:** `FileWatcher` encapsulates the watcher, debounce timer, and pending file set. Exposes `dispose()` which calls `watcher.dispose()` and clears the timer.

**When to use:** Any VS Code resource that must be cleaned up on extension deactivation.

**Example:**
```typescript
// Source: pattern established by HighlightService.ts in this project
import * as vscode from 'vscode';
import { BackendClient } from './BackendClient';

export class FileWatcher {
  private readonly _watcher: vscode.FileSystemWatcher;
  private _debounceTimer: ReturnType<typeof setTimeout> | undefined;
  private _pendingFiles: Set<string> = new Set();

  constructor(
    private readonly _repoPath: string,
    private readonly _client: BackendClient
  ) {
    // WATCH-01: RelativePattern scopes watcher to workspace root
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    const pattern = workspaceFolder
      ? new vscode.RelativePattern(workspaceFolder, '**/*.{py,ts,tsx,js,jsx}')
      : '**/*.{py,ts,tsx,js,jsx}';

    this._watcher = vscode.workspace.createFileSystemWatcher(pattern);

    // WATCH-01: subscribe to save and new-file events
    this._watcher.onDidChange(uri => this._onFileEvent(uri));
    this._watcher.onDidCreate(uri => this._onFileEvent(uri));
  }

  private _onFileEvent(uri: vscode.Uri): void {
    // WATCH-02: accumulate files, reset 2-second debounce timer
    this._pendingFiles.add(uri.fsPath);
    if (this._debounceTimer !== undefined) {
      clearTimeout(this._debounceTimer);
    }
    this._debounceTimer = setTimeout(() => {
      void this._flush();
    }, 2000);
  }

  private async _flush(): Promise<void> {
    this._debounceTimer = undefined;
    const files = Array.from(this._pendingFiles);
    this._pendingFiles.clear();
    if (files.length === 0) { return; }
    // WATCH-03: send only changed file paths
    await this._client.indexFiles(this._repoPath, files);
  }

  dispose(): void {
    if (this._debounceTimer !== undefined) {
      clearTimeout(this._debounceTimer);
    }
    this._watcher.dispose();
  }
}
```

### Pattern 2: New BackendClient Method for Incremental Index

**What:** Add `indexFiles(repoPath, changedFiles)` to `BackendClient` that sends `changed_files` in the POST body.

**When to use:** Whenever incremental re-index is needed (Phase 13 only, for now).

**Example:**
```typescript
// Extends existing BackendClient.ts
async indexFiles(repoPath: string, changedFiles: string[]): Promise<void> {
  const res = await fetch(`${this.backendUrl}/index`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ repo_path: repoPath, changed_files: changedFiles }),
  });
  if (!res.ok) {
    throw new Error(`POST /index (incremental) failed: ${res.status}`);
  }
}
```

The backend `IndexRequest` model already has `changed_files: list[str] | None = None` — no backend changes needed.

### Pattern 3: Wiring into extension.ts

**What:** Instantiate `FileWatcher` after the workspace is confirmed open; push its disposable to `context.subscriptions`.

**Example:**
```typescript
// extension.ts — add after existing subscriptions
import { FileWatcher } from './FileWatcher';

// Inside activate():
if (vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders.length > 0) {
  const repoPath = vscode.workspace.workspaceFolders[0].uri.fsPath;
  const watcher = new FileWatcher(repoPath, client);
  context.subscriptions.push(watcher);
  // auto-index also fires here per EXT-04 (already present)
}
```

Note: `context.subscriptions.push(watcher)` works because VS Code calls `dispose()` on everything in that array at deactivation. `FileWatcher` must therefore implement the `vscode.Disposable` interface (just needs a `dispose()` method — no need to explicitly `implements vscode.Disposable`).

### Anti-Patterns to Avoid

- **Creating the watcher outside a workspace guard:** `createFileSystemWatcher` with a bare string pattern (not `RelativePattern`) watches ALL of the VS Code file system, not just the current workspace. Always use `RelativePattern(workspaceFolder, ...)` when a workspace folder is available.
- **Not disposing the watcher:** Failing to call `watcher.dispose()` leaves OS-level file watches open. Always push to `context.subscriptions` or call `dispose()` explicitly.
- **Firing one HTTP request per file event:** Without debounce, rapid saves (e.g., format-on-save + auto-import) trigger dozens of `/index` calls per second. Always accumulate in a `Set` and flush after the quiet period.
- **Not clearing the pending set before the async call:** If `_flush()` is slow (backend busy), a second timer could fire before it completes. Clear `_pendingFiles` before the async call (already shown in Pattern 1 above).
- **Calling `pollUntilComplete` for incremental re-index:** The incremental path is fast (single file). Calling the polling loop adds 2+ seconds of overhead. For `FileWatcher`, fire-and-forget with `indexFiles()` is appropriate — the sidebar status will update via the next poll cycle anyway.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| File system watching | Custom `fs.watch` watcher | `vscode.workspace.createFileSystemWatcher` | The VS Code API handles OS-level differences, workspace boundaries, `files.watcherExclude` settings, recursive watching on all platforms |
| Debounce utility | Custom delay manager class | `setTimeout`/`clearTimeout` (10 lines) | Lodash adds a dependency; the single-timer pattern is sufficient and zero-risk |
| Glob matching | Custom extension-filter logic | `RelativePattern` glob `**/*.{py,ts,tsx,js,jsx}` | The watcher filters at the OS level — no application-layer filtering needed |

**Key insight:** VS Code's `createFileSystemWatcher` with `RelativePattern` handles platform differences (macOS FSEvents, Linux inotify, Windows ReadDirectoryChangesW) transparently. Hand-rolling with `fs.watch` would re-introduce all those platform bugs.

---

## Common Pitfalls

### Pitfall 1: Bare String Pattern Watches Everything
**What goes wrong:** `createFileSystemWatcher('**/*.ts')` without a `RelativePattern` fires for ALL TypeScript files across all open VS Code windows, not just the current workspace.
**Why it happens:** Without a base folder, VS Code treats the pattern as global.
**How to avoid:** Always use `new vscode.RelativePattern(vscode.workspace.workspaceFolders[0], '**/*.{py,ts,tsx,js,jsx}')`.
**Warning signs:** Watcher fires on files in `~/.vscode/extensions/` or other projects.

### Pitfall 2: onDidChange Fires Multiple Times Per Save
**What goes wrong:** A single "save" can fire `onDidChange` 2-4 times (write + flush + metadata update) depending on the editor configuration (format-on-save, ESLint fix-on-save, etc.).
**Why it happens:** The OS reports each write to the file as a separate change event.
**How to avoid:** The 2-second debounce timer in WATCH-02 absorbs all of these. This is exactly why debounce is required.
**Warning signs:** Seeing multiple consecutive `/index` requests for the same file in backend logs.

### Pitfall 3: `context.subscriptions` Expects `dispose()` Method
**What goes wrong:** If `FileWatcher` doesn't have a `dispose()` method, pushing it to `context.subscriptions` causes a TypeScript type error and the watcher never gets cleaned up.
**Why it happens:** `context.subscriptions` is `vscode.Disposable[]`.
**How to avoid:** Implement `dispose()` that calls `this._watcher.dispose()` and clears the timer. VS Code will call it on deactivation automatically.

### Pitfall 4: `BackendClient` is Already Constructed in SidebarProvider
**What goes wrong:** Creating a second `BackendClient` in `FileWatcher`'s constructor doubles the object, but the `backendUrl` config might diverge if the user changes it between constructions.
**Why it happens:** Extension constructs `BackendClient` per-class rather than sharing.
**How to avoid:** Pass the existing `BackendClient` instance into `FileWatcher` as a constructor parameter (see Pattern 1). The `extension.ts` activation function is the natural place to construct one `BackendClient` and share it — OR, keep `FileWatcher` accepting `BackendClient` as a parameter and the caller (SidebarProvider or extension.ts) passes theirs in.
**Note:** Currently `SidebarProvider` constructs its own `BackendClient`. The simplest approach for Phase 13 is to have `extension.ts` construct one shared `BackendClient` and pass it to both `SidebarProvider` and `FileWatcher`. However, reviewing `SidebarProvider`'s constructor, it reads `backendUrl` from config internally. The cleanest minimal-change approach: `extension.ts` reads `backendUrl` once and constructs a shared `BackendClient`, then passes it to both. This is a small refactor but avoids duplication.

### Pitfall 5: Timer Leaks on Rapid Deactivation
**What goes wrong:** If VS Code deactivates the extension while the debounce timer is pending, the `setTimeout` callback fires after disposal, calling a disposed `BackendClient` or a cleared `_pendingFiles` set.
**Why it happens:** `setTimeout` callbacks fire even after the calling scope is garbage-collected unless explicitly cancelled.
**How to avoid:** `dispose()` must call `clearTimeout(this._debounceTimer)` before `this._watcher.dispose()`. The Pattern 1 example above handles this.

---

## Code Examples

Verified patterns from official sources:

### createFileSystemWatcher with RelativePattern
```typescript
// Source: vscode API docs — https://code.visualstudio.com/api/references/vscode-api
// RelativePattern scopes watcher to workspace; '**/*.{py,ts,tsx,js,jsx}' matches target extensions
const folder = vscode.workspace.workspaceFolders![0];
const pattern = new vscode.RelativePattern(folder, '**/*.{py,ts,tsx,js,jsx}');
const watcher = vscode.workspace.createFileSystemWatcher(pattern);

watcher.onDidChange(uri => console.log('changed:', uri.fsPath));
watcher.onDidCreate(uri => console.log('created:', uri.fsPath));
// Dispose when done — always required
watcher.dispose();
```

### Single-timer debounce (no external library)
```typescript
// Source: standard Node.js pattern used throughout this project
let debounceTimer: ReturnType<typeof setTimeout> | undefined;
const pending = new Set<string>();

function onEvent(path: string): void {
  pending.add(path);
  if (debounceTimer !== undefined) { clearTimeout(debounceTimer); }
  debounceTimer = setTimeout(() => {
    debounceTimer = undefined;
    const files = Array.from(pending);
    pending.clear();
    void sendRequest(files);
  }, 2000);
}
```

### BackendClient incremental index call
```typescript
// Extends BackendClient.ts — sends changed_files matching IndexRequest schema
async indexFiles(repoPath: string, changedFiles: string[]): Promise<void> {
  const res = await fetch(`${this.backendUrl}/index`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ repo_path: repoPath, changed_files: changedFiles }),
  });
  if (!res.ok) {
    throw new Error(`POST /index (incremental) failed: ${res.status}`);
  }
}
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `fs.watch` / `chokidar` in extension | `vscode.workspace.createFileSystemWatcher` | VS Code 1.x (always) | Platform-safe; uses VS Code's own parcel-watcher infrastructure |
| Global string glob (no RelativePattern) | `RelativePattern(folder, glob)` | VS Code 1.74+ (our min engine) | Scopes watch to workspace, respects `files.watcherExclude` |

**Note:** As of September 2024 VS Code moved to correlated file watchers internally, but uncorrelated watchers (the public API) still work correctly for this use case. The change is transparent to extension authors.

---

## Open Questions

1. **Should `BackendClient` be refactored to be shared between `SidebarProvider` and `FileWatcher`?**
   - What we know: Currently `SidebarProvider` creates its own `BackendClient` in its constructor. `FileWatcher` needs one too.
   - What's unclear: Whether `extension.ts` should own a single `BackendClient` passed to both, or whether `FileWatcher` should construct its own.
   - Recommendation: Construct one `BackendClient` in `extension.ts` `activate()`, pass it to both `SidebarProvider` and `FileWatcher`. This requires a small `SidebarProvider` constructor signature change (accept `BackendClient` as parameter instead of creating it internally). This is the cleaner design. However, if minimizing change is preferred, `FileWatcher` can construct its own `BackendClient` reading from config — both work.

2. **Should `onDidDelete` be wired?**
   - What we know: WATCH-01, WATCH-02, WATCH-03 success criteria reference only saves (`.py`, `.ts`, etc.) triggering re-index. WATCH-03 says "changed file path."
   - What's unclear: Whether deleting a file should trigger cleanup.
   - Recommendation: Do NOT wire `onDidDelete` for Phase 13 — the success criteria don't mention it and the backend's `delete_nodes_for_files` is already called automatically at the start of every incremental run for the changed files. Keep scope minimal.

---

## Sources

### Primary (HIGH confidence)
- VS Code Extension API — `vscode.workspace.createFileSystemWatcher`, `RelativePattern`, `FileSystemWatcher` interface: https://code.visualstudio.com/api/references/vscode-api
- VS Code File Watcher Internals wiki (September 2024 update): https://github.com/microsoft/vscode/wiki/File-Watcher-Internals
- Project source: `extension/src/HighlightService.ts` — dispose pattern, timer management
- Project source: `extension/src/BackendClient.ts` — existing HTTP client interface
- Project source: `backend/app/models/schemas.py` — `IndexRequest.changed_files: list[str] | None` already present
- Project source: `extension/src/extension.ts` — activation wiring patterns
- Project source: `extension/src/SidebarProvider.ts` — BackendClient construction pattern

### Secondary (MEDIUM confidence)
- vscode-sftp extension `fileWatcher.ts` — real-world debounce with `Set<Uri>` queue pattern: https://github.com/liximomo/vscode-sftp/blob/master/src/modules/fileWatcher.ts
- VS Code API unofficial reference — FileSystemWatcher interface properties: https://www.vscodeapi.com/interfaces/vscode.filesystemwatcher

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — `vscode.workspace.createFileSystemWatcher` is the only VS Code API for this; verified via official docs
- Architecture: HIGH — patterns directly mirror `HighlightService.ts` already in this codebase; no new paradigms
- Pitfalls: HIGH — verified from official VS Code File Watcher Internals wiki and project STATE.md accumulated decisions

**Research date:** 2026-03-19
**Valid until:** 2026-04-19 (stable VS Code API; RelativePattern behavior is long-settled)
