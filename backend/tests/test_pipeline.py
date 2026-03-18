"""Unit tests for pipeline.py (Phase 6 — PIPE-01 through PIPE-05).

All I/O stages are mocked at the app.ingestion.pipeline.* namespace
(same pattern as test_embedder.py — from-imports bind at load time).

Tests run without Docker, OpenAI keys, or real SQLite state.
"""

import asyncio

import networkx as nx
import pytest
from unittest.mock import patch, MagicMock

from app.ingestion.pipeline import run_ingestion, get_status
from app.models.schemas import IndexStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_graph(n_nodes: int = 1, n_edges: int = 1) -> nx.DiGraph:
    """Build a minimal DiGraph with n_nodes nodes and n_edges self-loops."""
    G = nx.DiGraph()
    for i in range(n_nodes):
        G.add_node(f"a.py::func_{i}")
    for i in range(n_edges):
        node = f"a.py::func_{i % n_nodes}"
        G.add_edge(node, node)
    return G


# ---------------------------------------------------------------------------
# Fixture: patch all I/O stages simultaneously
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_pipeline_stages(tmp_path):
    """Patch all pipeline I/O stages so the pipeline runs without any real I/O.

    Yields a dict of mock objects so individual tests can inspect call args.
    """
    G = _make_graph(n_nodes=1, n_edges=1)

    with patch(
        "app.ingestion.pipeline.walk_repo",
        return_value=[
            {"path": str(tmp_path / "a.py"), "language": "python", "size_kb": 1}
        ],
    ) as mock_walk:
        with patch(
            "app.ingestion.pipeline.parse_file",
            return_value=([], []),
        ) as mock_parse:
            with patch(
                "app.ingestion.pipeline.build_graph",
                return_value=G,
            ) as mock_build:
                with patch(
                    "app.ingestion.pipeline.save_graph",
                ) as mock_save:
                    with patch(
                        "app.ingestion.pipeline.embed_and_store",
                        return_value=1,
                    ) as mock_embed:
                        yield {
                            "walk_repo": mock_walk,
                            "parse_file": mock_parse,
                            "build_graph": mock_build,
                            "save_graph": mock_save,
                            "embed_and_store": mock_embed,
                            "graph": G,
                        }


# ---------------------------------------------------------------------------
# PIPE-01: run_ingestion returns status='complete' with correct counts
# ---------------------------------------------------------------------------

def test_run_ingestion_complete(mock_pipeline_stages, tmp_path):
    """PIPE-01: Happy path — status='complete', counts match mocked returns."""
    result = asyncio.run(run_ingestion(str(tmp_path), ["python"]))

    assert result.status == "complete"
    assert result.nodes_indexed == 1       # embed_and_store returns 1
    assert result.edges_indexed == 1       # G has 1 self-loop edge
    assert result.files_processed == 1     # walk_repo returns 1 file


# ---------------------------------------------------------------------------
# PIPE-02: get_status returns the IndexStatus stored by the most recent run
# ---------------------------------------------------------------------------

def test_status_stored_after_run(mock_pipeline_stages, tmp_path):
    """PIPE-02: get_status returns the latest IndexStatus for the repo_path."""
    asyncio.run(run_ingestion(str(tmp_path), ["python"]))

    status = get_status(str(tmp_path))

    assert status is not None
    assert status.status == "complete"


# ---------------------------------------------------------------------------
# PIPE-03: Incremental path calls delete_nodes_for_files with changed_files
# ---------------------------------------------------------------------------

def test_incremental_calls_delete(tmp_path):
    """PIPE-03: When changed_files is passed, delete_nodes_for_files is called first."""
    changed = [str(tmp_path / "a.py")]

    G = _make_graph(n_nodes=1, n_edges=1)

    with patch("app.ingestion.pipeline.delete_nodes_for_files") as mock_delete:
        with patch(
            "app.ingestion.pipeline.parse_file",
            return_value=([], []),
        ):
            with patch(
                "app.ingestion.pipeline.build_graph",
                return_value=G,
            ):
                with patch("app.ingestion.pipeline.save_graph"):
                    with patch(
                        "app.ingestion.pipeline.embed_and_store",
                        return_value=1,
                    ):
                        asyncio.run(
                            run_ingestion(str(tmp_path), ["python"], changed_files=changed)
                        )

    mock_delete.assert_called_once_with(changed, str(tmp_path))


# ---------------------------------------------------------------------------
# PIPE-04: walk_repo or build_graph error → status='failed' with error message
# ---------------------------------------------------------------------------

def test_run_ingestion_error_returns_failed(tmp_path):
    """PIPE-04: An exception during walk_repo surfaces as status='failed'."""
    with patch(
        "app.ingestion.pipeline.walk_repo",
        side_effect=RuntimeError("disk error"),
    ):
        result = asyncio.run(run_ingestion(str(tmp_path), ["python"]))

    assert result.status == "failed"
    assert "disk error" in result.error


# ---------------------------------------------------------------------------
# PIPE-05: parse_file errors within gather are caught per-file — not fatal
# ---------------------------------------------------------------------------

def test_parse_failure_is_partial_not_fatal(tmp_path):
    """PIPE-05: A single parse_file failure does not abort the whole ingestion."""
    two_files = [
        {"path": str(tmp_path / "bad.py"), "language": "python", "size_kb": 1},
        {"path": str(tmp_path / "good.py"), "language": "python", "size_kb": 1},
    ]

    G = _make_graph(n_nodes=0, n_edges=0)

    with patch(
        "app.ingestion.pipeline.walk_repo",
        return_value=two_files,
    ):
        with patch(
            "app.ingestion.pipeline.parse_file",
            side_effect=[RuntimeError("bad file"), ([], [])],
        ):
            with patch(
                "app.ingestion.pipeline.build_graph",
                return_value=G,
            ):
                with patch("app.ingestion.pipeline.save_graph"):
                    with patch(
                        "app.ingestion.pipeline.embed_and_store",
                        return_value=0,
                    ):
                        result = asyncio.run(run_ingestion(str(tmp_path), ["python"]))

    # One file failed but the pipeline completes — not fatal
    assert result.status == "complete"
