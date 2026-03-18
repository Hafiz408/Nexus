"""Tests for graph_store.py and embedder.py (Phase 5).

graph_store tests (STORE-01, STORE-02, STORE-03):
  - Uses real SQLite in a tmp dir (no Docker needed).

embedder tests (EMBED-01 through EMBED-06):
  - Mocks OpenAI client so no real API call is made.
  - Mocks psycopg2 connection so no Docker needed for unit tests.
  # Requires Docker for integration tests: docker compose up -d postgres
"""

import os
import sqlite3
import tempfile

import networkx as nx
import pytest
from unittest.mock import MagicMock, patch

from app.ingestion.graph_store import save_graph, load_graph, delete_nodes_for_files
from app.ingestion.embedder import embed_and_store, init_pgvector_table, EMBED_BATCH_SIZE
from app.models.schemas import CodeNode


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Isolated SQLite database in a temp directory.

    Monkeypatches both graph_store._db_path() and embedder._sqlite_db_path()
    to return the same tmp path so both modules write to the same test file.
    """
    db_path = str(tmp_path / "test_nexus.db")
    import app.ingestion.graph_store as gs
    import app.ingestion.embedder as emb
    monkeypatch.setattr(gs, "_db_path", lambda: db_path)
    monkeypatch.setattr(emb, "_sqlite_db_path", lambda: db_path)
    return db_path


@pytest.fixture
def sample_graph():
    """Two-node DiGraph with one CALLS edge — used for graph_store tests."""
    G = nx.DiGraph()
    G.add_node(
        "src/foo.py::bar",
        name="bar",
        file_path="src/foo.py",
        node_id="src/foo.py::bar",
        type="function",
        line_start=1,
        line_end=10,
        signature="def bar():",
        docstring="Does bar.",
        body_preview="pass",
        complexity=1,
        embedding_text="def bar():\nDoes bar.\npass",
        pagerank=0.4,
        in_degree=1,
        out_degree=2,
    )
    G.add_node(
        "src/baz.py::Qux",
        name="Qux",
        file_path="src/baz.py",
        node_id="src/baz.py::Qux",
        type="class",
        line_start=5,
        line_end=20,
        signature="class Qux:",
        docstring=None,
        body_preview="def __init__(self): pass",
        complexity=2,
        embedding_text="class Qux:\n\ndef __init__(self): pass",
        pagerank=0.6,
        in_degree=0,
        out_degree=1,
    )
    G.add_edge("src/foo.py::bar", "src/baz.py::Qux", edge_type="CALLS")
    return G


@pytest.fixture
def mock_openai_client():
    """Returns a mock OpenAI client that yields deterministic embeddings.

    Each call to embeddings.create() returns 1536-dimensional vectors seeded
    with numpy random (seed=42) for reproducibility.
    """
    import numpy as np
    np.random.seed(42)

    def fake_create(model, input):
        items = []
        for i, _ in enumerate(input):
            emb = MagicMock()
            emb.embedding = np.random.rand(1536).tolist()
            emb.index = i
            items.append(emb)
        resp = MagicMock()
        resp.data = items
        return resp

    client = MagicMock()
    client.embeddings.create.side_effect = fake_create
    return client


@pytest.fixture
def sample_nodes():
    """Three CodeNode objects for embedder unit tests."""
    return [
        CodeNode(
            node_id=f"src/a.py::func_{i}",
            name=f"func_{i}",
            type="function",
            file_path="src/a.py",
            line_start=i * 10 + 1,
            line_end=i * 10 + 5,
            signature=f"def func_{i}():",
            embedding_text=f"def func_{i}():\n\n",
        )
        for i in range(3)
    ]


# ---------------------------------------------------------------------------
# graph_store tests: STORE-01, STORE-02, STORE-03
# ---------------------------------------------------------------------------

def test_save_and_load_graph_roundtrip(tmp_db, sample_graph):
    """STORE-01 + STORE-02: save then load returns identical nodes and edges."""
    save_graph(sample_graph, "/tmp/repo_a")
    G2 = load_graph("/tmp/repo_a")
    assert set(G2.nodes()) == set(sample_graph.nodes())
    assert list(G2.edges()) == list(sample_graph.edges())
    assert G2.nodes["src/foo.py::bar"]["pagerank"] == pytest.approx(0.4)
    assert G2.nodes["src/baz.py::Qux"]["name"] == "Qux"


def test_load_graph_empty(tmp_db):
    """load_graph on a repo with no saved data returns empty DiGraph."""
    G = load_graph("/tmp/nonexistent_repo")
    assert isinstance(G, nx.DiGraph)
    assert G.number_of_nodes() == 0


def test_save_graph_overwrites_on_second_call(tmp_db, sample_graph):
    """STORE-01: re-saving replaces previous data — no duplicates."""
    save_graph(sample_graph, "/tmp/repo_b")
    save_graph(sample_graph, "/tmp/repo_b")
    G2 = load_graph("/tmp/repo_b")
    assert G2.number_of_nodes() == 2  # not 4


def test_delete_nodes_for_files_removes_nodes_and_edges(tmp_db, sample_graph):
    """STORE-03: delete_nodes_for_files removes matching nodes and their incident edges."""
    save_graph(sample_graph, "/tmp/repo_c")
    delete_nodes_for_files(["src/foo.py"], "/tmp/repo_c")
    G2 = load_graph("/tmp/repo_c")
    assert "src/foo.py::bar" not in G2.nodes()
    assert ("src/foo.py::bar", "src/baz.py::Qux") not in G2.edges()
    # Unrelated node survives
    assert "src/baz.py::Qux" in G2.nodes()


def test_delete_nodes_for_files_empty_list_is_noop(tmp_db, sample_graph):
    """STORE-03 edge case: empty file_paths list changes nothing."""
    save_graph(sample_graph, "/tmp/repo_d")
    delete_nodes_for_files([], "/tmp/repo_d")
    G2 = load_graph("/tmp/repo_d")
    assert G2.number_of_nodes() == 2


def test_repos_isolated_in_single_db(tmp_db, sample_graph):
    """Two different repo_paths share one DB file without cross-contamination."""
    save_graph(sample_graph, "/tmp/repo_x")
    G_empty = nx.DiGraph()
    save_graph(G_empty, "/tmp/repo_y")
    assert load_graph("/tmp/repo_x").number_of_nodes() == 2
    assert load_graph("/tmp/repo_y").number_of_nodes() == 0


# ---------------------------------------------------------------------------
# embedder tests: EMBED-01 through EMBED-06
# All use mocked OpenAI + mocked psycopg2 — no Docker required for unit tests.
# ---------------------------------------------------------------------------

def test_embed_batch_size_constant():
    """EMBED-04: batch size is 100."""
    assert EMBED_BATCH_SIZE == 100


def test_embed_and_store_returns_count(tmp_db, sample_nodes, mock_openai_client):
    """EMBED-01 + EMBED-06: returns count equal to number of nodes."""
    with patch("app.ingestion.embedder.OpenAI", return_value=mock_openai_client):
        with patch("app.ingestion.embedder.get_db_connection") as mock_conn:
            # Mock psycopg2 connection so no Docker needed for this unit test
            pg_conn = MagicMock()
            pg_conn.cursor.return_value.__enter__ = MagicMock(return_value=MagicMock())
            pg_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_conn.return_value = pg_conn
            # Patch register_vector and execute_values in the embedder module namespace
            # (they were imported via `from ... import`, so must patch the local name)
            with patch("app.ingestion.embedder.execute_values"):
                with patch("app.ingestion.embedder.register_vector"):
                    count = embed_and_store(sample_nodes, "/tmp/test_repo")
    assert count == len(sample_nodes)


def test_fts5_table_supports_name_match(tmp_db, sample_nodes, mock_openai_client):
    """EMBED-03: After embed_and_store, FTS5 supports exact name MATCH."""
    with patch("app.ingestion.embedder.OpenAI", return_value=mock_openai_client):
        with patch("app.ingestion.embedder.get_db_connection") as mock_conn:
            pg_conn = MagicMock()
            pg_conn.cursor.return_value.__enter__ = MagicMock(return_value=MagicMock())
            pg_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_conn.return_value = pg_conn
            with patch("app.ingestion.embedder.execute_values"):
                with patch("app.ingestion.embedder.register_vector"):
                    embed_and_store(sample_nodes, "/tmp/fts_test_repo")
    conn = sqlite3.connect(tmp_db)
    rows = conn.execute(
        'SELECT node_id FROM code_fts WHERE name MATCH ?', ('"func_0"',)
    ).fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0][0] == "src/a.py::func_0"


def test_embed_and_store_upsert_no_duplicates(tmp_db, sample_nodes, mock_openai_client):
    """EMBED-05: calling embed_and_store twice on same nodes yields same FTS row count."""
    with patch("app.ingestion.embedder.OpenAI", return_value=mock_openai_client):
        with patch("app.ingestion.embedder.get_db_connection") as mock_conn:
            pg_conn = MagicMock()
            pg_conn.cursor.return_value.__enter__ = MagicMock(return_value=MagicMock())
            pg_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_conn.return_value = pg_conn
            with patch("app.ingestion.embedder.execute_values"):
                with patch("app.ingestion.embedder.register_vector"):
                    embed_and_store(sample_nodes, "/tmp/upsert_repo")
                    embed_and_store(sample_nodes, "/tmp/upsert_repo")
    conn = sqlite3.connect(tmp_db)
    count = conn.execute("SELECT COUNT(*) FROM code_fts").fetchone()[0]
    conn.close()
    assert count == len(sample_nodes)  # not doubled
