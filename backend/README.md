# Backend

FastAPI service with three independent concerns: **ingest** code into a graph + vector store, **retrieve** relevant context, **reason** via specialist agents.

## High-Level Design

```
Ingestion          Retrieval            Agents
─────────          ─────────            ──────
Parse code    →    Semantic search  →   Route intent
Build graph        Graph expand         Run specialist
Embed nodes        MMR select           Critic gate
                                        MCP side-effects
```

`query_router.py` wires these together. It picks the **Explore** path (graph RAG + token streaming) or **Agent** path (multi-agent orchestrator) based on `intent_hint` in the request.

## Structure

```
backend/
├── app/
│   ├── main.py               # FastAPI entry, CORS, lifespan
│   ├── config.py             # Pydantic settings (env fallback)
│   ├── api/                  # → HTTP routers (index + query + config + SSE)
│   ├── core/
│   │   ├── model_factory.py  # Provider-agnostic LLM + embedding clients
│   │   └── runtime_config.py # In-memory config store (POST /api/config)
│   ├── ingestion/            # → AST parsing, graph, sqlite-vec indexing
│   ├── retrieval/            # → Graph RAG pipeline
│   ├── agent/                # → Multi-agent orchestration (LangGraph)
│   ├── mcp/                  # → Side-effect tools (GitHub PR posting, test file writer)
│   └── models/               # Pydantic schemas (CodeNode, QueryRequest…)
├── build.py                  # PyInstaller build script (outputs extension/bin/)
├── tests/                    # 273 tests — all offline, no live API calls
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

Config is pushed at runtime via `POST /api/config` (from the extension). Environment variables provide fallback defaults only — runtime config takes precedence. Switching embedding providers requires a full re-index (vector dimensions differ and are tracked in `nexus_meta` table).

## Running

```bash
# Local (standard dev mode — extension's SidecarManager will skip spawn if port is already bound)
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
curl http://localhost:8000/api/health   # → {"status":"ok"}

# Build standalone binary (PyInstaller)
pip install pyinstaller
python build.py   # outputs extension/bin/nexus-backend-mac (or .exe on Windows)
```

In production use the extension auto-spawns the bundled binary — no manual startup needed.

## Tests

```bash
cd backend && python -m pytest tests/ -v    # 273 tests, no API keys required
```

## Module Docs

| Module | README |
|---|---|
| Ingestion | [app/ingestion/README.md](app/ingestion/README.md) |
| Retrieval | [app/retrieval/README.md](app/retrieval/README.md) |
| Agents | [app/agent/README.md](app/agent/README.md) |
| API | [app/api/README.md](app/api/README.md) |
| Agent Tools | [app/mcp/README.md](app/mcp/README.md) |
