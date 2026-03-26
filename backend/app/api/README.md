# API

FastAPI routers for indexing, querying, and runtime configuration. All query responses are **Server-Sent Events (SSE)**.

## Endpoints

| Method | Path | Purpose | Response |
|---|---|---|---|
| `POST` | `/api/config` | Push provider/model/key config at runtime | `{"status":"ok", "reindex_required": bool}` |
| `GET` | `/api/config/status` | Read active runtime config (keys redacted) | Config object |
| `GET` | `/api/health` | Readiness check (polled by SidecarManager) | `{"status":"ok"}` |
| `POST` | `/index` | Start indexing (full or incremental) | 202, runs in background |
| `GET` | `/index/status` | Poll indexing progress | `running \| complete \| failed` |
| `DELETE` | `/index` | Purge all data for a repo | Immediate |
| `POST` | `/query` | Query via SSE stream | Event stream |
| `POST` | `/review/post-pr` | Post review findings to GitHub PR | Immediate |

## Query Routing

```
intent_hint = debug | review | test?
  YES → Agent path   (multi-agent orchestrator)
  NO  → Streaming path (graph RAG + token streaming)
        covers: null / "auto" / "explain"
```

`explain` was unified with the streaming path — it no longer goes through the LangGraph orchestrator.

## SSE Event Sequences

**Streaming path** (`intent_hint = null`, `"auto"`, or `"explain"`):
```
token × N  →  citations  →  done
```

**Agent path** (`intent_hint = debug | review | test`):
```
result  →  done
```

| Event | Key fields |
|---|---|
| `token` | `content: str` |
| `citations` | `citations: [{node_id, file_path, line_start, line_end}]` |
| `done` | `retrieval_stats` (streaming) or empty (agent) |
| `result` | `intent, result, has_github_token, file_written, written_path` |
| `error` | `message: str` |

Result payload shape varies by intent — see [agent README](../agent/README.md) for schemas.

## Key Design Notes

- **Graph cache** — loaded graphs are kept in `app.state.graph_cache` (per repo, in-memory) to avoid SQLite reload on every request.
- **Lazy imports** — LLM clients are imported inside request handlers, not at module level, so tests can collect without API keys.
- **Checkpointing** — LangGraph state persists to a separate `checkpoints.db` (not `graph.db`) with per-request thread IDs.
- **db_path per request** — every request carries a `db_path` pointing to `.nexus/graph.db` in the workspace; the backend is stateless.
