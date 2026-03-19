"""Query router — POST /query SSE streaming endpoint (Phase 10).

SSE event sequence (API-04):
  event: token   — one per LLM token, data: {"type": "token", "content": str}
  event: citations — one after last token, data: {"type": "citations", "citations": [...]}
  event: done    — final event, data: {"type": "done", "retrieval_stats": dict}
  event: error   — on exception inside generator, data: {"type": "error", "message": str}
"""
from __future__ import annotations

import asyncio
import json

import networkx as nx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.agent.explorer import explore_stream
from app.ingestion.graph_store import load_graph
from app.ingestion.pipeline import get_status
from app.models.schemas import QueryRequest
from app.retrieval.graph_rag import graph_rag_retrieve

router = APIRouter()


def _get_graph(repo_path: str, request: Request) -> nx.DiGraph:
    """Return cached nx.DiGraph for repo_path; load from SQLite on first access."""
    cache: dict = request.app.state.graph_cache
    if repo_path not in cache:
        cache[repo_path] = load_graph(repo_path)
    return cache[repo_path]


@router.post("/query")
async def query(request_body: QueryRequest, request: Request) -> StreamingResponse:
    """Stream grounded answer tokens + citations over SSE (API-03, API-04).

    Validates that repo_path has a complete index before starting the stream.
    HTTPException is raised BEFORE StreamingResponse is returned — this is the
    only safe place to return HTTP errors (headers are sent once stream starts).
    """
    status = get_status(request_body.repo_path)
    if status is None or status.status != "complete":
        raise HTTPException(
            status_code=400,
            detail=f"repo '{request_body.repo_path}' has not been indexed or indexing is not complete",
        )

    async def event_generator():
        try:
            # Load graph from cache (lazy, async-safe via to_thread)
            G = await asyncio.to_thread(_get_graph, request_body.repo_path, request)

            # Step 1: retrieval — synchronous blocking I/O; run in thread pool
            nodes, stats = await asyncio.to_thread(
                graph_rag_retrieve,
                request_body.question,
                request_body.repo_path,
                G,
                request_body.max_nodes,
                request_body.hop_depth,
            )

            # Step 2: stream tokens from LLM (async generator, no threading needed)
            async for token in explore_stream(nodes, request_body.question):
                payload = json.dumps({"type": "token", "content": token})
                yield f"event: token\ndata: {payload}\n\n"

            # Step 3: citations event — plain dicts only (CodeNode is not JSON serializable)
            citations = [
                {
                    "node_id": n.node_id,
                    "file_path": n.file_path,
                    "line_start": n.line_start,
                    "line_end": n.line_end,
                    "name": n.name,
                    "type": n.type,
                }
                for n in nodes
            ]
            yield f"event: citations\ndata: {json.dumps({'type': 'citations', 'citations': citations})}\n\n"

            # Step 4: done event with retrieval stats
            yield f"event: done\ndata: {json.dumps({'type': 'done', 'retrieval_stats': stats})}\n\n"

        except Exception as exc:  # noqa: BLE001
            payload = json.dumps({"type": "error", "message": str(exc)})
            yield f"event: error\ndata: {payload}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
