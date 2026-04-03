"""Cross-encoder reranker for the improved RAG pipeline.

Uses cross-encoder/ms-marco-MiniLM-L-6-v2 (66 MB) — a model that jointly attends
to (query, document) pairs. Cross-encoders are significantly more accurate than
bi-encoder cosine similarity for relevance discrimination because they see both
inputs simultaneously rather than encoding them separately.

The model is lazy-loaded on first call and cached module-level.
It runs on CPU in ~100ms for 15 candidates — acceptable for a dev tool.
"""

from __future__ import annotations

import logging

import numpy as np
from sentence_transformers import CrossEncoder

from app.models.schemas import CodeNode

logger = logging.getLogger(__name__)

_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_reranker = None


def _get_reranker():
    """Lazy-load the CrossEncoder model; cached after first call."""
    global _reranker
    if _reranker is None:
        logger.info("Loading cross-encoder model %s (first call)", _MODEL_NAME)
        _reranker = CrossEncoder(_MODEL_NAME)
    return _reranker


def cross_encode_rerank(
    query: str,
    scored: list[tuple[float, CodeNode]],
    top_n: int,
) -> list[tuple[float, CodeNode]]:
    """Rerank a scored candidate pool using a cross-encoder model.

    The cross-encoder jointly reads (query, context_text) for each node and
    produces a relevance score more accurate than bi-encoder cosine similarity.
    Applied after rerank_and_assemble over the 2×max_nodes candidate pool.

    Args:
        query:   Original user query string.
        scored:  Pre-scored (score, CodeNode) list from rerank_and_assemble.
        top_n:   Number of (ce_score, CodeNode) pairs to return.

    Returns:
        Top top_n (cross_encoder_score, CodeNode) tuples sorted descending.
        Empty list if scored is empty (model not called).
    """
    if not scored:
        return []

    reranker = _get_reranker()
    pairs = [
        (
            query,
            f"{n.file_path}:{n.line_start}-{n.line_end}\n"
            f"{n.signature or ''}\n{n.docstring or ''}\n{n.body_preview or ''}",
        )
        for _, n in scored
    ]

    ce_scores: np.ndarray = reranker.predict(pairs)
    reranked = sorted(
        zip(ce_scores.tolist(), [n for _, n in scored]),
        key=lambda x: x[0],
        reverse=True,
    )
    return reranked[:top_n]
