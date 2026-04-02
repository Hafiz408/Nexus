---
status: complete
phase: 29-extension-integration
source: [verified from feature/v3-local-first-privacy — EXT-01, EXT-02 implemented in Phase 28]
started: 2026-03-25T00:00:00Z
updated: 2026-03-25T00:00:00Z
---

## Current Test

[testing complete]

## Tests

### 1. EXT-01: Extension derives workspace db path
expected: SidebarProvider.ts has _dbPath getter that returns path.join(repoPath, '.nexus', 'graph.db') and sends it with every index and query request.
result: pass

### 2. EXT-02: db_path in all BackendClient methods
expected: BackendClient.startIndex, clearIndex, indexFiles all accept dbPath param and include it in request body. SseStream.streamQuery includes db_path in POST body.
result: pass

### 3. getStatus accepts optional db_path
expected: BackendClient.getStatus accepts optional dbPath param (backwards-compatible — status endpoint reads in-memory state, no db_path required server-side).
result: pass

### 4. No hardcoded paths in extension
expected: Extension never constructs a path to data/nexus.db or any server-side path. Only .nexus/graph.db relative to workspace root.
result: pass

## Summary

total: 4
passed: 4
issues: 0
pending: 0
skipped: 0

## Gaps

[none]
