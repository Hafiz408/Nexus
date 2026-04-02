import asyncio

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from app.ingestion.embedder import delete_embeddings_for_repo
from app.ingestion.graph_store import delete_graph_for_repo
from app.ingestion.pipeline import clear_status, get_status, run_ingestion
from app.models.schemas import IndexRequest, IndexStatus

router = APIRouter()


async def _run_ingestion_and_invalidate_cache(
    repo_path: str,
    languages: list,
    db_path: str,
    changed_files: list | None,
    graph_cache: dict,
) -> None:
    """Run ingestion then evict the stale in-memory graph so the next query
    reloads from SQLite with the updated nodes."""
    await run_ingestion(repo_path, languages, db_path, changed_files)
    graph_cache.pop(repo_path, None)


@router.post("/index", response_model=dict)
async def start_index(request: IndexRequest, background_tasks: BackgroundTasks, http_request: Request):
    """Start ingestion as a background task; return immediately."""
    background_tasks.add_task(
        _run_ingestion_and_invalidate_cache,
        request.repo_path,
        request.languages,
        request.db_path,
        request.changed_files,
        http_request.app.state.graph_cache,
    )
    return {"status": "pending", "repo_path": request.repo_path}


@router.get("/index/status", response_model=IndexStatus)
async def index_status(repo_path: str):
    """Return live IndexStatus for the given repo_path."""
    status = get_status(repo_path)
    if status is None:
        raise HTTPException(status_code=404, detail="No index found for repo_path")
    return status


@router.delete("/index", response_model=dict)
async def delete_index(repo_path: str, db_path: str):
    """Remove all FTS5 and SQLite graph data for the given repo_path."""
    if not db_path or not db_path.strip():
        raise HTTPException(status_code=422, detail="db_path must be a non-empty path")
    try:
        await asyncio.to_thread(delete_embeddings_for_repo, repo_path, db_path)
        await asyncio.to_thread(delete_graph_for_repo, repo_path, db_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to delete index: {exc}") from exc
    clear_status(repo_path)
    return {"status": "deleted", "repo_path": repo_path}
