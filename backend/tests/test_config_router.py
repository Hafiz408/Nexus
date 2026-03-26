"""Tests for POST /api/config, GET /api/health, GET /api/config/status,
and model_factory provider instantiation (all external SDK calls mocked).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.runtime_config import get_runtime_config, update_runtime_config, RuntimeConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def reset_runtime_config():
    """Reset runtime config to defaults before each test."""
    import app.core.runtime_config as rc
    original = rc._config
    rc._config = RuntimeConfig()
    yield
    rc._config = original


# ---------------------------------------------------------------------------
# POST /api/config
# ---------------------------------------------------------------------------

def test_post_config_returns_ok(client):
    resp = client.post("/api/config", json={"chat_provider": "openai", "chat_model": "gpt-4o"})
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_post_config_updates_chat_provider(client):
    client.post("/api/config", json={"chat_provider": "anthropic", "chat_model": "claude-3-5-sonnet-latest"})
    cfg = get_runtime_config()
    assert cfg.chat_provider == "anthropic"
    assert cfg.chat_model == "claude-3-5-sonnet-latest"


def test_post_config_updates_embedding_provider(client):
    client.post("/api/config", json={"embedding_provider": "openai", "embedding_model": "text-embedding-3-small"})
    cfg = get_runtime_config()
    assert cfg.embedding_provider == "openai"
    assert cfg.embedding_model == "text-embedding-3-small"


def test_post_config_updates_api_keys(client):
    client.post("/api/config", json={"api_keys": {"openai": "sk-test123"}})
    cfg = get_runtime_config()
    assert cfg.api_keys["openai"] == "sk-test123"


def test_post_config_updates_ollama_base_url(client):
    client.post("/api/config", json={"ollama_base_url": "http://myhost:11434"})
    cfg = get_runtime_config()
    assert cfg.ollama_base_url == "http://myhost:11434"


def test_post_config_partial_update_preserves_other_fields(client):
    client.post("/api/config", json={"chat_provider": "gemini"})
    cfg = get_runtime_config()
    # embedding_provider should remain at default
    assert cfg.embedding_provider == "mistral"


def test_post_config_null_fields_ignored(client):
    """Fields not in the JSON body should not overwrite existing config."""
    client.post("/api/config", json={"chat_provider": "openai"})
    client.post("/api/config", json={"chat_model": "gpt-4o-mini"})
    cfg = get_runtime_config()
    assert cfg.chat_provider == "openai"
    assert cfg.chat_model == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# GET /api/health
# ---------------------------------------------------------------------------

def test_health_returns_200(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200


def test_health_returns_ok_json(client):
    resp = client.get("/api/health")
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# GET /api/config/status
# ---------------------------------------------------------------------------

def test_config_status_returns_defaults(client):
    resp = client.get("/api/config/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["chat_provider"] == "mistral"
    assert data["chat_model"] == "mistral-small-latest"
    assert data["embedding_provider"] == "mistral"
    assert data["embedding_model"] == "mistral-embed"


def test_config_status_reflects_updates(client):
    client.post("/api/config", json={"chat_provider": "ollama", "chat_model": "llama3"})
    resp = client.get("/api/config/status")
    data = resp.json()
    assert data["chat_provider"] == "ollama"
    assert data["chat_model"] == "llama3"


def test_config_status_has_required_keys(client):
    resp = client.get("/api/config/status")
    required = {"chat_provider", "chat_model", "embedding_provider", "embedding_model", "ollama_base_url"}
    assert required.issubset(resp.json().keys())


# ---------------------------------------------------------------------------
# get_llm() uses runtime config
# ---------------------------------------------------------------------------

def test_get_llm_uses_runtime_chat_provider():
    """get_llm() reads chat_provider from runtime config, not .env."""
    update_runtime_config({"chat_provider": "openai", "chat_model": "gpt-4o", "api_keys": {"openai": "sk-test"}})
    with patch("langchain_openai.ChatOpenAI") as mock_cls:
        mock_cls.return_value = MagicMock()
        from app.core.model_factory import get_llm
        get_llm()
        mock_cls.assert_called_once()
        call_kwargs = mock_cls.call_args.kwargs
        assert call_kwargs["model"] == "gpt-4o"


def test_get_llm_mistral_provider():
    update_runtime_config({"chat_provider": "mistral", "chat_model": "mistral-small-latest", "api_keys": {"mistral": "m-key"}})
    with patch("langchain_mistralai.ChatMistralAI") as mock_cls:
        mock_cls.return_value = MagicMock()
        from app.core.model_factory import get_llm
        get_llm()
        mock_cls.assert_called_once()


# ---------------------------------------------------------------------------
# get_embedding_client() uses runtime config
# ---------------------------------------------------------------------------

def test_get_embedding_client_uses_runtime_provider():
    update_runtime_config({"embedding_provider": "openai", "api_keys": {"openai": "sk-test"}})
    with patch("openai.OpenAI") as mock_cls:
        mock_cls.return_value = MagicMock()
        from app.core.model_factory import get_embedding_client
        client_obj = get_embedding_client()
        assert client_obj is not None


def test_get_embedding_client_mistral_default():
    """Default embedding provider is mistral."""
    with patch("app.core.model_factory.MistralEmbeddingClient") as mock_cls:
        instance = MagicMock()
        instance.dimensions = 1024
        mock_cls.return_value = instance
        from app.core.model_factory import get_embedding_client
        ec = get_embedding_client()
        assert ec.dimensions == 1024


# ---------------------------------------------------------------------------
# All 5 chat providers instantiate without error (SDK clients mocked)
# ---------------------------------------------------------------------------

def test_llm_provider_openai():
    update_runtime_config({"chat_provider": "openai", "chat_model": "gpt-4o", "api_keys": {"openai": "sk-test"}})
    with patch("langchain_openai.ChatOpenAI", return_value=MagicMock()):
        from app.core import model_factory
        llm = model_factory.get_llm()
        assert llm is not None


def test_llm_provider_mistral():
    update_runtime_config({"chat_provider": "mistral", "chat_model": "mistral-small-latest", "api_keys": {"mistral": "m-key"}})
    with patch("langchain_mistralai.ChatMistralAI", return_value=MagicMock()):
        from app.core import model_factory
        llm = model_factory.get_llm()
        assert llm is not None


def test_llm_provider_anthropic():
    update_runtime_config({"chat_provider": "anthropic", "chat_model": "claude-3-5-sonnet-latest", "api_keys": {"anthropic": "sk-ant-test"}})
    mock_anthropic = MagicMock()
    with patch.dict("sys.modules", {"langchain_anthropic": MagicMock(ChatAnthropic=lambda **kw: mock_anthropic)}):
        from app.core import model_factory
        llm = model_factory.get_llm()
        assert llm is not None


def test_llm_provider_ollama():
    update_runtime_config({"chat_provider": "ollama", "chat_model": "llama3"})
    mock_ollama = MagicMock()
    with patch.dict("sys.modules", {"langchain_ollama": MagicMock(ChatOllama=lambda **kw: mock_ollama)}):
        from app.core import model_factory
        llm = model_factory.get_llm()
        assert llm is not None


def test_llm_provider_gemini():
    update_runtime_config({"chat_provider": "gemini", "chat_model": "gemini-1.5-pro", "api_keys": {"gemini": "g-key"}})
    mock_gemini = MagicMock()
    with patch.dict("sys.modules", {"langchain_google_genai": MagicMock(ChatGoogleGenerativeAI=lambda **kw: mock_gemini)}):
        from app.core import model_factory
        llm = model_factory.get_llm()
        assert llm is not None


def test_llm_unknown_provider_raises():
    update_runtime_config({"chat_provider": "unknown_provider"})
    from app.core import model_factory
    with pytest.raises(ValueError, match="Unknown chat_provider"):
        model_factory.get_llm()


# ---------------------------------------------------------------------------
# All 4 embedding providers instantiate without error (SDK clients mocked)
# ---------------------------------------------------------------------------

def test_embedding_provider_openai():
    update_runtime_config({"embedding_provider": "openai", "embedding_model": "text-embedding-3-small", "api_keys": {"openai": "sk-test"}})
    with patch("openai.OpenAI", return_value=MagicMock()):
        from app.core import model_factory
        ec = model_factory.get_embedding_client()
        assert ec is not None
        assert ec.dimensions == 1536


def test_embedding_provider_mistral():
    update_runtime_config({"embedding_provider": "mistral", "api_keys": {"mistral": "m-key"}})
    mock_instance = MagicMock()
    mock_instance.dimensions = 1024
    with patch("app.core.model_factory.MistralEmbeddingClient", return_value=mock_instance):
        from app.core import model_factory
        ec = model_factory.get_embedding_client()
        assert ec is not None
        assert ec.dimensions == 1024


def test_embedding_provider_ollama():
    update_runtime_config({"embedding_provider": "ollama", "embedding_model": "nomic-embed-text"})
    mock_ollama_emb = MagicMock()
    with patch.dict("sys.modules", {"langchain_ollama": MagicMock(OllamaEmbeddings=lambda **kw: mock_ollama_emb)}):
        from app.core import model_factory
        ec = model_factory.get_embedding_client()
        assert ec is not None
        assert ec.dimensions == 768


def test_embedding_provider_gemini():
    update_runtime_config({"embedding_provider": "gemini", "embedding_model": "models/text-embedding-004", "api_keys": {"gemini": "g-key"}})
    mock_gemini_emb = MagicMock()
    with patch.dict("sys.modules", {"langchain_google_genai": MagicMock(GoogleGenerativeAIEmbeddings=lambda **kw: mock_gemini_emb)}):
        from app.core import model_factory
        ec = model_factory.get_embedding_client()
        assert ec is not None
        assert ec.dimensions == 768


def test_embedding_unknown_provider_raises():
    update_runtime_config({"embedding_provider": "unknown_provider"})
    from app.core import model_factory
    with pytest.raises(ValueError, match="Unknown embedding_provider"):
        model_factory.get_embedding_client()
