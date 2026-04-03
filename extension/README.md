# Nexus AI — Graph-Grounded Code Intelligence

**Ask questions about your codebase in plain English. Get grounded, citation-backed answers — streamed live, right inside VS Code.**

Nexus AI builds a **call graph + vector index** of your codebase and uses it to answer questions with full structural awareness. It doesn't just search for keywords — it understands how your code is connected through a [Graph RAG pipeline](https://github.com/Hafiz408/Nexus/blob/main/backend/app/retrieval/README.md) combining semantic vector search, FTS5 keyword search, RRF rank fusion, CALLS-depth-1 graph expansion, MMR diversity selection, and cross-encoder reranking.

> **100% local & private.** Your code never leaves your machine. The index lives in `.nexus/graph.db` inside your workspace. No cloud database, no telemetry, no server to manage.

---

## What You Can Do

| Mode | Description |
|---|---|
| **Explain** | Ask anything about your code — get streamed answers with clickable file and line citations. Supports module-level code selections (reads directly from disk when the selection is not a function or class). |
| **Debug** | Point at a function — get a ranked list of suspects with anomaly scores and a root-cause diagnosis via BFS call-graph traversal |
| **Review** | Get structured findings (severity · category · suggestion) ready to post directly to a GitHub PR |
| **Test** | Generate framework-aware tests written directly into your repo |

---

## Features

- **Graph-aware retrieval** — CALLS-depth-1 expansion surfaces direct callers and callees of your seed nodes with propagated scoring (parent score × 0.6 decay). IMPORTS edges excluded to prevent cross-file noise (+115% context precision vs vector-only, RAGAS eval on fastapi corpus)
- **Dual-search + RRF pipeline** — semantic vector search and FTS5 BM25 keyword search run in parallel; scores fused via Reciprocal Rank Fusion (rank-based, immune to cosine vs BM25 scale differences). Catches exact symbol-name queries that embedding similarity alone misses
- **MMR diversity selection** — final selection penalises duplicate-file nodes (−0.35 per same-file node already chosen) so one highly-central class can't monopolise the result set; test files penalised 0.5× so source implementation consistently ranks above test files
- **Cross-encoder reranking** — `cross-encoder/ms-marco-MiniLM-L-6-v2` jointly reads each `(query, node_context)` pair and re-orders the final result set for higher relevance accuracy. Pre-warmed at startup for ~0ms first-query latency. Delivers +46% context precision and +17% answer relevancy over v2 alone (RAGAS, 30Q fastapi corpus)
- **Live streaming answers** — tokens stream into the chat panel as the LLM generates them
- **Clickable citations** — every answer links to the exact file and line number in your editor
- **Incremental re-index** — file saves trigger automatic background re-indexing with a 2s debounce; index stays current without manual intervention
- **Embedding mismatch detection** — detects when you switch embedding providers or models and blocks chat until the index is rebuilt with the new model
- **Secure API key storage** — keys stored in VS Code SecretStorage (OS keychain), never written to disk or `settings.json`
- **Multi-workspace support** — each workspace gets its own isolated `.nexus/graph.db` index; opening multiple workspaces never cross-contaminates results
- **Dev-mode passthrough** — if port 8000 is already occupied, the extension skips spawning its own backend (useful for local development)

---

## Getting Started

**1. Install**
Search `Nexus AI` in the VS Code Extensions panel and click Install.

- [VS Code Marketplace](https://marketplace.visualstudio.com/items?itemName=Hafiz408.nexus-ai)
- [Open VSX Registry](https://open-vsx.org/extension/Hafiz408/nexus-ai) — for VSCodium and other open editors

On first activation the extension downloads the backend binary for your platform from GitHub Releases, verifies its SHA256 checksum, and caches it permanently in VS Code's global storage. Subsequent activations use the local cache with no network call.

**2. Set your API key**
`Cmd+Shift+P` → `Nexus: Setup — Configure API Key` → pick your provider → paste your key.

**3. Choose your provider**
`Code → Settings → Extensions → Nexus AI` — pick chat and embedding provider and model names.

**4. Index your workspace**
`Cmd+Shift+P` → `Nexus: Index Workspace`
Chat unlocks once indexing completes. Your index is saved in `.nexus/graph.db` inside the workspace.

**5. Ask a question**
Click the Nexus AI icon in the Activity Bar and start chatting.

---

## Supported Providers

| Provider | Chat | Embeddings | Notes |
|---|---|---|---|
| OpenAI | ✓ | ✓ | |
| Mistral | ✓ | ✓ | Default |
| Anthropic | ✓ | — | Chat only |
| Google Gemini | ✓ | ✓ | |
| Ollama (local) | ✓ | ✓ | Fully offline — see below |

Mix and match — use Anthropic for chat and Mistral for embeddings, for example.

> Changing embedding provider or model requires a re-index. Nexus will warn you and disable chat until the new index is ready.

### Using Ollama (local, no API key required)

1. [Install Ollama](https://ollama.com) and pull a chat model and an embedding model:
   ```bash
   ollama pull mistral          # or llama3.1, qwen2.5, etc.
   ollama pull nomic-embed-text # recommended embedding model for Ollama
   ```
2. In VS Code settings (`Code → Settings → Extensions → Nexus AI`):
   - `nexus.chatProvider` → `ollama`
   - `nexus.chatModel` → `mistral` (or whichever you pulled)
   - `nexus.embeddingProvider` → `ollama`
   - `nexus.embeddingModel` → `nomic-embed-text`
   - `nexus.ollamaBaseUrl` → `http://localhost:11434` (default — change if Ollama runs elsewhere)
3. No API key needed — skip the `Nexus: Set API Key` step entirely.
4. Run `Nexus: Index Workspace` and start chatting.

---

## Settings

| Setting | Default | Description |
|---|---|---|
| `nexus.chatProvider` | `mistral` | LLM provider for chat |
| `nexus.chatModel` | `mistral-small-latest` | Chat model name |
| `nexus.embeddingProvider` | `mistral` | Embedding provider |
| `nexus.embeddingModel` | `mistral-embed` | Embedding model name |
| `nexus.hopDepth` | `1` | Graph traversal depth (higher = more context, slower) |
| `nexus.maxNodes` | `15` | Max context nodes per query |
| `nexus.ollamaBaseUrl` | `http://localhost:11434` | Ollama base URL |
| `nexus.backendUrl` | `http://localhost:8000` | Backend URL — override only when running the backend manually |

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
