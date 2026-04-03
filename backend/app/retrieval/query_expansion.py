"""HyDE (Hypothetical Document Embeddings) query expansion.

HyDE bridges the vocabulary gap between natural-language questions and code:
  User query : "How does FastAPI validate path parameters?"
  Embedding  : question tokens are distant from `class Path(Param): assert default is ...`
  HyDE output: "def register_path(item_id: int = Path(gt=0)): ..."
  Embedding  : hypothetical code is near the actual Path implementation

We ask the LLM to generate a short hypothetical code snippet, embed it alongside
the original query, and RRF-merge the result sets. The snippet lives in the same
vector space as real indexed code, dramatically improving recall for questions
where the user vocabulary is far from the code vocabulary.
"""

from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage

from app.core.model_factory import get_llm

logger = logging.getLogger(__name__)

_HYDE_PROMPT = (
    'Write a short Python code snippet (5-15 lines) showing the key implementation '
    'or usage pattern that answers this question about a codebase:\n\n'
    '"{query}"\n\n'
    'Return only Python code. No explanations, no markdown fences.'
)


async def hyde_expand(query: str) -> str:
    """Generate a hypothetical code snippet to improve vector retrieval recall.

    Calls the configured LLM to produce a short code snippet representing an
    idealised answer. The snippet is then embedded and its semantic results are
    merged with the original query results via RRF. Falls back gracefully to
    empty string on any LLM error — the caller continues with original-query
    retrieval only.

    Args:
        query: Natural language question from the user.

    Returns:
        A Python code snippet string, or "" on LLM failure.
    """
    llm = get_llm()
    prompt = _HYDE_PROMPT.format(query=query)
    try:
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        return response.content.strip()
    except Exception as exc:
        logger.warning("HyDE expansion failed (falling back to original query): %s", exc)
        return ""
