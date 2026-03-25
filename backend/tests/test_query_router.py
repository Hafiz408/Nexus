"""Tests for POST /query SSE endpoint and POST /review/post-pr endpoint.

Covers:
  - 400 guards (unindexed / in-progress repo)
  - V1 path (intent_hint=None or "auto"): graph-RAG + token stream
  - V2 path (named intent): orchestrator routing for debug/review/test/explain
  - Sentinel fall-through: "auto" and None both use V1 path
  - /review/post-pr: GITHUB_TOKEN gate + post_review_comments() call

All external I/O is mocked — zero live LLM calls, zero live DB connections.

Patch strategy:
  - app.api.query_router.get_status         → monkeypatch.setattr
  - app.api.query_router.load_graph         → monkeypatch.setattr
  - app.api.query_router.graph_rag_retrieve → monkeypatch.setattr (V1 tests)
  - app.api.query_router.explore_stream     → monkeypatch.setattr (V1 tests)
  - app.agent.orchestrator.build_graph      → patch() at source namespace (V2 tests)
  - app.config.get_settings                 → patch() (V2 + /review/post-pr tests)
  - app.mcp.tools.post_review_comments      → patch() (/review/post-pr tests)
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import networkx as nx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.schemas import CodeNode, IndexStatus
from app.agent.debugger import DebugResult, SuspectNode


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
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


@pytest.fixture()
def nexus_dir(tmp_path):
    d = tmp_path / ".nexus"
    d.mkdir()
    return d


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_BODY = {"question": "What is bar?", "repo_path": "/repo", "db_path": "/repo/.nexus/graph.db"}


def _complete_status():
    return IndexStatus(status="complete", nodes_indexed=5, edges_indexed=2)


def _make_async_gen(*tokens):
    """Async generator yielding the given token strings (V1 path)."""
    async def _gen(nodes, question, **kwargs):
        for t in tokens:
            yield t
    return _gen


def _make_mock_graph(intent: str, specialist_result):
    """MagicMock graph whose invoke() returns a NexusState-shaped dict."""
    mock_graph = MagicMock()
    mock_graph.invoke.return_value = {
        "question": "test",
        "repo_path": "/repo",
        "intent_hint": intent,
        "G": None,
        "target_node_id": None,
        "selected_file": None,
        "selected_range": None,
        "repo_root": None,
        "intent": intent,
        "specialist_result": specialist_result,
        "critic_result": MagicMock(passed=True),
        "loop_count": 0,
    }
    return mock_graph


def _make_debug_result() -> DebugResult:
    return DebugResult(
        suspects=[
            SuspectNode(
                node_id="a.py::fn",
                file_path="/repo/a.py",
                line_start=1,
                anomaly_score=0.8,
                reasoning="r",
            )
        ],
        traversal_path=["a.py::fn"],
        impact_radius=[],
        diagnosis="fn is suspect.",
    )


def _read_stream(client, json_body):
    with client.stream("POST", "/query", json=json_body) as r:
        r.read()
        body = r.text
    return body


# ---------------------------------------------------------------------------
# 400 guard tests
# ---------------------------------------------------------------------------

def test_unindexed_repo_returns_400(client, monkeypatch):
    monkeypatch.setattr("app.api.query_router.get_status", lambda repo_path: None)
    response = client.post("/query", json=_BASE_BODY)
    assert response.status_code == 400


def test_indexing_in_progress_returns_400(client, monkeypatch):
    monkeypatch.setattr(
        "app.api.query_router.get_status",
        lambda repo_path: IndexStatus(status="running"),
    )
    response = client.post("/query", json=_BASE_BODY)
    assert response.status_code == 400


def test_empty_db_path_returns_422(client):
    response = client.post(
        "/query",
        json={"question": "What is bar?", "repo_path": "/repo", "db_path": ""},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# V1 path tests (intent_hint=None or "auto")
# ---------------------------------------------------------------------------

def test_happy_path_yields_token_events(client, monkeypatch, sample_node, sample_stats):
    """Stream yields one event: token per LLM token."""
    monkeypatch.setattr("app.api.query_router.get_status", lambda repo_path: _complete_status())
    monkeypatch.setattr("app.api.query_router.load_graph", lambda repo_path, db_path: nx.DiGraph())
    monkeypatch.setattr(
        "app.api.query_router.graph_rag_retrieve",
        lambda question, repo_path, G, db_path, max_nodes, hop_depth: ([sample_node], sample_stats),
    )
    monkeypatch.setattr("app.api.query_router.explore_stream", _make_async_gen("Hello", " world"))
    body = _read_stream(client, _BASE_BODY)
    token_events = [l for l in body.splitlines() if l.startswith("event: token")]
    assert len(token_events) == 2


def test_happy_path_yields_citations_event(client, monkeypatch, sample_node, sample_stats):
    """Stream yields event: citations with correct node_id."""
    monkeypatch.setattr("app.api.query_router.get_status", lambda repo_path: _complete_status())
    monkeypatch.setattr("app.api.query_router.load_graph", lambda repo_path, db_path: nx.DiGraph())
    monkeypatch.setattr(
        "app.api.query_router.graph_rag_retrieve",
        lambda question, repo_path, G, db_path, max_nodes, hop_depth: ([sample_node], sample_stats),
    )
    monkeypatch.setattr("app.api.query_router.explore_stream", _make_async_gen("Hello"))
    body = _read_stream(client, _BASE_BODY)

    lines = body.splitlines()
    citations_data = None
    for i, line in enumerate(lines):
        if line == "event: citations" and i + 1 < len(lines):
            citations_data = json.loads(lines[i + 1][len("data: "):])
            break

    assert citations_data is not None
    assert citations_data["citations"][0]["node_id"] == "src/foo.py::bar"


def test_happy_path_yields_done_event(client, monkeypatch, sample_node, sample_stats):
    """Stream yields event: done with retrieval_stats."""
    monkeypatch.setattr("app.api.query_router.get_status", lambda repo_path: _complete_status())
    monkeypatch.setattr("app.api.query_router.load_graph", lambda repo_path, db_path: nx.DiGraph())
    monkeypatch.setattr(
        "app.api.query_router.graph_rag_retrieve",
        lambda question, repo_path, G, db_path, max_nodes, hop_depth: ([sample_node], sample_stats),
    )
    monkeypatch.setattr("app.api.query_router.explore_stream", _make_async_gen("Hello"))
    body = _read_stream(client, _BASE_BODY)

    lines = body.splitlines()
    done_data = None
    for i, line in enumerate(lines):
        if line == "event: done" and i + 1 < len(lines):
            done_data = json.loads(lines[i + 1][len("data: "):])
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
    monkeypatch.setattr("app.api.query_router.explore_stream", _make_async_gen("Hello", " world"))
    body = _read_stream(client, _BASE_BODY)

    event_lines = [l for l in body.splitlines() if l.startswith("event:")]
    assert event_lines == ["event: token", "event: token", "event: citations", "event: done"]


def test_citations_contain_required_fields(client, monkeypatch, sample_node, sample_stats):
    """Citations include all required fields per citation."""
    monkeypatch.setattr("app.api.query_router.get_status", lambda repo_path: _complete_status())
    monkeypatch.setattr("app.api.query_router.load_graph", lambda repo_path, db_path: nx.DiGraph())
    monkeypatch.setattr(
        "app.api.query_router.graph_rag_retrieve",
        lambda question, repo_path, G, db_path, max_nodes, hop_depth: ([sample_node], sample_stats),
    )
    monkeypatch.setattr("app.api.query_router.explore_stream", _make_async_gen("Hi"))
    body = _read_stream(client, _BASE_BODY)

    lines = body.splitlines()
    citations_data = None
    for i, line in enumerate(lines):
        if line == "event: citations" and i + 1 < len(lines):
            citations_data = json.loads(lines[i + 1][len("data: "):])
            break

    assert citations_data is not None
    required = {"node_id", "file_path", "line_start", "line_end", "name", "type"}
    for citation in citations_data["citations"]:
        assert required.issubset(citation.keys())


def test_error_event_on_retrieval_failure(client, monkeypatch):
    """When graph_rag_retrieve raises, stream yields event: error with message."""
    monkeypatch.setattr("app.api.query_router.get_status", lambda repo_path: _complete_status())
    monkeypatch.setattr("app.api.query_router.load_graph", lambda repo_path, db_path: nx.DiGraph())
    monkeypatch.setattr(
        "app.api.query_router.graph_rag_retrieve",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("db error")),
    )
    monkeypatch.setattr("app.api.query_router.explore_stream", _make_async_gen())
    body = _read_stream(client, _BASE_BODY)

    lines = body.splitlines()
    error_data = None
    for i, line in enumerate(lines):
        if line == "event: error" and i + 1 < len(lines):
            error_data = json.loads(lines[i + 1][len("data: "):])
            break

    assert error_data is not None
    assert "db error" in error_data["message"]


def test_content_type_is_text_event_stream(client, monkeypatch, sample_node, sample_stats):
    """Response Content-Type must start with text/event-stream."""
    monkeypatch.setattr("app.api.query_router.get_status", lambda repo_path: _complete_status())
    monkeypatch.setattr("app.api.query_router.load_graph", lambda repo_path, db_path: nx.DiGraph())
    monkeypatch.setattr(
        "app.api.query_router.graph_rag_retrieve",
        lambda question, repo_path, G, db_path, max_nodes, hop_depth: ([sample_node], sample_stats),
    )
    monkeypatch.setattr("app.api.query_router.explore_stream", _make_async_gen("Hi"))
    with client.stream("POST", "/query", json=_BASE_BODY) as r:
        content_type = r.headers.get("content-type", "")
        r.read()
    assert content_type.startswith("text/event-stream")


def test_auto_sentinel_uses_v1_path(client, monkeypatch):
    """intent_hint='auto' routes to V1 path; orchestrator must NOT be called."""
    monkeypatch.setattr("app.api.query_router.get_status", lambda repo_path: _complete_status())
    monkeypatch.setattr("app.api.query_router.load_graph", lambda repo_path, db_path: None)
    monkeypatch.setattr(
        "app.api.query_router.graph_rag_retrieve",
        lambda question, repo_path, G, db_path, max_nodes, hop_depth: ([], {}),
    )
    monkeypatch.setattr("app.api.query_router.explore_stream", _make_async_gen("tok"))

    with patch("app.agent.orchestrator.build_graph") as mock_bg:
        body = _read_stream(
            client,
            {"question": "What is fn?", "repo_path": "/repo", "intent_hint": "auto", "db_path": "/repo/.nexus/graph.db"},
        )
        assert mock_bg.call_count == 0

    assert "event: token" in body


def test_none_intent_hint_uses_v1_path(client, monkeypatch):
    """Omitting intent_hint (defaults to None) routes to V1 path; orchestrator NOT called."""
    monkeypatch.setattr("app.api.query_router.get_status", lambda repo_path: _complete_status())
    monkeypatch.setattr("app.api.query_router.load_graph", lambda repo_path, db_path: None)
    monkeypatch.setattr(
        "app.api.query_router.graph_rag_retrieve",
        lambda question, repo_path, G, db_path, max_nodes, hop_depth: ([], {}),
    )
    monkeypatch.setattr("app.api.query_router.explore_stream", _make_async_gen("tok"))

    with patch("app.agent.orchestrator.build_graph") as mock_bg:
        body = _read_stream(
            client,
            {"question": "What is fn?", "repo_path": "/repo", "db_path": "/repo/.nexus/graph.db"},
        )
        assert mock_bg.call_count == 0

    assert "event: token" in body


# ---------------------------------------------------------------------------
# V2 path tests (named intent → orchestrator)
# ---------------------------------------------------------------------------

def test_v2_debug_intent_returns_result_event(client, monkeypatch, nexus_dir):
    """intent_hint='debug' invokes orchestrator; stream yields event: result with intent=debug."""
    monkeypatch.setattr("app.api.query_router.get_status", lambda repo_path: _complete_status())
    monkeypatch.setattr("app.api.query_router.load_graph", lambda repo_path, db_path: None)

    mock_graph = _make_mock_graph("debug", _make_debug_result())
    db_path = str(nexus_dir / "graph.db")

    with patch("app.agent.orchestrator.build_graph", return_value=mock_graph), \
         patch("app.config.get_settings", return_value=MagicMock(github_token="")), \
         patch("langgraph.checkpoint.sqlite.SqliteSaver"):
        body = _read_stream(
            client,
            {"question": "Why does fn crash?", "repo_path": "/repo", "intent_hint": "debug", "db_path": db_path},
        )

    assert "event: result" in body
    assert "event: done" in body
    assert '"intent": "debug"' in body
    assert mock_graph.invoke.call_count == 1


def test_v2_result_event_contains_required_keys(client, monkeypatch, nexus_dir):
    """The data: line after event: result is valid JSON with keys type, intent, result."""
    monkeypatch.setattr("app.api.query_router.get_status", lambda repo_path: _complete_status())
    monkeypatch.setattr("app.api.query_router.load_graph", lambda repo_path, db_path: None)

    mock_graph = _make_mock_graph("debug", _make_debug_result())
    db_path = str(nexus_dir / "graph.db")

    with patch("app.agent.orchestrator.build_graph", return_value=mock_graph), \
         patch("app.config.get_settings", return_value=MagicMock(github_token="")), \
         patch("langgraph.checkpoint.sqlite.SqliteSaver"):
        body = _read_stream(
            client,
            {"question": "Why does fn crash?", "repo_path": "/repo", "intent_hint": "debug", "db_path": db_path},
        )

    lines = body.splitlines()
    result_data = None
    for i, line in enumerate(lines):
        if line == "event: result" and i + 1 < len(lines):
            result_data = json.loads(lines[i + 1][len("data: "):])
            break

    assert result_data is not None
    assert {"type", "intent", "result"}.issubset(result_data.keys())


def test_v2_review_intent_routes_to_orchestrator(client, monkeypatch, nexus_dir):
    monkeypatch.setattr("app.api.query_router.get_status", lambda repo_path: _complete_status())
    monkeypatch.setattr("app.api.query_router.load_graph", lambda repo_path, db_path: None)

    mock_review = MagicMock()
    mock_review.model_dump.return_value = {"findings": []}
    mock_graph = _make_mock_graph("review", mock_review)
    db_path = str(nexus_dir / "graph.db")

    with patch("app.agent.orchestrator.build_graph", return_value=mock_graph), \
         patch("app.config.get_settings", return_value=MagicMock(github_token="")), \
         patch("langgraph.checkpoint.sqlite.SqliteSaver"):
        body = _read_stream(
            client,
            {"question": "Review this code", "repo_path": "/repo", "intent_hint": "review", "db_path": db_path},
        )

    assert "event: result" in body
    assert '"intent": "review"' in body


def test_v2_test_intent_routes_to_orchestrator(client, monkeypatch, nexus_dir):
    monkeypatch.setattr("app.api.query_router.get_status", lambda repo_path: _complete_status())
    monkeypatch.setattr("app.api.query_router.load_graph", lambda repo_path, db_path: None)

    mock_test = MagicMock()
    mock_test.model_dump.return_value = {"test_code": "def test_fn(): pass", "framework": "pytest"}
    mock_graph = _make_mock_graph("test", mock_test)
    db_path = str(nexus_dir / "graph.db")

    with patch("app.agent.orchestrator.build_graph", return_value=mock_graph), \
         patch("app.config.get_settings", return_value=MagicMock(github_token="")), \
         patch("langgraph.checkpoint.sqlite.SqliteSaver"):
        body = _read_stream(
            client,
            {"question": "Generate tests for fn", "repo_path": "/repo", "intent_hint": "test", "db_path": db_path},
        )

    assert "event: result" in body
    assert '"intent": "test"' in body


def test_v2_explain_intent_routes_to_orchestrator(client, monkeypatch, nexus_dir):
    monkeypatch.setattr("app.api.query_router.get_status", lambda repo_path: _complete_status())
    monkeypatch.setattr("app.api.query_router.load_graph", lambda repo_path, db_path: None)

    mock_explain = MagicMock()
    mock_explain.model_dump.return_value = {"answer": "fn does X", "nodes": [], "stats": {}}
    mock_graph = _make_mock_graph("explain", mock_explain)
    db_path = str(nexus_dir / "graph.db")

    with patch("app.agent.orchestrator.build_graph", return_value=mock_graph), \
         patch("app.config.get_settings", return_value=MagicMock(github_token="")), \
         patch("langgraph.checkpoint.sqlite.SqliteSaver"):
        body = _read_stream(
            client,
            {"question": "Explain fn", "repo_path": "/repo", "intent_hint": "explain", "db_path": db_path},
        )

    assert "event: result" in body


def test_v2_orchestrator_error_yields_error_event(client, monkeypatch, nexus_dir):
    """When graph.invoke raises, stream yields event: error with the message."""
    monkeypatch.setattr("app.api.query_router.get_status", lambda repo_path: _complete_status())
    monkeypatch.setattr("app.api.query_router.load_graph", lambda repo_path, db_path: None)

    mock_graph = MagicMock()
    mock_graph.invoke.side_effect = RuntimeError("graph failed")
    db_path = str(nexus_dir / "graph.db")

    with patch("app.agent.orchestrator.build_graph", return_value=mock_graph), \
         patch("langgraph.checkpoint.sqlite.SqliteSaver"):
        body = _read_stream(
            client,
            {"question": "Why does fn crash?", "repo_path": "/repo", "intent_hint": "debug", "db_path": db_path},
        )

    assert "event: error" in body
    assert "graph failed" in body


# ---------------------------------------------------------------------------
# /review/post-pr tests
# ---------------------------------------------------------------------------

def test_post_review_to_pr_no_token(client):
    """Returns 400 when GITHUB_TOKEN is not configured."""
    with patch("app.config.get_settings", return_value=MagicMock(github_token="")):
        resp = client.post("/review/post-pr", json={
            "findings": [],
            "repo": "owner/repo",
            "pr_number": 42,
            "commit_sha": "abc123",
        })
    assert resp.status_code == 400
    assert "GITHUB_TOKEN" in resp.json()["detail"]


def test_post_review_to_pr_calls_mcp(client):
    """Calls post_review_comments() when token is present."""
    with patch("app.config.get_settings", return_value=MagicMock(github_token="ghp_test")), \
         patch("app.mcp.tools.post_review_comments", return_value={"posted": 2, "overflow": False}) as mock_post:
        resp = client.post("/review/post-pr", json={
            "findings": [{"file_path": "app/foo.py", "line_start": 10, "severity": "high", "description": "Issue", "suggestion": "Fix it", "rule": "R1", "confidence": 0.9}],
            "repo": "owner/repo",
            "pr_number": 42,
            "commit_sha": "abc123",
        })
    assert resp.status_code == 200
    assert resp.json()["posted"] == 2
    mock_post.assert_called_once()
