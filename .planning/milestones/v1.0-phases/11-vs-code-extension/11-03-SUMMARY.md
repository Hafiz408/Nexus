---
phase: 11-vs-code-extension
plan: "03"
subsystem: extension/webview
tags: [vscode-extension, react18, typescript, webview, chat-ui, streaming]
dependency_graph:
  requires: [11-01]
  provides: [webview-ui, chat-message-list, streaming-token-render, citation-chips, index-status-bar]
  affects: [11-04, 11-05]
tech_stack:
  added: []
  patterns:
    - React 18 createRoot() webview entry point
    - window.postMessage / vscode.postMessage two-way bridge
    - functional setState updater for streaming token append
    - acquireVsCodeApi() called once at module level
key_files:
  created:
    - extension/src/webview/index.tsx
    - extension/src/webview/App.tsx
    - extension/src/webview/index.css
  modified: []
decisions:
  - "acquireVsCodeApi() called at module level (not inside component) — VS Code throws if called more than once per webview lifetime"
  - "Functional setState updater pattern for token append — ensures correct prev-state access in concurrent renders"
  - "status bar covers all 5 IndexStatus states: not_indexed, pending, running, complete, failed"
metrics:
  duration: "2 min"
  completed: "2026-03-19"
  tasks_completed: 2
  files_created: 3
---

# Phase 11 Plan 03: Webview Chat UI Summary

**One-liner:** React 18 webview with streaming token append, citation chips posting openFile events, and a four-state index status bar — all styled exclusively via VS Code CSS variables.

## What Was Built

Three files form the pure rendering layer of the Nexus extension webview:

- **extension/src/webview/index.tsx** — React 18 `createRoot()` entry point that mounts the `App` component into `#root`. Uses react-dom/client (not legacy ReactDOM.render).
- **extension/src/webview/App.tsx** — Full chat UI component with:
  - CHAT-01: Message list rendering user (right-aligned) and assistant (left-aligned) messages
  - CHAT-02: `window.addEventListener('message')` handler processes `token` / `citations` / `done` / `error` / `indexStatus` events; token events use functional `setState` updater to append to the last streaming assistant message in real-time
  - CHAT-03: Citation chips rendered as `<button>` elements; click posts `{ type: 'openFile', filePath, lineStart }` to the extension host via `vscode.postMessage()`
  - CHAT-04: Status bar with four rendered states: spinner for pending/running, "Ready — N nodes" for complete, "Index failed + Retry" for failed, "Not indexed + Index Workspace" otherwise
  - `acquireVsCodeApi()` called exactly once at module level to avoid VS Code's single-call constraint
- **extension/src/webview/index.css** — All styling uses `var(--vscode-*)` CSS variables exclusively. No external CSS framework, no hardcoded hex colors. Covers body layout, status bar, message bubbles, citation chips, input area, and spinner keyframe animation.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create webview/index.tsx and webview/index.css | efff61b | extension/src/webview/index.tsx, extension/src/webview/index.css |
| 2 | Create webview/App.tsx with full chat UI | a474868 | extension/src/webview/App.tsx |

## Deviations from Plan

None — plan executed exactly as written.

## Verification Results

All 8 verification checks passed:
1. index.tsx uses `createRoot()` from react-dom/client (React 18 API)
2. App.tsx: `acquireVsCodeApi()` called once at module level, stored as `const vscode`
3. `window.addEventListener('message')` handles token/citations/done/error/indexStatus
4. Token event appends to last streaming assistant message via functional setState updater
5. Citation chips call `vscode.postMessage({ type: 'openFile', filePath, lineStart })`
6. Status bar covers all states: not_indexed, pending/running spinner, complete node count, failed+retry
7. index.css contains zero hardcoded hex colors — only `var(--vscode-*)` variables
8. `tsc --noEmit -p tsconfig.webview.json` exits with 0 errors

## Self-Check: PASSED

Files verified:
- FOUND: extension/src/webview/index.tsx
- FOUND: extension/src/webview/App.tsx
- FOUND: extension/src/webview/index.css

Commits verified:
- FOUND: efff61b (feat(11-03): add webview/index.tsx React 18 entry point and index.css)
- FOUND: a474868 (feat(11-03): add webview/App.tsx full chat UI component)
