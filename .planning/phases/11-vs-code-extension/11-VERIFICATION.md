---
phase: 11-vs-code-extension
verified: 2026-03-19T10:30:00Z
status: human_needed
score: 12/12 must-haves verified
re_verification: false
human_verification:
  - test: "Open extension/ folder in VS Code, press F5 to launch Extension Development Host. Verify Nexus circuit-board icon appears in Activity Bar."
    expected: "Nexus icon appears in the Activity Bar left sidebar"
    why_human: "Visual appearance of SVG icon in VS Code Activity Bar cannot be verified programmatically"
  - test: "Click the Nexus icon to open the sidebar. Verify the chat UI renders with a status bar at top, empty message list, and textarea input at bottom with placeholder 'Ask about your codebase...'"
    expected: "Sidebar opens showing the React chat UI with VS Code theme colors applied correctly"
    why_human: "Visual rendering of the webview React component and theme integration requires human inspection"
  - test: "With backend running (docker compose up), type a question and press Enter. Verify tokens stream in real-time and citations appear as clickable chips."
    expected: "Tokens stream character-by-character into the assistant message bubble; citation chips appear below the answer; clicking a chip opens the referenced file at the correct line"
    why_human: "Real-time streaming behavior, citation rendering, and file-open integration require end-to-end testing with a live backend"
  - test: "Without a backend running, type a question and press Enter. Verify an error message appears in the chat."
    expected: "Error message 'Cannot reach backend: ...' appears as an assistant message"
    why_human: "Error path behavior requires testing without backend connectivity"
---

# Phase 11: VS Code Extension Verification Report

**Phase Goal:** A developer can open the Nexus sidebar, index a workspace, and ask a question that streams back a cited answer
**Verified:** 2026-03-19T10:30:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Extension directory exists as a standalone npm project with package.json | VERIFIED | `extension/package.json` exists with engines, activationEvents, main field, contributes |
| 2 | npm install has been completed with node_modules present | VERIFIED | `extension/node_modules/` exists with esbuild, @types, react packages |
| 3 | Both bundles compiled: out/extension.js (10KB) and out/webview/index.js (1MB) | VERIFIED | `out/extension.js` 10KB, `out/webview/index.js` 1.0MB — both present |
| 4 | extension.ts activate() imports from SidebarProvider and registers nexus.sidebar provider with retainContextWhenHidden:true | VERIFIED | `extension.ts:2` imports `SidebarProvider` from `./SidebarProvider`; `extension.ts:13` has `retainContextWhenHidden: true` |
| 5 | package.json contributes activity bar icon, nexus.sidebar webview view, two commands, and three configuration properties | VERIFIED | `package.json` contributes `viewsContainers/activitybar`, `views/nexus-sidebar` with type:webview, `nexus.indexWorkspace` + `nexus.clearIndex` commands, `backendUrl`/`hopDepth`/`maxNodes` config |
| 6 | BackendClient sends POST /index and polls GET /index/status every 2 seconds until complete or failed | VERIFIED | `BackendClient.ts:7` POSTs to `/index`; `BackendClient.ts:43,55` polls every 2000ms via setInterval |
| 7 | SseStream consumes fetch() + ReadableStream with buffer accumulation for chunk boundary safety | VERIFIED | `SseStream.ts:36` uses `response.body.getReader()`; `SseStream.ts:50-51` splits on `\n\n` and retains partial buffer |
| 8 | SseStream parses event:/data: SSE lines and forwards each event to webview via postMessage | VERIFIED | `SseStream.ts:58-79` parses event/data lines; calls `webview.postMessage()` for token/citations/done/error |
| 9 | SidebarProvider.resolveWebviewView injects compiled webview bundle via asWebviewUri() with CSP nonce | VERIFIED | `SidebarProvider.ts:124-125` uses `asWebviewUri()`; `SidebarProvider.ts:127` calls `getNonce()`; CSP nonce used in HTML template at line 134 |
| 10 | SidebarProvider.onDidReceiveMessage handles query, openFile, indexWorkspace, clearIndex messages | VERIFIED | `SidebarProvider.ts:46-86` handles all four message types; openFile converts lineStart-1 (0-indexed) |
| 11 | React 18 webview renders chat with streaming, citations, and status bar | VERIFIED | `App.tsx:49` exports `App`; `index.tsx:8` uses `createRoot`; token streaming at `App.tsx:70-88`; citation chips at `App.tsx:231-242`; status bar at `App.tsx:183-213` |
| 12 | All CSS uses only --vscode-* variables, no hardcoded hex colors, no external framework | VERIFIED | `index.css` contains 36 `--vscode-*` usages; grep for `#[0-9a-fA-F]{3,6}` returns 0 matches |

