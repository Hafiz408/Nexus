---
phase: 11-vs-code-extension
plan: "01"
subsystem: extension
tags: [vscode-extension, esbuild, typescript, react, scaffold]
dependency_graph:
  requires: []
  provides: [extension-project-structure, extension-host-bundle, extension-manifest]
  affects: [11-02, 11-03, 11-04]
tech_stack:
  added:
    - esbuild ^0.20.0
    - typescript ^5.0.0
    - react ^18.0.0
    - react-dom ^18.0.0
    - "@types/vscode ^1.74.0"
    - "@types/react ^18.x"
    - "@types/react-dom ^18.x"
  patterns:
    - dual-bundle esbuild (extension host node/cjs + webview browser/iife)
    - WebviewViewProvider skeleton with inline stub
    - retainContextWhenHidden for React state persistence
key_files:
  created:
    - extension/package.json
    - extension/tsconfig.json
    - extension/tsconfig.webview.json
    - extension/esbuild.js
    - extension/.vscodeignore
    - extension/.gitignore
    - extension/media/nexus.svg
    - extension/src/extension.ts
  modified: []
decisions:
  - "esbuild.js webview bundle failure is gracefully caught when src/webview/index.tsx not yet present — build prints warning but exits 0 so npm run build succeeds at scaffold stage"
metrics:
  duration: "3 min"
  completed: "2026-03-19"
  tasks_completed: 2
  files_created: 8
---

# Phase 11 Plan 01: VS Code Extension Scaffold Summary

**One-liner:** Dual-bundle esbuild scaffold with package.json manifest, tsconfigs, nexus.svg, and extension.ts activate() skeleton registering WebviewViewProvider and two commands.

## What Was Built

The `extension/` directory is now a standalone npm project that forms the foundation for all subsequent Phase 11 plans. Key deliverables:

- **extension/package.json** — Full VS Code manifest with `onStartupFinished` activation event, `nexus-sidebar` activitybar container, `nexus.sidebar` webview view (type:webview), `nexus.indexWorkspace`/`nexus.clearIndex` commands, and three configuration properties (`backendUrl`, `hopDepth`, `maxNodes`)
- **extension/tsconfig.json** — Extension host TypeScript config (commonjs, ES2022, excludes src/webview)
- **extension/tsconfig.webview.json** — Webview TypeScript config (react-jsx, ES2022 + DOM lib, bundler moduleResolution)
- **extension/esbuild.js** — Dual-bundle CommonJS build script: extension host (node/cjs, vscode externalized) + webview (browser/iife); webview failure gracefully skipped when entry not yet created
- **extension/media/nexus.svg** — Monochrome circuit-board icon for activity bar (16x16 SVG, #C5C5C5 stroke)
- **extension/src/extension.ts** — `activate()` with inline SidebarProvider stub, registers WebviewViewProvider with `retainContextWhenHidden: true`, two commands, EXT-04 workspaceFolders auto-index guard

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create extension/ project structure with package.json, tsconfigs, and esbuild.js | 71f8b8f | extension/package.json, tsconfig.json, tsconfig.webview.json, esbuild.js, .vscodeignore, .gitignore |
| 2 | Create media/nexus.svg, install deps, and create extension.ts skeleton | 7149d05 | extension/media/nexus.svg, extension/src/extension.ts, extension/esbuild.js |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] esbuild exits with code 1 when webview entry point missing**
- **Found during:** Task 2 verification
- **Issue:** `esbuild.context().rebuild()` throws when `src/webview/index.tsx` does not exist (Plan 03 creates it). The error propagated to the top-level `.catch()` causing `process.exit(1)`, making `npm run build` fail even though `out/extension.js` was successfully produced.
- **Fix:** Wrapped the webview `rebuild()` + `dispose()` calls in a try/catch. Extension host rebuild still throws (fail-fast). Webview failure prints a warning and continues to "Build complete." exit 0.
- **Files modified:** extension/esbuild.js
- **Commit:** 7149d05

## Verification Results

All 7 verification checks passed:
1. package.json has `"type": "webview"` in nexus-sidebar views contribution
2. esbuild.js uses `require('esbuild')` (CommonJS), not ESM import
3. tsconfig.json targets commonjs with `src/webview` in excludes
4. tsconfig.webview.json has `jsx: "react-jsx"` and `lib: ["ES2022", "DOM"]`
5. extension/node_modules/ exists (npm install succeeded, 13 packages)
6. extension/media/nexus.svg exists as valid SVG
7. extension.ts has `activate()` with `retainContextWhenHidden: true` and EXT-04 workspaceFolders guard

## Self-Check: PASSED

Files verified:
- FOUND: extension/package.json
- FOUND: extension/tsconfig.json
- FOUND: extension/tsconfig.webview.json
- FOUND: extension/esbuild.js
- FOUND: extension/media/nexus.svg
- FOUND: extension/src/extension.ts

Commits verified:
- FOUND: 71f8b8f (chore(11-01): create extension/ project structure...)
- FOUND: 7149d05 (feat(11-01): add media/nexus.svg, extension.ts skeleton...)
