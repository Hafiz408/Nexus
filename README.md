# Nexus — Graph-Grounded Code Intelligence

AI-powered code assistant that understands your codebase through a **call graph + vector index**. Ask questions in plain English; get grounded, citation-backed answers with file/line references — streamed live in VS Code.

## Features

| Mode | What it does |
|---|---|
| **Explain** | Semantic + graph-aware retrieval; streams tokens with clickable file citations |
| **Debug** | BFS call-graph traversal, anomaly scoring, ranked suspect list with diagnosis |
| **Review** | Structured findings (severity · category · suggestion), postable to GitHub PRs |
| **Test** | Framework-aware test generation written directly to your repo |
| **Auto** | LLM classifies intent and routes to the right specialist automatically |

## Architecture

```
┌──────────────────────────────────────┐
│         VS Code Extension            │
│  Sidebar UI · FileWatcher · SSE      │
└──────────────────┬───────────────────┘
                   │ HTTP + SSE
                   ▼
┌──────────────────────────────────────┐
│           FastAPI Backend            │
│                                      │
│  Ingestion ──► Graph + Vectors       │
│                     │                │
│  Query ──► Retrieval ──► Agents      │
│                     │                │
│            MCP Tools (PR · files)    │
└──────────┬───────────────────────────┘
           │
  ┌────────┴────────┐
  │ PostgreSQL      │  SQLite
  │ pgvector        │  graph · FTS · checkpoints
  └─────────────────┘
```

## Query Flow

```
Question
  │
  ├─ Embed → pgvector cosine search (top-k seeds)
  ├─ BFS expand via call graph (callers + callees)
  ├─ Rerank: semantic + 0.2×PageRank + 0.1×in-degree
  │
  └─ intent = explain?  → stream tokens → file citations
     intent = debug/review/test?
       → Specialist agent
           → Critic (score = 0.4G + 0.35R + 0.25A)
               └── score < 0.7 → retry (max 2×)
```

## Setup

**Prerequisites:** Docker Compose · VS Code 1.74+ · Python 3.10+ · Mistral or OpenAI API key

```bash
# 1. Backend
cp .env.example .env      # set your API key
docker compose up -d
curl http://localhost:8000/health   # → {"status":"ok"}

# 2. Extension
cd extension && npm install && npm run build
# VS Code: load unpacked from ./out/

# 3. Index a repo
# Ctrl+Shift+P → "Nexus: Index Workspace"
```

### Key `.env` Variables

```bash
embedding_provider=mistral    # mistral | openai
llm_provider=mistral
mistral_api_key=sk-...        # or openai_api_key
```

## Structure

```
nexus/
├── backend/           → FastAPI service
│   └── app/
│       ├── api/       → HTTP endpoints + SSE routing
│       ├── ingestion/ → AST parsing, graph, vector index
│       ├── retrieval/ → 3-step Graph RAG pipeline
│       ├── agent/     → Multi-agent orchestration
│       ├── core/      → Provider-agnostic model factory
│       └── mcp/       → GitHub PR + file-write tools
├── extension/         → VS Code extension (TypeScript + React)
├── eval/              → RAGAS evaluation suite
└── docker-compose.yml
```

## Docs

| Area | |
|---|---|
| Backend | [backend/README.md](backend/README.md) |
| Ingestion | [backend/app/ingestion/README.md](backend/app/ingestion/README.md) |
| Retrieval | [backend/app/retrieval/README.md](backend/app/retrieval/README.md) |
| Agents | [backend/app/agent/README.md](backend/app/agent/README.md) |
| API | [backend/app/api/README.md](backend/app/api/README.md) |
| MCP Tools | [backend/app/mcp/README.md](backend/app/mcp/README.md) |
| Extension | [extension/README.md](extension/README.md) |
| Evaluation | [eval/README.md](eval/README.md) |