**Score:** 12/12 truths verified (automated)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `extension/package.json` | Extension manifest with engines, activationEvents, contributes, scripts | VERIFIED | All fields present; type:webview confirmed; three config properties confirmed |
| `extension/tsconfig.json` | TypeScript config for extension host (commonjs) | VERIFIED | `module: commonjs`; `lib: ["ES2022","DOM"]` — DOM added for fetch/setInterval types (documented deviation) |
| `extension/tsconfig.webview.json` | TypeScript config for webview (react-jsx, dom lib) | VERIFIED | `jsx: react-jsx`; `lib: ["ES2022","DOM"]` |
| `extension/esbuild.js` | Dual-bundle build script — extension host + webview | VERIFIED | Two `esbuild.context()` calls; `external: ['vscode']`; `entryPoints: ['src/extension.ts']` |
| `extension/media/nexus.svg` | Activity bar icon (SVG) | VERIFIED | File exists at `extension/media/nexus.svg` |
| `extension/src/extension.ts` | activate() + deactivate() with provider and command registration | VERIFIED | Imports SidebarProvider; registers provider, two commands, EXT-04 auto-index guard; `deactivate()` exported |
| `extension/src/types.ts` | Discriminated union WebviewMessage type | VERIFIED | Contains `HostToWebviewMessage`, `WebviewToHostMessage`, `Citation`, `IndexStatus` |
| `extension/src/BackendClient.ts` | HTTP client with startIndex(), clearIndex(), pollUntilComplete() | VERIFIED | All four methods present; 2000ms polling confirmed |
| `extension/src/SseStream.ts` | SSE consumer using fetch + getReader + TextDecoder | VERIFIED | Uses `getReader()`, `TextDecoder`, buffer split on `\n\n` — NOT EventSource |
| `extension/src/SidebarProvider.ts` | WebviewViewProvider with resolveWebviewView and postMessage bridge | VERIFIED | Full implementation with resolveWebviewView, triggerIndex, triggerClear, all message handlers |
| `extension/src/webview/index.tsx` | React 18 createRoot entry point | VERIFIED | Uses `createRoot` from react-dom/client |
| `extension/src/webview/App.tsx` | Chat UI with message list, input, citation chips, and status bar | VERIFIED | Full implementation; acquireVsCodeApi() called once at module level |
| `extension/src/webview/index.css` | CSS using only --vscode-* variables | VERIFIED | 36 --vscode-* usages; zero hex color literals |
| `extension/out/extension.js` | Compiled extension host bundle | VERIFIED | 10KB, present at `out/extension.js` |
| `extension/out/webview/index.js` | Compiled React webview bundle | VERIFIED | 1.0MB, present at `out/webview/index.js` |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `extension.ts` | `SidebarProvider.ts` | `import { SidebarProvider } from './SidebarProvider'` | WIRED | `extension.ts:2` — real import, not inline stub |
| `SidebarProvider.ts` | `SseStream.ts` | `streamQuery()` called from onDidReceiveMessage | WIRED | `SidebarProvider.ts:3` imports; `SidebarProvider.ts:51` calls `streamQuery()` on 'query' message |
| `SseStream.ts` | `vscode.Webview` | `webview.postMessage()` for each parsed SSE event | WIRED | `SseStream.ts:27,32,70,73,76,79` — all four SSE event types forwarded |
| `BackendClient.ts` | `http://localhost:8000/index` | `fetch()` POST from extension host | WIRED | `BackendClient.ts:7` POSTs to `${backendUrl}/index` |
| `App.tsx` | `vscode.postMessage` | `acquireVsCodeApi().postMessage()` for query and citation clicks | WIRED | `App.tsx:42` API acquired once; `App.tsx:158,171,180` three postMessage call sites |
| `App.tsx` | `window.addEventListener` | message event listener for tokens/citations/done/error/indexStatus | WIRED | `App.tsx:139` — all five event types handled in switch |
| `SidebarProvider.ts` | `out/webview/index.js` | `asWebviewUri()` injects bundle path into HTML | WIRED | `SidebarProvider.ts:125` — path `'out', 'webview', 'index.js'` |
| `package.json` | `out/extension.js` | `main` field points to compiled bundle | WIRED | `package.json:8` — `"main": "./out/extension.js"` |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| EXT-01 | 11-01, 11-04 | Extension activates; registers nexus.sidebar WebviewViewProvider | SATISFIED | `extension.ts:10-15` registers provider with `retainContextWhenHidden:true` |
| EXT-02 | 11-01, 11-04 | Registers commands: nexus.indexWorkspace, nexus.clearIndex | SATISFIED | `extension.ts:18-28` registers both commands |
| EXT-03 | 11-01, 11-04 | package.json contributes activity bar icon, sidebar view, commands, and configuration | SATISFIED | `package.json` has all contributions; media/nexus.svg present |
| EXT-04 | 11-01, 11-04 | On activation with open workspace, auto-triggers indexing | SATISFIED | `extension.ts:31-33` checks `workspaceFolders` and calls `triggerIndex()` |
| CHAT-01 | 11-03 | React 18 webview shows chat messages with user and assistant roles | SATISFIED | `App.tsx:221-246` renders message-user/message-assistant CSS classes |
| CHAT-02 | 11-03 | Streaming: tokens append to last assistant message in real-time | SATISFIED | `App.tsx:68-89` — token case uses functional state update to append to last streaming assistant message |
| CHAT-03 | 11-03 | Citations rendered as clickable chips; click opens file at correct line | SATISFIED | `App.tsx:231-242` renders citation-chip buttons; `App.tsx:170-176` posts openFile; `SidebarProvider.ts:65` converts lineStart-1 |
| CHAT-04 | 11-03 | Index status bar shows Indexing spinner / Ready N nodes / Not indexed + Index button | SATISFIED | `App.tsx:183-213` covers all four states: pending/running (spinner), complete (nodes count), failed (Retry), not_indexed (Index Workspace button) |
| CHAT-05 | 11-03 | Styling uses VS Code CSS variables; no external CSS frameworks | SATISFIED | `index.css` has 36 --vscode-* usages; zero hex color literals; no framework imports |
| SSE-01 | 11-02 | BackendClient sends POST /index and polls GET /index/status every 2 seconds | SATISFIED | `BackendClient.ts:43-55` — setInterval at 2000ms; startIndex POSTs to /index |
| SSE-02 | 11-02 | SseStream.ts parses SSE stream; forwards token/citations/done/error events | SATISFIED | `SseStream.ts:36` uses fetch+getReader (not EventSource); parses event:/data: lines; forwards all four event types. Note: REQUIREMENTS.md says "native EventSource" but implementation correctly uses `fetch + ReadableStream` (EventSource is GET-only; POST /query requires fetch) — this is the correct approach documented in 11-02-SUMMARY.md |
| SSE-03 | 11-02 | SidebarProvider forwards events to Webview via webview.postMessage() | SATISFIED | `SidebarProvider.ts:53,97,100,103,113,120` — multiple postMessage call sites including status forwarding |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `App.tsx` | 255 | `placeholder="Ask about your codebase..."` | Info | This is an HTML input placeholder attribute — not a code placeholder. No impact. |

