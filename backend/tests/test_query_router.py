"""Tests for POST /query SSE endpoint (API-03, API-04).

Uses FastAPI TestClient with stream=True to consume the SSE body.
All external I/O is monkeypatched:
  - app.api.query_router.get_status   → returns IndexStatus or None
  - app.api.query_router.load_graph   → returns nx.DiGraph()
  - app.api.query_router.graph_rag_retrieve → returns (nodes, stats)
  - app.api.query_router.explore_stream     → async generator of token strings
"""
import json
from unittest.mock import patch

import networkx as nx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.schemas import CodeNode, IndexStatus


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    """TestClient with lifespan enabled."""
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def sample_node():
    return CodeNode(
        node_id="src/foo.py::bar",
        name="bar",
        type="function",
        file_path="src/foo.py",
        line_start=10,
        line_end=20,
        signature="def bar():",
        docstring="Does bar.",
        body_preview="return 42",
    )


@pytest.fixture()
def sample_stats():
    return {"seed_nodes": 1, "expanded_nodes": 3, "returned_nodes": 1}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _complete_status():
    return IndexStatus(status="complete", nodes_indexed=5, edges_indexed=2)


def _make_async_gen(*tokens):
    """Return an async generator that yields the given token strings."""
    async def _gen(nodes, question, **kwargs):
        for t in tokens:
            yield t
    return _gen


def _read_stream(client, json_body):
    """POST /query with stream=True; read body inside context manager and return it."""
    with client.stream("POST", "/query", json=json_body) as r:
        r.read()
        body = r.text
    return body


# ---------------------------------------------------------------------------
# 400 guard tests (unindexed / in-progress repo)
# ---------------------------------------------------------------------------

_BASE_BODY = {"question": "What is bar?", "repo_path": "/repo", "db_path": "/repo/.nexus/graph.db"}


def test_unindexed_repo_returns_400(client, monkeypatch):
    """POST /query with unindexed repo returns 400 without streaming."""
    monkeypatch.setattr("app.api.query_router.get_status", lambda repo_path: None)
    response = client.post("/query", json=_BASE_BODY)
    assert response.status_code == 400


def test_indexing_in_progress_returns_400(client, monkeypatch):
    """POST /query while indexing is still running returns 400."""
    monkeypatch.setattr(
        "app.api.query_router.get_status",
        lambda repo_path: IndexStatus(status="running"),
    )
    response = client.post("/query", json=_BASE_BODY)
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Happy path tests — complete index
# ---------------------------------------------------------------------------

def test_happy_path_yields_token_events(client, monkeypatch, sample_node, sample_stats):
    """Stream from a complete repo yields one event: token line per LLM token."""
    monkeypatch.setattr("app.api.query_router.get_status", lambda repo_path: _complete_status())
    monkeypatch.setattr("app.api.query_router.load_graph", lambda repo_path, db_path: nx.DiGraph())
    monkeypatch.setattr(
        "app.api.query_router.graph_rag_retrieve",
        lambda question, repo_path, G, db_path, max_nodes, hop_depth: ([sample_node], sample_stats),
    )
    monkeypatch.setattr(
        "app.api.query_router.explore_stream",
        _make_async_gen("Hello", " world"),
    )
    body = _read_stream(client, _BASE_BODY)
    assert "event: token" in body
    token_events = [line for line in body.splitlines() if line.startswith("event: token")]
    assert len(token_events) == 2


def test_happy_path_yields_citations_event(client, monkeypatch, sample_node, sample_stats):
    """Stream yields event: citations; first citation has correct node_id."""
    monkeypatch.setattr("app.api.query_router.get_status", lambda repo_path: _complete_status())
    monkeypatch.setattr("app.api.query_router.load_graph", lambda repo_path, db_path: nx.DiGraph())
    monkeypatch.setattr(
        "app.api.query_router.graph_rag_retrieve",
        lambda question, repo_path, G, db_path, max_nodes, hop_depth: ([sample_node], sample_stats),
    )
    monkeypatch.setattr(
        "app.api.query_router.explore_stream",
        _make_async_gen("Hello"),
    )
    body = _read_stream(client, _BASE_BODY)

    assert "event: citations" in body

    # Extract citations data line
    lines = body.splitlines()
    citations_data = None
    for i, line in enumerate(lines):
        if line == "event: citations" and i + 1 < len(lines):
            data_line = lines[i + 1]
            assert data_line.startswith("data: ")
            citations_data = json.loads(data_line[len("data: "):])
            break

    assert citations_data is not None
    assert citations_data["citations"][0]["node_id"] == "src/foo.py::bar"


