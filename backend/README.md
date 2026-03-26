# Backend

FastAPI service with three independent concerns: **ingest** code into a graph + vector store, **retrieve** relevant context, **reason** via specialist agents.

## High-Level Design

```
Ingestion          Retrieval            Agents
─────────          ─────────            ──────
Parse code    →    Semantic search  →   Route intent
Build graph        BFS expand           Run specialist
Embed nodes        Rerank               Critic gate
                                        MCP side-effects
```

`query_router.py` wires these together. It picks the **Explore** path (graph RAG + token streaming) or **Agent** path (multi-agent orchestrator) based on `intent_hint` in the request.

## Structure

```
backend/
├── app/
│   ├── main.py               # FastAPI entry, CORS, lifespan
│   ├── config.py             # Pydantic settings (.env-driven)
│   ├── api/                  # → HTTP routers (index + query + SSE)
│   ├── core/
│   │   ├── model_factory.py  # Provider-agnostic LLM + embedding clients
│   │   └── runtime_config.py # In-memory config store (POST /api/config)
│   ├── ingestion/            # → AST parsing, graph, vector indexing
│   ├── retrieval/            # → Graph RAG pipeline
│   ├── agent/                # → Multi-agent orchestration (LangGraph)
│   ├── mcp/                  # → GitHub PR + file-write tools
│   └── models/               # Pydantic schemas (CodeNode, QueryRequest…)
├── tests/                    # 190+ tests — all offline, no live API calls
├── Dockerfile
└── requirements.txt
```

## Model Factory

All LLM and embedding calls route through `core/model_factory.py` — no provider-specific code in agents.

| Provider | Embedding dims | LLM support |
|---|---|---|
| Mistral | 1024 | ✓ |
| OpenAI | 1536 | ✓ |
| Anthropic | — | ✓ (chat only) |
| Ollama | 768 | ✓ |
| Gemini | 768 | ✓ |

Config is pushed at runtime via `POST /api/config` (from the extension) and seeded from `.env` on startup. Switching embedding providers requires a full re-index (vector dimensions differ).

## Running

```bash
# Docker (recommended — includes hot reload via volume mount)
docker compose up --build
curl http://localhost:8000/api/health   # → {"status":"ok"}

# Local
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## Tests

```bash
python -m pytest backend/tests/ -v    # 190+ tests, no API keys required
```

## Module Docs

| Module | README |
|---|---|
| Ingestion | [app/ingestion/README.md](app/ingestion/README.md) |
| Retrieval | [app/retrieval/README.md](app/retrieval/README.md) |
| Agents | [app/agent/README.md](app/agent/README.md) |
| API | [app/api/README.md](app/api/README.md) |
| MCP Tools | [app/mcp/README.md](app/mcp/README.md) |
