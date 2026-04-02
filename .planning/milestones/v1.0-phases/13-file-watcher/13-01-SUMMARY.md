---
phase: 13-file-watcher
plan: "01"
subsystem: extension
tags: [file-watcher, incremental-index, debounce, vscode-api]
dependency_graph:
  requires: [12-01]
  provides: [WATCH-01, WATCH-02, WATCH-03]
  affects: [extension/src/FileWatcher.ts, extension/src/BackendClient.ts, extension/src/extension.ts, extension/src/SidebarProvider.ts]
tech_stack:
  added: []
  patterns:
    - FileSystemWatcher with RelativePattern scoped to workspace root
    - 2-second debounce accumulator using Set for deduplication
    - Disposable pushed to context.subscriptions for automatic lifecycle management
    - Shared BackendClient instance passed via constructor injection
key_files:
  created:
    - extension/src/FileWatcher.ts
  modified:
    - extension/src/BackendClient.ts
    - extension/src/extension.ts
    - extension/src/SidebarProvider.ts
decisions:
  - FileWatcher uses RelativePattern(workspaceFolder, ...) to scope OS-level watch to workspace root only — bare string glob would watch all VS Code FS windows globally
  - pendingFiles cleared before async _flush() call — prevents race where second timer fires into non-empty set after first flush starts
  - indexFiles does not call pollUntilComplete — incremental re-index is fast; fire-and-forget is appropriate; sidebar updates via next poll cycle
  - SidebarProvider constructor changed to required second BackendClient param — extension.ts is the sole caller; optional param adds unnecessary complexity
  - Single BackendClient in activate() shared by SidebarProvider and FileWatcher — eliminates duplicate config reads and potential URL mismatch
metrics:
  duration: "2 min"
  completed: "2026-03-19"
  tasks_completed: 2
  files_modified: 4
---

# Phase 13 Plan 01: File Watcher Summary

**One-liner:** FileSystemWatcher with 2-second debounce accumulator sending incremental changed_files payload to POST /index on every source file save.

## What Was Built

Automatic incremental re-indexing triggered on every `.py`, `.ts`, `.tsx`, `.js`, or `.jsx` file save within the VS Code workspace. Rapid successive saves are coalesced by a Set-based 2-second debounce accumulator, so only one POST /index request fires after the quiet period ends.

### Key Components

**FileWatcher.ts (new):** Standalone disposable class following the HighlightService lifecycle pattern. Uses `vscode.RelativePattern` scoped to the first workspace folder to prevent watching unrelated VS Code windows. Subscribes to `onDidChange` and `onDidCreate` (not `onDidDelete`). The debounce timer resets on every event; the accumulated Set deduplicates rapid multi-fire saves of the same file. `_pendingFiles` is cleared before the async `_flush()` call to prevent race conditions with concurrent timers.

**BackendClient.ts (updated):** Added `indexFiles(repoPath: string, changedFiles: string[])` method that POSTs `{ repo_path, changed_files: [...] }` to `/index`. Returns without polling — incremental re-index is fast and fire-and-forget is appropriate per research.

**extension.ts (updated):** Constructs one shared `BackendClient` in `activate()` and passes it to both `SidebarProvider` and `FileWatcher`. `FileWatcher` is pushed to `context.subscriptions` so VS Code calls `dispose()` automatically on deactivation — no OS-level file watch leaks.

**SidebarProvider.ts (updated):** Constructor signature changed to accept `BackendClient` as a required second parameter instead of constructing its own instance internally. The `backendUrl` read in `resolveWebviewView` for `streamQuery` is unaffected.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | FileWatcher class and BackendClient.indexFiles method | 4bc6ce1 | FileWatcher.ts (new), BackendClient.ts |
| 2 | Wire FileWatcher into extension.ts (shared BackendClient) | 575ba6e | extension.ts, SidebarProvider.ts |

## Verification Results

All 5 post-completion checks passed:
1. `npx tsc --noEmit` — 0 TypeScript errors across all extension source files
2. `createFileSystemWatcher` confirmed in FileWatcher.ts
3. `changed_files` confirmed in BackendClient.ts POST body
4. `new FileWatcher` confirmed in extension.ts
5. `context.subscriptions.push(watcher)` confirmed in extension.ts

## Deviations from Plan

None - plan executed exactly as written.

## Requirements Fulfilled

- WATCH-01: FileWatcher watches `**/*.{py,ts,tsx,js,jsx}` via RelativePattern scoped to workspace root
- WATCH-02: Debounce timer resets on each file event; single flush fires after 2-second quiet period with Set-based deduplication
- WATCH-03: BackendClient.indexFiles sends `{ repo_path, changed_files: [...] }` to POST /index for incremental re-index
