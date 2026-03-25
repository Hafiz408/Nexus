# API

FastAPI routers for indexing and querying. All query responses are **Server-Sent Events (SSE)**.

## Endpoints

| Method | Path | Purpose | Response |
|---|---|---|---|
| `POST` | `/index` | Start indexing (full or incremental) | 202, runs in background |
| `GET` | `/index/status` | Poll indexing progress | `running \| complete \| failed` |
| `DELETE` | `/index` | Purge all data for a repo | Immediate |
| `POST` | `/query` | Query via SSE stream | Event stream |
| `GET` | `/health` | Health check | `{"status":"ok"}` |

## Query Routing

```
intent_hint present and not "auto"?
  YES → Agent path   (multi-agent orchestrator)
  NO  → Explore path (graph RAG + token streaming)
```

## SSE Event Sequences

**Explore path** (`intent_hint = null` or `"auto"`):
```
token × N  →  citations  →  done
```

**Agent path** (`intent_hint = explain|debug|review|test`):
```
result  →  done
```

| Event | Key fields |
|---|---|
| `token` | `content: str` |
| `citations` | `citations: [{node_id, file_path, line_start, line_end}]` |
| `done` | `retrieval_stats` (explore) or empty (agent) |
| `result` | `intent, result, has_github_token, file_written, written_path` |
| `error` | `message: str` |

Result payload shape varies by intent — see [agent README](../agent/README.md) for schemas.

## Key Design Notes

- **Graph cache** — loaded graphs are kept in `app.state.graph_cache` (per repo, in-memory) to avoid SQLite reload on every request.
- **Lazy imports** — LLM clients are imported inside request handlers, not at module level, so tests can collect without API keys.
- **Checkpointing** — LangGraph state persists to `data/checkpoints.db` (separate from the main `nexus.db`) with per-request thread IDs.
