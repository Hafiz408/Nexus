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


_config = RuntimeConfig()


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
