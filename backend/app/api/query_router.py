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
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

from app.agent.explorer import explore_stream
from app.ingestion.graph_store import load_graph
from app.ingestion.pipeline import get_status, restore_status
from app.models.schemas import QueryRequest

router = APIRouter()


def _get_graph(repo_path: str, db_path: str, request: Request) -> nx.DiGraph:
    """Return cached nx.DiGraph for repo_path; load from SQLite on first access."""
    cache: dict = request.app.state.graph_cache
    if repo_path not in cache:
        cache[repo_path] = load_graph(repo_path, db_path)
    return cache[repo_path]


@router.post("/query")
async def query(request_body: QueryRequest, request: Request) -> StreamingResponse:
    """Stream grounded answer tokens + citations over SSE (API-03, API-04).

    Validates that repo_path has a complete index before starting the stream.
    HTTPException is raised BEFORE StreamingResponse is returned — this is the
    only safe place to return HTTP errors (headers are sent once stream starts).
    """
    status = get_status(request_body.repo_path)
    if status is None:
        # In-memory status lost after restart — check SQLite to restore
        from app.ingestion.meta_store import get_embedding_meta  # noqa: PLC0415
        if get_embedding_meta(request_body.db_path) is not None:
            restore_status(request_body.repo_path)
            status = get_status(request_body.repo_path)

    logger.info(
        "POST /query repo=%r intent=%r status=%r target=%r file=%r",
        request_body.repo_path,
        request_body.intent_hint,
        status.status if status else None,
        request_body.target_node_id,
        request_body.selected_file,
    )
    if status is None or status.status != "complete":
        raise HTTPException(
            status_code=400,
            detail=f"repo '{request_body.repo_path}' has not been indexed or indexing is not complete",
        )

    # V2 path: structured agents (debug / review / test) use LangGraph
    if request_body.intent_hint and request_body.intent_hint not in ("auto", "explain"):
        async def v2_event_generator():
            _conn = None
            try:
                # Lazy imports — established project pattern (all V2 agents use this)
                # Prevents import-time ValidationError when API keys are absent.
                from app.agent.orchestrator import build_graph  # noqa: PLC0415
                import sqlite3 as _sqlite3  # noqa: PLC0415
                from langgraph.checkpoint.sqlite import SqliteSaver  # noqa: PLC0415

                G = await asyncio.to_thread(_get_graph, request_body.repo_path, request_body.db_path, request)
                # Store G in process-level cache — keeps DiGraph out of LangGraph state
                # so SqliteSaver never tries to msgpack-serialize it.
                from app.agent.orchestrator import set_graph as _set_graph  # noqa: PLC0415
                _set_graph(request_body.repo_path, G)

                # SqliteSaver DB is SEPARATE from graph.db (locked decision, STATE.md)
                import os as _os  # noqa: PLC0415
                _nexus_dir = _os.path.dirname(request_body.db_path)
                _os.makedirs(_nexus_dir, exist_ok=True)
                checkpoints_path = _os.path.join(_nexus_dir, "checkpoints.db")
                _conn = _sqlite3.connect(checkpoints_path, check_same_thread=False)
                graph = build_graph(checkpointer=SqliteSaver(_conn))

                initial_state = {
                    "question": request_body.question,
                    "repo_path": request_body.repo_path,
                    "db_path": request_body.db_path,
                    "intent_hint": request_body.intent_hint,
                    "max_nodes": request_body.max_nodes,
                    "hop_depth": request_body.hop_depth,
                    "target_node_id": request_body.target_node_id,
                    "selected_file": request_body.selected_file,
                    "selected_range": request_body.selected_range,
                    "repo_root": request_body.repo_root,
                    "intent": None,
                    "specialist_result": None,
                    "critic_result": None,
                    "loop_count": 0,
                }
                # Thread ID scoped per request for isolation (no cross-request state bleed)
                from uuid import uuid4  # noqa: PLC0415
                thread_id = f"{request_body.repo_path}::{uuid4()}"

                # graph.invoke() is synchronous — offload to thread pool to avoid
                # blocking the FastAPI event loop (established pattern, STATE.md Phase 22)
                logger.info("v2 invoke start: intent=%r thread=%r", request_body.intent_hint, thread_id)
                result_state = await asyncio.to_thread(
                    graph.invoke,
                    initial_state,
                    {"configurable": {"thread_id": thread_id}},
                )

                specialist = result_state["specialist_result"]
                intent = result_state["intent"]
                logger.info("v2 invoke done: resolved_intent=%r", intent)

                # Pydantic v2: model_dump(mode="json") recursively serializes nested models
                # e.g. _ExplainResult.nodes contains CodeNode objects — mode="json" is required
                if hasattr(specialist, "model_dump"):
                    result_dict = specialist.model_dump(mode="json")
                else:
                    result_dict = {"answer": str(specialist)}

                # EXT-07: surface github_token presence so extension can show/hide
                # "Post to GitHub PR" button — extension has no env var access.
                from app.config import get_settings as _get_settings  # noqa: PLC0415
                _settings = _get_settings()
                has_github_token = bool(_settings.github_token)

                # EXT-09: attempt MCP file write for test intent; carry result in payload
                # so extension can show file-written badge vs copy-to-clipboard fallback.
                file_written = False
                written_path: str | None = None
                if intent == "test":
                    try:
                        from app.mcp.tools import write_test_file as _write_test_file  # noqa: PLC0415
                        _mcp_result = _write_test_file(
                            result_dict.get("test_code", ""),
                            result_dict.get("test_file_path", "tests/test_output.py"),
                            base_dir=str(request_body.repo_root or "."),
                        )
                        file_written = bool(_mcp_result.get("success", False))
                        written_path = _mcp_result.get("path")
                    except Exception as _mcp_exc:  # noqa: BLE001
                        import logging as _logging  # noqa: PLC0415
                        _logging.getLogger(__name__).warning(
                            "write_test_file raised; file_written=False: %s", _mcp_exc
                        )

                payload = json.dumps({
                    "type": "result",
                    "intent": intent,
                    "result": result_dict,
                    "has_github_token": has_github_token,
                    "file_written": file_written,
                    "written_path": written_path,
                })
                yield f"event: result\ndata: {payload}\n\n"
                yield f"event: done\ndata: {json.dumps({'type': 'done'})}\n\n"

            except Exception as exc:  # noqa: BLE001
                logger.exception("v2 error: %s", exc)
                payload = json.dumps({"type": "error", "message": str(exc)})
                yield f"event: error\ndata: {payload}\n\n"
            finally:
                if _conn is not None:
                    _conn.close()

        return StreamingResponse(v2_event_generator(), media_type="text/event-stream")

    # Explain path: selection-aware retrieval + streaming tokens
    async def event_generator():
        try:
            from app.agent.orchestrator import set_graph as _set_graph, build_explain_context  # noqa: PLC0415

            G = await asyncio.to_thread(_get_graph, request_body.repo_path, request_body.db_path, request)
            _set_graph(request_body.repo_path, G)

            nodes, stats, anchored_question = await asyncio.to_thread(
                build_explain_context,
                request_body.question,
                request_body.repo_path,
                request_body.db_path,
                request_body.selected_file,
                request_body.selected_range,
                request_body.max_nodes,
                request_body.hop_depth,
            )

            async for token in explore_stream(nodes, anchored_question):
                payload = json.dumps({"type": "token", "content": token})
                yield f"event: token\ndata: {payload}\n\n"

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
            yield f"event: done\ndata: {json.dumps({'type': 'done', 'retrieval_stats': stats})}\n\n"

        except Exception as exc:  # noqa: BLE001
            payload = json.dumps({"type": "error", "message": str(exc)})
            yield f"event: error\ndata: {payload}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


from pydantic import BaseModel as _BaseModel


class _PostPRRequest(_BaseModel):
    findings: list                 # list of finding dicts
    repo: str                      # "owner/repo"
    pr_number: int
    commit_sha: str


@router.post("/review/post-pr")
async def post_review_to_pr(request_body: _PostPRRequest):
    """Post reviewer findings as GitHub PR inline comments (MCP-01).

    Uses server-side GITHUB_TOKEN from settings — token is never exposed
    to the extension. Extension sends findings + PR context; this endpoint
    calls post_review_comments() from the MCP tool layer.
    """
    from app.config import get_settings as _get_settings  # noqa: PLC0415
    from app.mcp.tools import post_review_comments  # noqa: PLC0415

    settings = _get_settings()
    if not settings.github_token:
        raise HTTPException(
            status_code=400,
            detail="GITHUB_TOKEN not configured on server",
        )

    try:
        result = post_review_comments(
            findings=request_body.findings,
            repo=request_body.repo,
            pr_number=request_body.pr_number,
            commit_sha=request_body.commit_sha,
            github_token=settings.github_token,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to post PR comments: {exc}") from exc
    return result
