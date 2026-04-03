import pytest
import numpy as np
from unittest.mock import MagicMock, patch
from app.models.schemas import CodeNode


def _make_node(name: str, file_path: str = "/repo/a.py") -> CodeNode:
    return CodeNode(
        node_id=f"{file_path}::{name}", name=name, type="function",
        file_path=file_path, line_start=1, line_end=10,
        signature=f"def {name}():", docstring=f"Does {name}.",
        body_preview="pass", complexity=1, embedding_text=f"def {name}():",
    )


@pytest.fixture(autouse=True)
def patch_cross_encoder():
    """Prevent real model download during tests."""
    with patch("app.retrieval.reranker.CrossEncoder") as MockCE:
        instance = MagicMock()
        MockCE.return_value = instance
        yield instance


def test_returns_top_n(patch_cross_encoder):
    from app.retrieval.reranker import cross_encode_rerank

    nodes = [_make_node(f"f{i}") for i in range(5)]
    scored = [(float(i) * 0.1, n) for i, n in enumerate(nodes)]
    patch_cross_encoder.predict.return_value = np.array([0.9, 0.1, 0.8, 0.2, 0.7])

    result = cross_encode_rerank("query", scored, top_n=3)
    assert len(result) == 3


def test_orders_by_ce_score(patch_cross_encoder):
    from app.retrieval.reranker import cross_encode_rerank

    nodes = [_make_node("high"), _make_node("low"), _make_node("mid")]
    scored = [(0.5, n) for n in nodes]
    patch_cross_encoder.predict.return_value = np.array([0.9, 0.1, 0.5])

    result = cross_encode_rerank("query", scored, top_n=3)
    assert [n.name for _, n in result] == ["high", "mid", "low"]


def test_pair_format_contains_query_and_code(patch_cross_encoder):
    from app.retrieval.reranker import cross_encode_rerank

    node = _make_node("my_func")
    scored = [(0.8, node)]
    patch_cross_encoder.predict.return_value = np.array([0.7])

    cross_encode_rerank("my special query", scored, top_n=1)

    pairs = patch_cross_encoder.predict.call_args[0][0]
    query_text, context_text = pairs[0]
    assert query_text == "my special query"
    assert "my_func" in context_text


def test_empty_scored_returns_empty(patch_cross_encoder):
    from app.retrieval.reranker import cross_encode_rerank

    result = cross_encode_rerank("query", [], top_n=5)
    assert result == []
    patch_cross_encoder.predict.assert_not_called()
