"""Tests for POST /query V2 endpoint branch and POST /review/post-pr endpoint (TST-09).

Covers all V2 routing scenarios, sentinel handling (auto/None fall-through to V1),
SSE payload structure (event: result, event: done, event: error), error propagation,
and the /review/post-pr endpoint (GITHUB_TOKEN gate + post_review_comments() call).

All external I/O is mocked — zero live LLM calls, zero live database connections.
No environment variables required to run this suite.

Patch strategy:
  - app.api.query_router.get_status   → monkeypatch.setattr
  - app.api.query_router.load_graph   → monkeypatch.setattr
  - app.agent.orchestrator.build_graph → patch() at source module namespace
      NOTE: build_graph is lazy-imported inside v2_event_generator body;
      Python resolves the name in the source module (app.agent.orchestrator) when the
      lazy `from app.agent.orchestrator import build_graph` executes — patching at
      the source module intercepts the binding. (Phase 24 decision, consistent with
      Phase 17 router-agent pattern)
  - app.api.query_router.graph_rag_retrieve → monkeypatch for V1-path tests
  - app.api.query_router.explore_stream     → monkeypatch for V1-path tests
  - app.config.get_settings                 → patch() for /review/post-pr tests
  - app.mcp.tools.post_review_comments      → patch() for /review/post-pr tests
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.schemas import IndexStatus
from app.agent.debugger import DebugResult, SuspectNode


# ---------------------------------------------------------------------------
# Shared fixtures (mirror V1 test_query_router.py exactly to avoid conflicts)
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    """TestClient with lifespan enabled."""
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_status():
    """Return a complete IndexStatus for monkeypatching get_status."""
    return IndexStatus(status="complete")


def _make_mock_graph(intent: str, specialist_result):
    """Return a MagicMock graph whose invoke() returns a NexusState-shaped dict."""
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


@pytest.fixture()
def nexus_dir(tmp_path):
    """Return a writable .nexus directory path for use as db_path parent."""
    d = tmp_path / ".nexus"
    d.mkdir()
    return d


def _read_stream(client, json_body):
    """POST /query with stream=True; read body inside context manager and return it."""
    with client.stream("POST", "/query", json=json_body) as r:
        r.read()
        body = r.text
    return body


def _make_debug_result() -> DebugResult:
    """Return a minimal DebugResult for use in V2 debug-intent tests."""
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


def _make_async_gen_token():
    """Return an async generator that yields a single 'tok' string (for V1-path tests)."""
    async def _gen(nodes, question, **kwargs):
        yield "tok"
    return _gen


# ---------------------------------------------------------------------------
# Test 1: debug intent invokes orchestrator; stream yields event: result + done
# ---------------------------------------------------------------------------

def test_v2_debug_intent_returns_result_event(client, monkeypatch, nexus_dir):
    """intent_hint='debug' invokes orchestrator; stream yields event: result with intent=debug."""
    monkeypatch.setattr("app.api.query_router.get_status", lambda repo_path: _make_status())
    monkeypatch.setattr("app.api.query_router.load_graph", lambda repo_path, db_path: None)

    debug_result = _make_debug_result()
    mock_graph = _make_mock_graph("debug", debug_result)
    mock_settings = MagicMock(github_token="")
    db_path = str(nexus_dir / "graph.db")

    with patch("app.agent.orchestrator.build_graph", return_value=mock_graph), \
         patch("app.config.get_settings", return_value=mock_settings), \
         patch("langgraph.checkpoint.sqlite.SqliteSaver"):
        body = _read_stream(
            client,
            {"question": "Why does fn crash?", "repo_path": "/repo", "intent_hint": "debug", "db_path": db_path},
        )

    assert "event: result" in body
    assert "event: done" in body
    assert '"intent": "debug"' in body
    assert mock_graph.invoke.call_count == 1


# ---------------------------------------------------------------------------
# Test 2: event: result data line contains type, intent, result keys
# ---------------------------------------------------------------------------

def test_v2_result_event_contains_result_key(client, monkeypatch, nexus_dir):
    """The data: line after 'event: result' is valid JSON with keys type, intent, result."""
    monkeypatch.setattr("app.api.query_router.get_status", lambda repo_path: _make_status())
    monkeypatch.setattr("app.api.query_router.load_graph", lambda repo_path, db_path: None)

    debug_result = _make_debug_result()
    mock_graph = _make_mock_graph("debug", debug_result)
    mock_settings = MagicMock(github_token="")
    db_path = str(nexus_dir / "graph.db")

    with patch("app.agent.orchestrator.build_graph", return_value=mock_graph), \
         patch("app.config.get_settings", return_value=mock_settings), \
         patch("langgraph.checkpoint.sqlite.SqliteSaver"):
        body = _read_stream(
            client,
            {"question": "Why does fn crash?", "repo_path": "/repo", "intent_hint": "debug", "db_path": db_path},
        )

    # Extract the data line immediately following "event: result"
    lines = body.splitlines()
    result_data = None
    for i, line in enumerate(lines):
        if line == "event: result" and i + 1 < len(lines):
            data_line = lines[i + 1]
            assert data_line.startswith("data: ")
            result_data = json.loads(data_line[len("data: "):])
            break

    assert result_data is not None
    assert "type" in result_data
    assert "intent" in result_data
    assert "result" in result_data


# ---------------------------------------------------------------------------
# Test 3: review intent routes to orchestrator
# ---------------------------------------------------------------------------

def test_v2_review_intent_routes_to_orchestrator(client, monkeypatch, nexus_dir):
    """intent_hint='review' routes through orchestrator; stream yields event: result with intent=review."""
    monkeypatch.setattr("app.api.query_router.get_status", lambda repo_path: _make_status())
    monkeypatch.setattr("app.api.query_router.load_graph", lambda repo_path, db_path: None)

    mock_review = MagicMock()
    mock_review.model_dump.return_value = {"findings": []}
    mock_graph = _make_mock_graph("review", mock_review)
    mock_settings = MagicMock(github_token="")
    db_path = str(nexus_dir / "graph.db")

    with patch("app.agent.orchestrator.build_graph", return_value=mock_graph), \
         patch("app.config.get_settings", return_value=mock_settings), \
         patch("langgraph.checkpoint.sqlite.SqliteSaver"):
        body = _read_stream(
            client,
            {"question": "Review this code", "repo_path": "/repo", "intent_hint": "review", "db_path": db_path},
        )

    assert "event: result" in body
    assert '"intent": "review"' in body


# ---------------------------------------------------------------------------
# Test 4: test intent routes to orchestrator
# ---------------------------------------------------------------------------

def test_v2_test_intent_routes_to_orchestrator(client, monkeypatch, nexus_dir):
    """intent_hint='test' routes through orchestrator; stream yields event: result with intent=test."""
    monkeypatch.setattr("app.api.query_router.get_status", lambda repo_path: _make_status())
    monkeypatch.setattr("app.api.query_router.load_graph", lambda repo_path, db_path: None)

    mock_test_result = MagicMock()
    mock_test_result.model_dump.return_value = {"test_code": "def test_fn(): pass", "framework": "pytest"}
    mock_graph = _make_mock_graph("test", mock_test_result)
    mock_settings = MagicMock(github_token="")
    db_path = str(nexus_dir / "graph.db")

    with patch("app.agent.orchestrator.build_graph", return_value=mock_graph), \
         patch("app.config.get_settings", return_value=mock_settings), \
         patch("langgraph.checkpoint.sqlite.SqliteSaver"):
        body = _read_stream(
            client,
            {"question": "Generate tests for fn", "repo_path": "/repo", "intent_hint": "test", "db_path": db_path},
        )

    assert "event: result" in body
    assert '"intent": "test"' in body


# ---------------------------------------------------------------------------
# Test 5: explain intent routes to orchestrator
# ---------------------------------------------------------------------------

def test_v2_explain_intent_routes_to_orchestrator(client, monkeypatch, nexus_dir):
    """intent_hint='explain' routes through orchestrator; stream yields event: result."""
    monkeypatch.setattr("app.api.query_router.get_status", lambda repo_path: _make_status())
    monkeypatch.setattr("app.api.query_router.load_graph", lambda repo_path, db_path: None)

    mock_explain = MagicMock()
    mock_explain.model_dump.return_value = {"answer": "fn does X", "nodes": [], "stats": {}}
    mock_graph = _make_mock_graph("explain", mock_explain)
    mock_settings = MagicMock(github_token="")
    db_path = str(nexus_dir / "graph.db")

    with patch("app.agent.orchestrator.build_graph", return_value=mock_graph), \
         patch("app.config.get_settings", return_value=mock_settings), \
         patch("langgraph.checkpoint.sqlite.SqliteSaver"):
        body = _read_stream(
            client,
            {"question": "Explain fn", "repo_path": "/repo", "intent_hint": "explain", "db_path": db_path},
        )

    assert "event: result" in body


# ---------------------------------------------------------------------------
# Test 6: intent_hint="auto" falls through to V1 path — orchestrator NOT called
# ---------------------------------------------------------------------------

def test_v2_auto_sentinel_uses_v1_path(client, monkeypatch):
    """intent_hint='auto' is the V1-path sentinel; build_graph must NOT be called."""
    monkeypatch.setattr("app.api.query_router.get_status", lambda repo_path: _make_status())
    monkeypatch.setattr("app.api.query_router.load_graph", lambda repo_path, db_path: None)
    monkeypatch.setattr(
        "app.api.query_router.graph_rag_retrieve",
        lambda question, repo_path, G, db_path, max_nodes, hop_depth: ([], {}),
    )
    monkeypatch.setattr(
        "app.api.query_router.explore_stream",
        _make_async_gen_token(),
    )

    with patch("app.agent.orchestrator.build_graph") as mock_bg:
        body = _read_stream(
            client,
            {"question": "What is fn?", "repo_path": "/repo", "intent_hint": "auto", "db_path": "/repo/.nexus/graph.db"},
        )
        assert mock_bg.call_count == 0

    assert "event: token" in body


# ---------------------------------------------------------------------------
# Test 7: No intent_hint field (defaults to None) falls through to V1 path
# ---------------------------------------------------------------------------

def test_v2_none_intent_hint_uses_v1_path(client, monkeypatch):
    """Omitting intent_hint (defaults to None) routes to V1 path; orchestrator NOT invoked."""
    monkeypatch.setattr("app.api.query_router.get_status", lambda repo_path: _make_status())
    monkeypatch.setattr("app.api.query_router.load_graph", lambda repo_path, db_path: None)
    monkeypatch.setattr(
        "app.api.query_router.graph_rag_retrieve",
        lambda question, repo_path, G, db_path, max_nodes, hop_depth: ([], {}),
    )
    monkeypatch.setattr(
        "app.api.query_router.explore_stream",
        _make_async_gen_token(),
    )

    with patch("app.agent.orchestrator.build_graph") as mock_bg:
        # No intent_hint key in request body — defaults to None
        body = _read_stream(
            client,
            {"question": "What is fn?", "repo_path": "/repo", "db_path": "/repo/.nexus/graph.db"},
        )
        assert mock_bg.call_count == 0

    assert "event: token" in body


# ---------------------------------------------------------------------------
# Test 8: orchestrator error is surfaced as event: error in SSE stream
# ---------------------------------------------------------------------------

def test_v2_orchestrator_error_yields_error_event(client, monkeypatch, nexus_dir):
    """When graph.invoke raises RuntimeError, the stream yields event: error with the message."""
    monkeypatch.setattr("app.api.query_router.get_status", lambda repo_path: _make_status())
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
# Test 9: /review/post-pr returns 400 when GITHUB_TOKEN is not configured
# ---------------------------------------------------------------------------

def test_post_review_to_pr_no_token(client):
    """Returns 400 when GITHUB_TOKEN is not configured."""
    with patch("app.config.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(github_token="")
        resp = client.post("/review/post-pr", json={
            "findings": [],
            "repo": "owner/repo",
            "pr_number": 42,
            "commit_sha": "abc123",
        })
    assert resp.status_code == 400
    assert "GITHUB_TOKEN" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Test 10: /review/post-pr calls post_review_comments() when token is present
# ---------------------------------------------------------------------------

def test_post_review_to_pr_calls_mcp(client):
    """Calls post_review_comments() when token is present."""
    with patch("app.config.get_settings") as mock_settings, \
         patch("app.mcp.tools.post_review_comments") as mock_post:
        mock_settings.return_value = MagicMock(github_token="ghp_test")
        mock_post.return_value = {"posted": 2, "overflow": False}
        resp = client.post("/review/post-pr", json={
            "findings": [{"file_path": "app/foo.py", "line_start": 10, "severity": "high", "description": "Issue", "suggestion": "Fix it", "rule": "R1", "confidence": 0.9}],
            "repo": "owner/repo",
            "pr_number": 42,
            "commit_sha": "abc123",
        })
    assert resp.status_code == 200
    result = resp.json()
    assert result["posted"] == 2
    mock_post.assert_called_once()
