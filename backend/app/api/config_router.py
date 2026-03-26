from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
from app.core.runtime_config import update_runtime_config, get_runtime_config

router = APIRouter()


class ConfigRequest(BaseModel):
    chat_provider: Optional[str] = None
    chat_model: Optional[str] = None
    embedding_provider: Optional[str] = None
    embedding_model: Optional[str] = None
    api_keys: Optional[dict[str, str]] = None
    ollama_base_url: Optional[str] = None


@router.post("/config")
def set_config(request: ConfigRequest):
    update_runtime_config(request.model_dump(exclude_none=True))
    return {"status": "ok"}


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
    return {"status": "ok"}
