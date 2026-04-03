import pytest
import asyncio
import networkx as nx
import numpy as np
from unittest.mock import patch, MagicMock, AsyncMock
from app.models.schemas import CodeNode


@pytest.fixture
def two_node_graph():
    G = nx.DiGraph()
    for nid, name, fp, pr in [
        ("a.py::func_a", "func_a", "/repo/a.py", 0.25),
        ("b.py::func_b", "func_b", "/repo/b.py", 0.30),
    ]:
        G.add_node(nid, node_id=nid, name=name, type="function",
                   file_path=fp, line_start=1, line_end=5,
                   signature=f"def {name}():", docstring="", body_preview="pass",
                   complexity=1, embedding_text=f"def {name}():",
                   pagerank=pr, in_degree=0, out_degree=0)
    G.add_edge("a.py::func_a", "b.py::func_b", type="CALLS")
    return G


@pytest.fixture
def mock_sem_search():
    with patch("app.retrieval.improved_rag.semantic_search") as m:
        m.return_value = [("a.py::func_a", 0.85), ("b.py::func_b", 0.60)]
        yield m


@pytest.fixture
def mock_fts():
    with patch("app.retrieval.improved_rag.fts_search") as m:
        m.return_value = [("a.py::func_a", 0.80)]
        yield m


@pytest.fixture
def mock_hyde():
    with patch("app.retrieval.improved_rag.hyde_expand", new_callable=AsyncMock) as m:
        m.return_value = "def func_a(): ..."
        yield m


@pytest.fixture
def mock_ce():
    with patch("app.retrieval.improved_rag.cross_encode_rerank") as m:
        m.side_effect = lambda q, scored, top_n: scored[:top_n]
        yield m


@pytest.mark.asyncio
async def test_returns_codenodes(two_node_graph, mock_sem_search, mock_fts, mock_hyde, mock_ce):
    from app.retrieval.improved_rag import improved_graph_rag_retrieve
    nodes, stats = await improved_graph_rag_retrieve(
        "how does func_a work", "/repo", two_node_graph, "/fake/db.sqlite", max_nodes=2
    )
    assert isinstance(nodes, list)
    assert all(isinstance(n, CodeNode) for n in nodes)


@pytest.mark.asyncio
async def test_stats_has_required_keys(two_node_graph, mock_sem_search, mock_fts, mock_hyde, mock_ce):
    from app.retrieval.improved_rag import improved_graph_rag_retrieve
    _, stats = await improved_graph_rag_retrieve(
        "test", "/repo", two_node_graph, "/fake/db.sqlite", max_nodes=2
    )
    for key in ("seed_count", "semantic_seeds", "fts_seeds", "hyde_used",
                "expanded_count", "returned_count", "hop_depth", "strong_bfs_seeds"):
        assert key in stats, f"Missing: {key}"


@pytest.mark.asyncio
async def test_hyde_disabled_does_not_call_expand(two_node_graph, mock_sem_search, mock_fts, mock_hyde, mock_ce):
    from app.retrieval.improved_rag import improved_graph_rag_retrieve
    _, stats = await improved_graph_rag_retrieve(
        "test", "/repo", two_node_graph, "/fake/db.sqlite", max_nodes=2, use_hyde=False
    )
    assert stats["hyde_used"] is False
    mock_hyde.assert_not_called()


@pytest.mark.asyncio
async def test_bfs_threshold_limits_expansion(two_node_graph, mock_fts, mock_hyde, mock_ce):
    from app.retrieval.improved_rag import improved_graph_rag_retrieve
    # Only func_a has score above threshold; func_b is weak
    with patch("app.retrieval.improved_rag.semantic_search") as m:
        m.return_value = [("a.py::func_a", 0.90), ("b.py::func_b", 0.10)]
        _, stats = await improved_graph_rag_retrieve(
            "test", "/repo", two_node_graph, "/fake/db.sqlite",
            max_nodes=2, bfs_score_threshold=0.45
        )
    # Only func_a is strong enough for BFS; func_b added directly
    assert stats["strong_bfs_seeds"] == 1


@pytest.mark.asyncio
async def test_cross_encoder_disabled_falls_back_to_mmr(two_node_graph, mock_sem_search, mock_fts, mock_hyde, mock_ce):
    from app.retrieval.improved_rag import improved_graph_rag_retrieve
    nodes, _ = await improved_graph_rag_retrieve(
        "test", "/repo", two_node_graph, "/fake/db.sqlite",
        max_nodes=2, use_cross_encoder=False
    )
    mock_ce.assert_not_called()
    assert isinstance(nodes, list)
