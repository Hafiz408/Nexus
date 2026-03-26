"""Runtime configuration store — replaces static .env singleton for dynamic provider config."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RuntimeConfig:
    chat_provider: str = "mistral"
    chat_model: str = "mistral-small-latest"
    embedding_provider: str = "mistral"
    embedding_model: str = "mistral-embed"
    api_keys: dict[str, str] = field(default_factory=dict)
    ollama_base_url: str = "http://localhost:11434"


def _init_config() -> RuntimeConfig:
    """Seed runtime defaults from .env Settings so startup config matches the env file."""
    from app.config import get_settings
    s = get_settings()
    cfg = RuntimeConfig(
        chat_provider=s.llm_provider,
        embedding_provider=s.embedding_provider,
    )
    # Pre-populate api_keys so the factory fallback works without a config push
    if s.llm_provider_api_key:
        cfg.api_keys[s.llm_provider] = s.llm_provider_api_key
    if s.embedding_provider_api_key and s.embedding_provider != s.llm_provider:
        cfg.api_keys[s.embedding_provider] = s.embedding_provider_api_key
    return cfg


_config = _init_config()


def get_runtime_config() -> RuntimeConfig:
    return _config


def update_runtime_config(data: dict) -> None:
    global _config
    if "chat_provider" in data:
        _config.chat_provider = data["chat_provider"]
    if "chat_model" in data:
        _config.chat_model = data["chat_model"]
    if "embedding_provider" in data:
        _config.embedding_provider = data["embedding_provider"]
    if "embedding_model" in data:
        _config.embedding_model = data["embedding_model"]
    if "api_keys" in data:
        _config.api_keys.update(data["api_keys"])
    if "ollama_base_url" in data:
        _config.ollama_base_url = data["ollama_base_url"]
