---
status: complete
phase: 35-extension-e2e
source: [manual — derived from v4.0 phases 30-35 roadmap goals + extension source code]
started: 2026-03-26T00:00:00Z
updated: 2026-03-26T00:00:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Extension Panel Loads
expected: Open VS Code on your Nexus workspace. The Nexus sidebar icon appears in the Activity Bar. Clicking it opens the Nexus panel with a chat interface visible.
result: pass

### 2. Sidecar Dev-Mode Skip (backend already running)
expected: If you already have the backend running locally on port 8000, the extension should NOT try to spawn a second binary. Open the Output panel → select "Nexus" channel. You should see a line like "[SidecarManager] Port 8000 already in use — skipping sidecar spawn (dev mode)."
result: pass

### 3. VS Code Settings Visible
expected: Open VS Code Settings (Cmd+,) and search "nexus". Settings appear for: chatProvider, chatModel, embeddingProvider, embeddingModel, backendUrl. All have sensible defaults (e.g. mistral as embedding provider).
result: pass

### 4. Set API Key Command
expected: Open Command Palette (Cmd+Shift+P) → type "Nexus: Set API Key". A provider picker appears (openai, mistral, anthropic, ollama, gemini). After selecting a provider, an input box prompts for the key. After entering a value, a confirmation toast says "Nexus: API key stored for [provider]".
result: pass

### 5. Config Push on Load
expected: With the backend running (POST /api/config endpoint live), open the Nexus Output channel. On extension activation you should see the backend receive config (or no error logged). You can also hit GET http://localhost:8000/health in a browser — it should return HTTP 200.
result: pass

### 6. Reindex Guard — Chat Blocked Before Index
expected: On a fresh workspace (never indexed), the chat input in the Nexus panel should be disabled or show a message like "Index your workspace first" / "No index found". Sending a message should not be possible until indexing is done.
result: pass

### 7. Index Workspace
expected: Click the "Index Workspace" button (or run Command Palette → "Nexus: Index Workspace"). Indexing starts — a progress indicator or status message appears. After it completes, the chat input becomes enabled.
result: pass

### 8. Status Bar Shows Active Config
expected: After config is pushed, a status bar item at the bottom of VS Code shows the active provider/model (e.g. "Nexus: mistral / mistral-embed" or similar). Hovering it may show a tooltip.
result: pass

### 9. Chat Query Returns Response
expected: With a workspace indexed, type a question in the chat box (e.g. "What does the SidecarManager do?") and press Enter. A streaming response appears in the chat panel — text flows in gradually, not all at once.
result: pass
note: LangSmith 401 warnings present — suppressed by adding LANGCHAIN_TRACING_V2=false to .env

### 10. Embedding Mismatch Warning
expected: Go to VS Code Settings and change "nexus.embeddingProvider" to a different value (e.g. from "mistral" to "openai"). A warning should appear — either a toast notification or a UI message in the panel — saying the index needs to be rebuilt because the embedding model changed.
result: pass

### 11. Clear API Key Command
expected: Open Command Palette → "Nexus: Clear API Key". A provider picker appears. Select a provider whose key you previously set. A confirmation toast says "Nexus: API key cleared for [provider]".
result: pass

### 12. File Watcher — Re-index on Save
expected: With the workspace indexed, open any source file and make a minor change (add a comment). Save the file. The extension should silently re-index the changed file in the background (no error, no full reindex required).
result: pass

## Summary

total: 12
passed: 12
issues: 0
pending: 0
skipped: 0

## Gaps

[none yet]