No blockers or warnings found. One informational item (HTML input placeholder) is semantically correct.

### Human Verification Required

The following items require manual testing in VS Code:

**1. Nexus icon in Activity Bar**

**Test:** Open `extension/` folder in VS Code and press F5 (with `extension/.vscode/launch.json` present)
**Expected:** Nexus circuit-board SVG icon appears in the Activity Bar alongside other extension icons
**Why human:** Visual rendering of SVG icons in VS Code Activity Bar cannot be verified programmatically

**2. Sidebar React UI renders**

**Test:** Click the Nexus icon to open the sidebar panel
**Expected:** Sidebar opens showing: status bar at top ("Not indexed" with "Index Workspace" button), empty message list area, textarea input at bottom with placeholder text "Ask about your codebase..."
**Why human:** React webview rendering, VS Code theme application, and layout cannot be verified without the VS Code runtime

**3. Streaming chat (with backend)**

**Test:** Start the backend with `docker compose up` from the nexus root, then open a workspace folder and ask a question
**Expected:** Tokens stream into the assistant message bubble in real-time; after streaming completes, citation chips appear below the answer; clicking a chip opens the referenced file at the correct line
**Why human:** Real-time streaming behavior, token-by-token UI update, and cross-boundary file navigation require end-to-end testing

**4. Error handling (without backend)**

**Test:** Ensure backend is not running, type a question and press Enter
**Expected:** An "Error: Cannot reach backend: ..." assistant message appears in the chat
**Why human:** Network error path requires testing without backend connectivity; UI rendering of error state needs visual confirmation

---

## Gaps Summary

No gaps found. All 12 automated truths are verified. All 15 artifacts pass three-level checks (exists, substantive, wired). All 8 key links are confirmed wired in source code. All 12 requirement IDs (EXT-01 through EXT-04, CHAT-01 through CHAT-05, SSE-01 through SSE-03) are satisfied with direct code evidence.

One notable deviation from plan spec: `tsconfig.json` has `lib: ["ES2022","DOM"]` instead of the plan-specified `["ES2022"]`. This was a required fix (documented in 11-02-SUMMARY.md) because `fetch`, `setInterval`, and `clearInterval` need DOM types even in Node 18+ extension host. The deviation improves correctness.

One documentation discrepancy: REQUIREMENTS.md SSE-02 says "parses native EventSource stream" but the implementation correctly uses `fetch + ReadableStream`. EventSource is GET-only and cannot POST to `/query`. The implementation matches the correct technical approach specified in the PLAN and RESEARCH files.

---

_Verified: 2026-03-19T10:30:00Z_
_Verifier: Claude (gsd-verifier)_
