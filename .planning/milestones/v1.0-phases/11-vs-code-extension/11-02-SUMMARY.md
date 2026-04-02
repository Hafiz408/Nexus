---
phase: 11-vs-code-extension
plan: "02"
subsystem: extension
tags: [vscode-extension, typescript, sse, http-client, webview-bridge]
dependency_graph:
  requires: [11-01]
  provides: [extension-host-services, sse-consumer, backend-http-client, webview-message-bridge]
  affects: [11-03, 11-04]
tech_stack:
  added: []
  patterns:
    - fetch + ReadableStream SSE consumer (not EventSource — GET-only limitation)
    - Buffer accumulation with split('\n\n') for SSE chunk boundary alignment
    - Discriminated union postMessage types for compile-time safety
    - BackendClient polling via setInterval every 2000ms
    - getNonce() + asWebviewUri() for CSP-safe webview HTML injection
key_files:
  created:
    - extension/src/types.ts
    - extension/src/BackendClient.ts
    - extension/src/SseStream.ts
    - extension/src/SidebarProvider.ts
  modified:
    - extension/tsconfig.json
decisions:
  - "fetch + ReadableStream used (not EventSource) — EventSource is GET-only; POST /query requires custom method"
  - "DOM lib added to tsconfig.json — fetch/setInterval/clearInterval types unavailable without it even in Node 18+ extension host"
  - "Buffer split on double newline preserves partial SSE events across chunk boundaries"
  - "openFile handler uses lineStart - 1 — VS Code Position is 0-indexed, API returns 1-indexed line numbers"
metrics:
  duration: "2 min"
  completed: "2026-03-19"
  tasks_completed: 2
  files_created: 4
---

# Phase 11 Plan 02: Extension Host Services Summary

**One-liner:** Four extension host TypeScript files implementing the full data flow: BackendClient HTTP polling, SseStream fetch-based SSE consumer, SidebarProvider webview bridge with nonce CSP, and shared discriminated union message types.

## What Was Built

The extension host service layer is now complete. These files proxy all network I/O between the sandboxed webview (which cannot call localhost) and the backend.

- **extension/src/types.ts** — Discriminated unions `HostToWebviewMessage` and `WebviewToHostMessage` covering all postMessage event shapes; `Citation` and `IndexStatus` interfaces shared across host and webview
- **extension/src/BackendClient.ts** — HTTP client running in Node.js extension host: `startIndex()` POST /index, `clearIndex()` DELETE /index, `getStatus()` GET /index/status, `pollUntilComplete()` polling every 2000ms per SSE-01 spec
- **extension/src/SseStream.ts** — `streamQuery()` uses `fetch()` + `response.body.getReader()` (not EventSource). Buffer accumulates raw bytes across chunk reads; splits on `\n\n` to isolate complete SSE events; parses `event:`/`data:` lines; forwards each event to `webview.postMessage()`
- **extension/src/SidebarProvider.ts** — `WebviewViewProvider` implementation: `resolveWebviewView` injects compiled webview bundle via `asWebviewUri()` with `getNonce()` CSP nonce; `onDidReceiveMessage` handles query/openFile/indexWorkspace/clearIndex; `openFile` converts 1-indexed `lineStart` to 0-indexed `vscode.Position`; `triggerIndex`/`triggerClear` proxy lifecycle to BackendClient

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create types.ts and BackendClient.ts | dde1822 | extension/src/types.ts, extension/src/BackendClient.ts, extension/tsconfig.json |
| 2 | Create SseStream.ts and SidebarProvider.ts | 5c17656 | extension/src/SseStream.ts, extension/src/SidebarProvider.ts |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] tsconfig.json missing DOM lib — fetch/setInterval/clearInterval not found**
- **Found during:** Task 1 verification
- **Issue:** `npx tsc --noEmit` reported 6 errors: `Cannot find name 'fetch'` (3x) and `Cannot find name 'setInterval'`/`clearInterval` (3x). The extension tsconfig only had `"lib": ["ES2022"]`. Even though Node 18+ ships native fetch, TypeScript requires the DOM lib to resolve these globals.
- **Fix:** Added `"DOM"` to the `lib` array in `extension/tsconfig.json`
- **Files modified:** extension/tsconfig.json
- **Commit:** dde1822

## Verification Results

All 7 verification checks passed:
1. types.ts exports `HostToWebviewMessage`, `WebviewToHostMessage`, `Citation`, `IndexStatus`
2. BackendClient has `startIndex()`, `clearIndex()`, `getStatus()`, `pollUntilComplete()` with 2000ms interval
3. SseStream uses `fetch()` + `getReader()` — no EventSource
4. SidebarProvider `resolveWebviewView` sets `enableScripts:true`, uses `asWebviewUri` + nonce CSP
5. `openFile` converts with `lineStart - 1` to produce 0-indexed `vscode.Position`
6. `retainContextWhenHidden: true` present in extension.ts (from Plan 01)
7. `tsc --noEmit` reports 0 errors

## Self-Check: PASSED
