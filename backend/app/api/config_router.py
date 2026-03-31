from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
from app.core.runtime_config import update_runtime_config, get_runtime_config
from app.ingestion.meta_store import get_embedding_meta

router = APIRouter()

NEXUS_VERSION = "4.0.6"


class ConfigRequest(BaseModel):
    chat_provider: Optional[str] = None
    chat_model: Optional[str] = None
    embedding_provider: Optional[str] = None
    embedding_model: Optional[str] = None
    api_keys: Optional[dict[str, str]] = None
    ollama_base_url: Optional[str] = None
    db_path: Optional[str] = None  # if provided, check embedding mismatch


@router.post("/config")
def set_config(request: ConfigRequest):
    data = request.model_dump(exclude_none=True)
    db_path = data.pop("db_path", None)
    update_runtime_config(data)

    reindex_required = False
    if db_path:
        stored = get_embedding_meta(db_path)
        if stored is not None:
            cfg = get_runtime_config()
            reindex_required = (
                stored["provider"] != cfg.embedding_provider or
                stored["model"] != cfg.embedding_model
            )

    return {"status": "ok", "reindex_required": reindex_required}


@router.get("/config/status")
def get_config_status():
    cfg = get_runtime_config()
    return {
        "chat_provider": cfg.chat_provider,
        "chat_model": cfg.chat_model,
        "embedding_provider": cfg.embedding_provider,
        "embedding_model": cfg.embedding_model,
        "ollama_base_url": cfg.ollama_base_url,
    }


@router.get("/health")
def health():
    return {"status": "ok", "version": NEXUS_VERSION}
