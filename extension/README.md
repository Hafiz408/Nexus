# Nexus AI — Graph-Grounded Code Intelligence

**Ask questions about your codebase in plain English. Get grounded, citation-backed answers — streamed live, right inside VS Code.**

Nexus AI builds a **call graph + vector index** of your codebase and uses it to answer questions with full structural awareness. It doesn't just search for keywords — it understands how your code is connected.

> **100% local & private.** Your code never leaves your machine. The index lives in `.nexus/graph.db` inside your workspace. No cloud database, no telemetry, no server to manage.

---

## What You Can Do

| Mode | Description |
|---|---|
| **Explain** | Ask anything about your code — get streamed answers with clickable file and line citations |
| **Debug** | Point at a function — get a ranked list of suspects with anomaly scores and a root-cause diagnosis |
| **Review** | Get structured findings (severity · category · suggestion) ready to post directly to a GitHub PR |
| **Test** | Generate framework-aware tests written directly into your repo |
| **Auto** | Let Nexus classify your intent and route to the right mode automatically |

---

## Features

- **Live streaming answers** — tokens stream into the chat panel as the LLM generates them
- **Clickable citations** — every answer links to the exact file and line number in your editor
- **Graph-aware retrieval** — BFS call-graph traversal surfaces structurally connected code that pure vector search misses (+13% RAGAS score vs vector-only)
- **Incremental re-index** — file saves trigger automatic background re-indexing with a 2s debounce
- **Secure API key storage** — keys stored in VS Code SecretStorage (OS keychain), never written to disk or `settings.json`
- **GitHub PR integration** — post Review findings as inline comments directly to a pull request
- **Embedding mismatch detection** — warns and blocks chat if you switch embedding models without re-indexing
- **Multi-workspace support** — each workspace gets its own isolated `.nexus/graph.db` index
- **Dev-mode passthrough** — if port 8000 is already occupied, the extension skips spawning its own backend

---

## Zero Setup

Install the extension — that's it. The backend binary is bundled inside the extension and starts automatically when VS Code opens your workspace. No Python installation, no terminal commands, no Docker, no configuration files required.

---

## Getting Started

**1. Install**
Search `Nexus AI` in the VS Code Extensions panel and click Install, or install from [Open VSX Registry](https://open-vsx.org/extension/Hafiz408/nexus-ai) for VSCodium and other open editors.

**2. Set your API key**
`Cmd+Shift+P` → `Nexus: Setup — Configure API Key` → pick your provider → paste your key.

**3. Choose your provider**
`Code → Settings → Extensions → Nexus AI` — pick chat and embedding provider.

**4. Index your workspace**
`Cmd+Shift+P` → `Nexus: Index Workspace`
Chat unlocks once indexing completes. Your index is saved in `.nexus/graph.db` inside the workspace.

**5. Ask a question**
Click the Nexus AI icon in the Activity Bar and start chatting.

---

## Supported Providers

| Provider | Chat | Embeddings |
|---|---|---|
| OpenAI | ✓ | ✓ |
| Mistral | ✓ | ✓ |
| Anthropic | ✓ | — |
| Google Gemini | ✓ | ✓ |
| Ollama (local) | ✓ | ✓ |

Mix and match — use Anthropic for chat and Mistral for embeddings, for example.

> Changing embedding provider or model requires a re-index. Nexus will warn you and disable chat until the new index is ready.

---

## Settings

| Setting | Default | Description |
|---|---|---|
| `nexus.chatProvider` | `mistral` | LLM provider for chat |
| `nexus.chatModel` | `mistral-small-latest` | Chat model name |
| `nexus.embeddingProvider` | `mistral` | Embedding provider |
| `nexus.embeddingModel` | `mistral-embed` | Embedding model name |
| `nexus.hopDepth` | `1` | Graph traversal depth |
| `nexus.maxNodes` | `15` | Max context nodes per query |
| `nexus.ollamaBaseUrl` | `http://localhost:11434` | Ollama base URL |
| `nexus.backendUrl` | `http://localhost:8000` | Backend URL (advanced — override if running backend manually) |

---

## Commands

| Command | Description |
|---|---|
| `Nexus: Index Workspace` | Build or refresh the code index |
| `Nexus: Clear Index` | Remove the index for the current workspace |
| `Nexus: Setup — Configure API Key` | Guided setup flow to configure your API key |
| `Nexus: Set API Key (choose provider)` | Store an API key for a specific provider |
| `Nexus: Clear API Key` | Remove a stored API key |
| `Nexus: Open Settings` | Open Nexus extension settings directly |

---

## Source & License

- GitHub: [Hafiz408/Nexus](https://github.com/Hafiz408/Nexus)
- VS Code Marketplace: [Nexus AI](https://marketplace.visualstudio.com/items?itemName=Hafiz408.nexus-ai)
- Open VSX Registry: [Nexus AI](https://open-vsx.org/extension/Hafiz408/nexus-ai)
- License: MIT
- Developer docs: [DEV.md](DEV.md)
