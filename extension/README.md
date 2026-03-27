# Nexus AI — Graph-Grounded Code Intelligence

**Ask questions about your code in plain English. Get grounded, citation-backed answers — streamed live, right inside VS Code.**

Nexus AI builds a **call graph + vector index** of your codebase and uses it to answer questions with full structural awareness. It doesn't just search for keywords — it understands how your code is connected.

> **100% local & private.** Your code never leaves your machine. The index lives in `.nexus/graph.db` inside your workspace. No cloud database, no telemetry.

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

## How It Works

Nexus uses a **3-step Graph RAG pipeline**:

1. **Semantic search** — embeds your question and finds the most similar code nodes
2. **Graph expansion** — BFS traversal follows CALLS edges to surface callers and callees
3. **Rerank** — combines semantic similarity, PageRank, and call-graph centrality to pick the best context

This gives **+13% retrieval accuracy** over plain vector search, with the biggest gains in code that matters structurally but doesn't match the query keyword-for-keyword.

---

## Zero Setup

Install the extension — that's it. The backend starts automatically in the background. No Python, no Docker, no terminal commands.

---

## Getting Started

**1. Install the extension**
Search `Nexus AI` in the VS Code Extensions panel and click Install.

**2. Set your API key**
`Cmd+Shift+P` → `Nexus: Set API Key` → pick your provider → paste your key.
Keys are stored in VS Code SecretStorage (OS keychain) and never written to disk.

**3. Choose your provider**
`Code → Settings → Extensions → Nexus AI`

**4. Index your workspace**
`Cmd+Shift+P` → `Nexus: Index Workspace`
Creates `.nexus/graph.db` in your project. Chat unlocks once indexing completes.

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

> **Changing embedding provider requires a re-index.** Nexus will warn you and disable chat until the new index is ready.

---

## Settings

| Setting | Default | Description |
|---|---|---|
| `nexus.chatProvider` | `mistral` | LLM provider for chat |
| `nexus.chatModel` | `mistral-small-latest` | Chat model name |
| `nexus.embeddingProvider` | `mistral` | Embedding provider |
| `nexus.embeddingModel` | `mistral-embed` | Embedding model name |
| `nexus.hopDepth` | `1` | Graph traversal depth |
| `nexus.maxNodes` | `10` | Max context nodes per query |
| `nexus.ollamaBaseUrl` | `http://localhost:11434` | Ollama base URL |

---

## Commands

| Command | Description |
|---|---|
| `Nexus: Index Workspace` | Build or refresh the code index |
| `Nexus: Clear Index` | Remove the index for the current workspace |
| `Nexus: Set API Key` | Store an API key securely |
| `Nexus: Clear API Key` | Remove a stored API key |

---

## Source & Docs

- GitHub: [Hafiz408/Nexus](https://github.com/Hafiz408/Nexus)
- Developer docs: [DEV.md](DEV.md)
- License: MIT
