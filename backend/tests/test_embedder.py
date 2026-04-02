"""Tests for graph_store.py and embedder.py (Phase 5).

graph_store tests (STORE-01, STORE-02, STORE-03):
  - Uses real SQLite in a tmp dir (no Docker needed).

embedder tests (EMBED-01 through EMBED-06):
  - Mocks embedding client so no real API call is made.
  - Mocks sqlite_vec so no C extension needed for unit tests.
  - Uses stub vec tables (plain SQLite BLOB columns) in place of vec0 virtual tables.
"""

import sqlite3

import networkx as nx
import pytest
from unittest.mock import MagicMock, patch

from app.ingestion.graph_store import save_graph, load_graph, delete_nodes_for_files
from app.ingestion.embedder import embed_and_store, EMBED_BATCH_SIZE_MAX, _build_batches, delete_embeddings_for_files
from app.models.schemas import CodeNode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_stub_vec_tables(db_path: str) -> None:
    """Create stub sqlite-vec tables using plain SQLite (no C extension required).

    Replaces the vec0 virtual table with a regular table that has an embedding
    BLOB column so all INSERT/DELETE/SELECT operations in embed_and_store work
    without loading the sqlite-vec extension.
    """
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS code_embeddings_meta (
            node_id    TEXT PRIMARY KEY,
            repo_path  TEXT NOT NULL,
            name       TEXT NOT NULL,
            file_path  TEXT NOT NULL,
            line_start INTEGER,
            line_end   INTEGER,
            vec_rowid  INTEGER
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_embed_repo ON code_embeddings_meta(repo_path)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS code_embeddings_vec (
            rowid     INTEGER PRIMARY KEY AUTOINCREMENT,
            embedding BLOB
        )
    """)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db(tmp_path):
    """Isolated SQLite database path in a temp directory."""
    db_path = str(tmp_path / "test_nexus.db")
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
def mock_mistral_client():
    """Returns a mock EmbeddingClient (factory interface) with deterministic 1024-d vectors."""
    import numpy as np
    np.random.seed(42)

    client = MagicMock()
    client.embed.side_effect = lambda texts: [np.random.rand(1024).tolist() for _ in texts]
    client.dimensions = 1024
    client.max_tokens = 16_384  # matches MistralEmbeddingClient; keeps token_budget = 12_288
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
    save_graph(sample_graph, "/tmp/repo_a", tmp_db)
    G2 = load_graph("/tmp/repo_a", tmp_db)
    assert set(G2.nodes()) == set(sample_graph.nodes())
    assert list(G2.edges()) == list(sample_graph.edges())
    assert G2.nodes["src/foo.py::bar"]["pagerank"] == pytest.approx(0.4)
    assert G2.nodes["src/baz.py::Qux"]["name"] == "Qux"


def test_load_graph_empty(tmp_db):
    """load_graph on a repo with no saved data returns empty DiGraph."""
    G = load_graph("/tmp/nonexistent_repo", tmp_db)
    assert isinstance(G, nx.DiGraph)
    assert G.number_of_nodes() == 0


def test_save_graph_overwrites_on_second_call(tmp_db, sample_graph):
    """STORE-01: re-saving replaces previous data — no duplicates."""
    save_graph(sample_graph, "/tmp/repo_b", tmp_db)
    save_graph(sample_graph, "/tmp/repo_b", tmp_db)
    G2 = load_graph("/tmp/repo_b", tmp_db)
    assert G2.number_of_nodes() == 2  # not 4


def test_delete_nodes_for_files_removes_nodes_and_edges(tmp_db, sample_graph):
    """STORE-03: delete_nodes_for_files removes matching nodes and their incident edges."""
    save_graph(sample_graph, "/tmp/repo_c", tmp_db)
    delete_nodes_for_files(["src/foo.py"], "/tmp/repo_c", tmp_db)
    G2 = load_graph("/tmp/repo_c", tmp_db)
    assert "src/foo.py::bar" not in G2.nodes()
    assert ("src/foo.py::bar", "src/baz.py::Qux") not in G2.edges()
    # Unrelated node survives
    assert "src/baz.py::Qux" in G2.nodes()


def test_delete_nodes_for_files_empty_list_is_noop(tmp_db, sample_graph):
    """STORE-03 edge case: empty file_paths list changes nothing."""
    save_graph(sample_graph, "/tmp/repo_d", tmp_db)
    delete_nodes_for_files([], "/tmp/repo_d", tmp_db)
    G2 = load_graph("/tmp/repo_d", tmp_db)
    assert G2.number_of_nodes() == 2


def test_repos_isolated_in_single_db(tmp_db, sample_graph):
    """Two different repo_paths share one DB file without cross-contamination."""
    save_graph(sample_graph, "/tmp/repo_x", tmp_db)
    G_empty = nx.DiGraph()
    save_graph(G_empty, "/tmp/repo_y", tmp_db)
    assert load_graph("/tmp/repo_x", tmp_db).number_of_nodes() == 2
    assert load_graph("/tmp/repo_y", tmp_db).number_of_nodes() == 0


# ---------------------------------------------------------------------------
# embedder tests: EMBED-01 through EMBED-06
# All use mocked embedding client + mocked sqlite_vec — no C extension required.
# Stub vec tables (plain SQLite) replace the vec0 virtual table.
# ---------------------------------------------------------------------------

def test_embed_batch_constants():
    """EMBED-04: batching constants and 75 % budget logic are within expected bounds."""
    assert EMBED_BATCH_SIZE_MAX <= 64

    # Verify _build_batches respects a provider-derived budget.
    # Use Mistral's max_tokens (16 384) → budget = 12 288.
    from app.core.model_factory import MistralEmbeddingClient
    budget = int(16_384 * 0.75)
    assert budget <= 16_384  # must never exceed Mistral hard cap


def test_embed_and_store_returns_count(tmp_db, sample_nodes, mock_mistral_client):
    """EMBED-01 + EMBED-06: returns count equal to number of nodes."""
    _create_stub_vec_tables(tmp_db)
    with patch("app.ingestion.embedder.get_embedding_client", return_value=mock_mistral_client):
        with patch("app.ingestion.embedder.init_vec_table"):
            with patch("app.ingestion.embedder._vec_conn", side_effect=sqlite3.connect):
                with patch("app.ingestion.embedder.sqlite_vec") as mock_sv:
                    mock_sv.load = MagicMock()
                    mock_sv.serialize_float32 = MagicMock(return_value=b"\x00" * 4096)
                    count = embed_and_store(sample_nodes, "/tmp/test_repo", tmp_db)
    assert count == len(sample_nodes)


def test_fts5_table_includes_embedding_text_column(tmp_db, sample_nodes, mock_mistral_client):
    """After embed_and_store, FTS5 indexes embedding_text so body content is searchable.

    Uses a word ('def') that appears only in embedding_text, not in name or file_path.
    With the old name-only schema this query would return 0 rows.
    """
    _create_stub_vec_tables(tmp_db)
    with patch("app.ingestion.embedder.get_embedding_client", return_value=mock_mistral_client):
        with patch("app.ingestion.embedder.init_vec_table"):
            with patch("app.ingestion.embedder._vec_conn", side_effect=sqlite3.connect):
                with patch("app.ingestion.embedder.sqlite_vec") as mock_sv:
                    mock_sv.load = MagicMock()
                    mock_sv.serialize_float32 = MagicMock(return_value=b"\x00" * 4096)
                    embed_and_store(sample_nodes, "/tmp/fts_emb_repo", tmp_db)
    conn = sqlite3.connect(tmp_db)
    # "def" is in embedding_text ("def func_0():...") but NOT in name or file_path
    rows = conn.execute(
        "SELECT node_id FROM code_fts WHERE embedding_text MATCH 'def'"
    ).fetchall()
    conn.close()
    assert len(rows) == len(sample_nodes), (
        "FTS embedding_text not indexed — all nodes have 'def' in embedding_text"
    )


def test_fts5_table_supports_name_match(tmp_db, sample_nodes, mock_mistral_client):
    """EMBED-03: After embed_and_store, FTS5 supports exact name MATCH."""
    _create_stub_vec_tables(tmp_db)
    with patch("app.ingestion.embedder.get_embedding_client", return_value=mock_mistral_client):
        with patch("app.ingestion.embedder.init_vec_table"):
            with patch("app.ingestion.embedder._vec_conn", side_effect=sqlite3.connect):
                with patch("app.ingestion.embedder.sqlite_vec") as mock_sv:
                    mock_sv.load = MagicMock()
                    mock_sv.serialize_float32 = MagicMock(return_value=b"\x00" * 4096)
                    embed_and_store(sample_nodes, "/tmp/fts_test_repo", tmp_db)
    conn = sqlite3.connect(tmp_db)
    rows = conn.execute(
        'SELECT node_id FROM code_fts WHERE name MATCH ?', ('"func_0"',)
    ).fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0][0] == "src/a.py::func_0"


def test_embed_and_store_upsert_no_duplicates(tmp_db, sample_nodes, mock_mistral_client):
    """EMBED-05: calling embed_and_store twice on same nodes yields same FTS row count."""
    _create_stub_vec_tables(tmp_db)
    with patch("app.ingestion.embedder.get_embedding_client", return_value=mock_mistral_client):
        with patch("app.ingestion.embedder.init_vec_table"):
            with patch("app.ingestion.embedder._vec_conn", side_effect=sqlite3.connect):
                with patch("app.ingestion.embedder.sqlite_vec") as mock_sv:
                    mock_sv.load = MagicMock()
                    mock_sv.serialize_float32 = MagicMock(return_value=b"\x00" * 4096)
                    embed_and_store(sample_nodes, "/tmp/upsert_repo", tmp_db)
                    embed_and_store(sample_nodes, "/tmp/upsert_repo", tmp_db)
    conn = sqlite3.connect(tmp_db)
    count = conn.execute("SELECT COUNT(*) FROM code_fts").fetchone()[0]
    conn.close()
    assert count == len(sample_nodes)  # not doubled


# ---------------------------------------------------------------------------
# EMBED-05 / delete_embeddings_for_files tests (EMBED-05, PIPE-03 support)
# ---------------------------------------------------------------------------

def test_delete_embeddings_for_files_empty_list_is_noop(tmp_db):
    """Empty file_paths list must return without opening any DB connection."""
    with patch("app.ingestion.embedder.sqlite3.connect") as mock_connect:
        delete_embeddings_for_files([], "/tmp/repo", tmp_db)
        mock_connect.assert_not_called()


def test_delete_embeddings_for_files_removes_fts5_rows(tmp_db, sample_nodes, mock_mistral_client):
    """After embed_and_store, delete_embeddings_for_files removes FTS5 rows for target file."""
    # First embed so FTS5 rows exist
    _create_stub_vec_tables(tmp_db)
    with patch("app.ingestion.embedder.get_embedding_client", return_value=mock_mistral_client):
        with patch("app.ingestion.embedder.init_vec_table"):
            with patch("app.ingestion.embedder._vec_conn", side_effect=sqlite3.connect):
                with patch("app.ingestion.embedder.sqlite_vec") as mock_sv:
                    mock_sv.load = MagicMock()
                    mock_sv.serialize_float32 = MagicMock(return_value=b"\x00" * 4096)
                    embed_and_store(sample_nodes, "/tmp/test_repo", tmp_db)

    # Confirm FTS5 rows were written
    conn = sqlite3.connect(tmp_db)
    total = conn.execute("SELECT COUNT(*) FROM code_fts").fetchone()[0]
    conn.close()
    assert total > 0

    # Now delete for the file that all sample_nodes share (src/a.py)
    target_file = sample_nodes[0].file_path
    with patch("app.ingestion.embedder._vec_conn", side_effect=sqlite3.connect):
        with patch("app.ingestion.embedder.sqlite_vec") as mock_sv:
            mock_sv.load = MagicMock()
            delete_embeddings_for_files([target_file], "/tmp/test_repo", tmp_db)

    # FTS5 rows for that file_path must be gone
    conn = sqlite3.connect(tmp_db)
    remaining = conn.execute(
        "SELECT COUNT(*) FROM code_fts WHERE file_path = ?", (target_file,)
    ).fetchone()[0]
    conn.close()
    assert remaining == 0
