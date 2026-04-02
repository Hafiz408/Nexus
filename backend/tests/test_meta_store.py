"""Tests for meta_store.py and embedding mismatch detection via POST /api/config.

Covers:
- EMBD-01: nexus_meta table round-trip (set/get embedding meta)
- EMBD-02: POST /api/config returns reindex_required on mismatch
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.ingestion.meta_store import (
    get_embedding_meta,
    get_meta,
    set_embedding_meta,
    set_meta,
)
from app.core.runtime_config import RuntimeConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    from app.main import app
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
# meta_store unit tests
# ---------------------------------------------------------------------------

def test_get_meta_returns_none_when_db_missing(tmp_path):
    """get_meta returns None when the db file does not exist."""
    db = str(tmp_path / "nonexistent.db")
    assert get_meta(db, "embedding_provider") is None


def test_get_embedding_meta_returns_none_when_db_missing(tmp_path):
    """get_embedding_meta returns None when no db file exists."""
    db = str(tmp_path / "nonexistent.db")
    assert get_embedding_meta(db) is None


def test_set_and_get_meta_round_trip(tmp_path):
    """set_meta + get_meta round-trip stores and retrieves the value."""
    db = str(tmp_path / "graph.db")
    set_meta(db, "some_key", "some_value")
    assert get_meta(db, "some_key") == "some_value"


def test_set_meta_overwrites_existing(tmp_path):
    """set_meta with INSERT OR REPLACE overwrites an existing key."""
    db = str(tmp_path / "graph.db")
    set_meta(db, "embedding_provider", "mistral")
    set_meta(db, "embedding_provider", "openai")
    assert get_meta(db, "embedding_provider") == "openai"


def test_set_embedding_meta_round_trip(tmp_path):
    """set_embedding_meta + get_embedding_meta round-trip stores all three fields."""
    db = str(tmp_path / "graph.db")
    set_embedding_meta(db, "openai", "text-embedding-3-small", 1536)
    meta = get_embedding_meta(db)
    assert meta is not None
    assert meta["provider"] == "openai"
    assert meta["model"] == "text-embedding-3-small"
    assert meta["dimensions"] == "1536"


def test_get_embedding_meta_returns_none_before_any_write(tmp_path):
    """get_embedding_meta returns None when db exists but no meta written."""
    db = str(tmp_path / "graph.db")
    # Create the db file with the table but no rows
    set_meta(db, "some_other_key", "some_value")
    assert get_embedding_meta(db) is None


def test_set_embedding_meta_overwrites(tmp_path):
    """set_embedding_meta can be called multiple times; latest values win."""
    db = str(tmp_path / "graph.db")
    set_embedding_meta(db, "mistral", "mistral-embed", 1024)
    set_embedding_meta(db, "openai", "text-embedding-3-large", 3072)
    meta = get_embedding_meta(db)
    assert meta["provider"] == "openai"
    assert meta["model"] == "text-embedding-3-large"
    assert meta["dimensions"] == "3072"


# ---------------------------------------------------------------------------
# POST /api/config — reindex_required flag
# ---------------------------------------------------------------------------

def test_post_config_no_db_path_no_reindex_required(client):
    """POST /api/config without db_path always returns reindex_required: false."""
    resp = client.post("/api/config", json={"embedding_provider": "openai", "embedding_model": "text-embedding-3-small"})
    assert resp.status_code == 200
    assert resp.json()["reindex_required"] is False


def test_post_config_with_db_path_no_stored_meta_no_reindex(client, tmp_path):
    """If db_path provided but no meta stored yet, reindex_required is false."""
    db = str(tmp_path / "graph.db")
    resp = client.post("/api/config", json={
        "embedding_provider": "openai",
        "embedding_model": "text-embedding-3-small",
        "db_path": db,
    })
    assert resp.status_code == 200
    assert resp.json()["reindex_required"] is False


def test_post_config_matching_embedding_no_reindex(client, tmp_path):
    """When incoming config matches stored meta, reindex_required is false."""
    db = str(tmp_path / "graph.db")
    set_embedding_meta(db, "mistral", "mistral-embed", 1024)

    # Post the same provider+model that is stored
    resp = client.post("/api/config", json={
        "embedding_provider": "mistral",
        "embedding_model": "mistral-embed",
        "db_path": db,
    })
    assert resp.status_code == 200
    assert resp.json()["reindex_required"] is False


def test_post_config_different_provider_triggers_reindex(client, tmp_path):
    """When embedding_provider changes relative to stored meta, reindex_required is true."""
    db = str(tmp_path / "graph.db")
    set_embedding_meta(db, "mistral", "mistral-embed", 1024)

    resp = client.post("/api/config", json={
        "embedding_provider": "openai",
        "embedding_model": "mistral-embed",
        "db_path": db,
    })
    assert resp.status_code == 200
    assert resp.json()["reindex_required"] is True


def test_post_config_different_model_triggers_reindex(client, tmp_path):
    """When embedding_model changes relative to stored meta, reindex_required is true."""
    db = str(tmp_path / "graph.db")
    set_embedding_meta(db, "openai", "text-embedding-3-small", 1536)

    resp = client.post("/api/config", json={
        "embedding_provider": "openai",
        "embedding_model": "text-embedding-3-large",
        "db_path": db,
    })
    assert resp.status_code == 200
    assert resp.json()["reindex_required"] is True


def test_post_config_both_provider_and_model_changed_triggers_reindex(client, tmp_path):
    """When both provider and model change, reindex_required is true."""
    db = str(tmp_path / "graph.db")
    set_embedding_meta(db, "mistral", "mistral-embed", 1024)

    resp = client.post("/api/config", json={
        "embedding_provider": "openai",
        "embedding_model": "text-embedding-3-large",
        "db_path": db,
    })
    assert resp.status_code == 200
    assert resp.json()["reindex_required"] is True


# ---------------------------------------------------------------------------
# pipeline integration — set_embedding_meta called after run_ingestion
# ---------------------------------------------------------------------------

def test_run_ingestion_writes_embedding_meta(tmp_path):
    """After run_ingestion completes, get_embedding_meta returns the active config."""
    import networkx as nx
    from app.ingestion.pipeline import run_ingestion
    from app.core.runtime_config import update_runtime_config

    db = str(tmp_path / "graph.db")
    update_runtime_config({
        "embedding_provider": "openai",
        "embedding_model": "text-embedding-3-small",
    })

    G = nx.DiGraph()
    G.add_node("a.py::func_0")

    mock_embedder = MagicMock()
    mock_embedder.dimensions = 1536

    with patch("app.ingestion.pipeline.walk_repo", return_value=[
        {"path": str(tmp_path / "a.py"), "language": "python", "size_kb": 1}
    ]):
        with patch("app.ingestion.pipeline.parse_file", return_value=([], [])):
            with patch("app.ingestion.pipeline.build_graph", return_value=G):
                with patch("app.ingestion.pipeline.save_graph"):
                    with patch("app.ingestion.pipeline.delete_embeddings_for_repo"):
                        with patch("app.ingestion.pipeline.embed_and_store", return_value=1):
                            with patch("app.ingestion.pipeline.get_embedding_client", return_value=mock_embedder):
                                with patch("app.ingestion.pipeline.init_vec_table"):
                                    asyncio.run(run_ingestion(str(tmp_path), ["python"], db))

    meta = get_embedding_meta(db)
    assert meta is not None
    assert meta["provider"] == "openai"
    assert meta["model"] == "text-embedding-3-small"
    assert meta["dimensions"] == "1536"