def test_happy_path_yields_done_event(client, monkeypatch, sample_node, sample_stats):
    """Stream yields event: done with retrieval_stats key in data."""
    monkeypatch.setattr("app.api.query_router.get_status", lambda repo_path: _complete_status())
    monkeypatch.setattr("app.api.query_router.load_graph", lambda repo_path, db_path: nx.DiGraph())
    monkeypatch.setattr(
        "app.api.query_router.graph_rag_retrieve",
        lambda question, repo_path, G, db_path, max_nodes, hop_depth: ([sample_node], sample_stats),
    )
    monkeypatch.setattr(
        "app.api.query_router.explore_stream",
        _make_async_gen("Hello"),
    )
    body = _read_stream(client, _BASE_BODY)

    assert "event: done" in body

    lines = body.splitlines()
    done_data = None
    for i, line in enumerate(lines):
        if line == "event: done" and i + 1 < len(lines):
            data_line = lines[i + 1]
            assert data_line.startswith("data: ")
            done_data = json.loads(data_line[len("data: "):])
            break

    assert done_data is not None
    assert "retrieval_stats" in done_data


def test_event_order(client, monkeypatch, sample_node, sample_stats):
    """Events arrive in order: token, token, citations, done."""
    monkeypatch.setattr("app.api.query_router.get_status", lambda repo_path: _complete_status())
    monkeypatch.setattr("app.api.query_router.load_graph", lambda repo_path, db_path: nx.DiGraph())
    monkeypatch.setattr(
        "app.api.query_router.graph_rag_retrieve",
        lambda question, repo_path, G, db_path, max_nodes, hop_depth: ([sample_node], sample_stats),
    )
    monkeypatch.setattr(
        "app.api.query_router.explore_stream",
        _make_async_gen("Hello", " world"),
    )
    body = _read_stream(client, _BASE_BODY)

    event_lines = [line for line in body.splitlines() if line.startswith("event:")]
    assert event_lines == ["event: token", "event: token", "event: citations", "event: done"]


# ---------------------------------------------------------------------------
# Error event test
# ---------------------------------------------------------------------------

def test_error_event_on_retrieval_failure(client, monkeypatch):
    """When graph_rag_retrieve raises, the stream yields event: error with message."""
    monkeypatch.setattr("app.api.query_router.get_status", lambda repo_path: _complete_status())
    monkeypatch.setattr("app.api.query_router.load_graph", lambda repo_path, db_path: nx.DiGraph())

    def _bad_retrieve(question, repo_path, G, db_path, max_nodes, hop_depth):
        raise RuntimeError("db error")

    monkeypatch.setattr("app.api.query_router.graph_rag_retrieve", _bad_retrieve)
    monkeypatch.setattr("app.api.query_router.explore_stream", _make_async_gen())

    body = _read_stream(client, _BASE_BODY)

    assert "event: error" in body

    lines = body.splitlines()
    error_data = None
    for i, line in enumerate(lines):
        if line == "event: error" and i + 1 < len(lines):
            data_line = lines[i + 1]
            assert data_line.startswith("data: ")
            error_data = json.loads(data_line[len("data: "):])
            break

    assert error_data is not None
    assert "db error" in error_data["message"]


# ---------------------------------------------------------------------------
# Citation fields test
# ---------------------------------------------------------------------------

def test_citations_contain_required_fields(client, monkeypatch, sample_node, sample_stats):
    """Citations event data includes required fields for each citation."""
    monkeypatch.setattr("app.api.query_router.get_status", lambda repo_path: _complete_status())
    monkeypatch.setattr("app.api.query_router.load_graph", lambda repo_path, db_path: nx.DiGraph())
    monkeypatch.setattr(
        "app.api.query_router.graph_rag_retrieve",
        lambda question, repo_path, G, db_path, max_nodes, hop_depth: ([sample_node], sample_stats),
    )
    monkeypatch.setattr(
        "app.api.query_router.explore_stream",
        _make_async_gen("Hi"),
    )
    body = _read_stream(client, _BASE_BODY)

    lines = body.splitlines()
    citations_data = None
    for i, line in enumerate(lines):
        if line == "event: citations" and i + 1 < len(lines):
            data_line = lines[i + 1]
            citations_data = json.loads(data_line[len("data: "):])
            break

    assert citations_data is not None
    required_fields = {"node_id", "file_path", "line_start", "line_end", "name", "type"}
    for citation in citations_data["citations"]:
        assert required_fields.issubset(citation.keys()), f"Missing fields: {required_fields - citation.keys()}"


# ---------------------------------------------------------------------------
# Content-Type test
# ---------------------------------------------------------------------------

def test_content_type_is_text_event_stream(client, monkeypatch, sample_node, sample_stats):
    """Response Content-Type must start with text/event-stream."""
    monkeypatch.setattr("app.api.query_router.get_status", lambda repo_path: _complete_status())
    monkeypatch.setattr("app.api.query_router.load_graph", lambda repo_path, db_path: nx.DiGraph())
    monkeypatch.setattr(
        "app.api.query_router.graph_rag_retrieve",
        lambda question, repo_path, G, db_path, max_nodes, hop_depth: ([sample_node], sample_stats),
    )
    monkeypatch.setattr(
        "app.api.query_router.explore_stream",
        _make_async_gen("Hi"),
    )
    with client.stream("POST", "/query", json=_BASE_BODY) as r:
        content_type = r.headers.get("content-type", "")
        r.read()

    assert content_type.startswith("text/event-stream")
