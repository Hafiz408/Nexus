from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.ingestion.embedder import delete_embeddings_for_repo
from app.ingestion.graph_store import delete_graph_for_repo
from app.ingestion.pipeline import clear_status, get_status, run_ingestion
from app.models.schemas import IndexRequest, IndexStatus

router = APIRouter()


@router.post("/index", response_model=dict)
async def start_index(request: IndexRequest, background_tasks: BackgroundTasks):
    """Start ingestion as a background task; return immediately."""
    background_tasks.add_task(
        run_ingestion,
        request.repo_path,
        request.languages,
        request.changed_files,
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
async def delete_index(repo_path: str):
    """Remove all pgvector, FTS5, and SQLite graph data for the given repo_path."""
    delete_embeddings_for_repo(repo_path)
    delete_graph_for_repo(repo_path)
    clear_status(repo_path)
    return {"status": "deleted", "repo_path": repo_path}
