"""Explorer Agent — LangChain LCEL streaming chain (Phase 9).

Exposes:
  - format_context_block(nodes) -> str   (pure, AGNT-05)
  - explore_stream(nodes, question)       (async generator, AGNT-01/03/04)
"""
from __future__ import annotations

from typing import AsyncGenerator

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tracers.context import tracing_v2_enabled

from app.agent.prompts import SYSTEM_PROMPT
from app.config import get_settings
from app.core.model_factory import get_llm
from app.models.schemas import CodeNode

# Module-level sentinel — chain is built lazily to avoid ValidationError
# when OPENAI_API_KEY is absent (e.g., during test collection).
# Reset to None whenever the prompt template changes to force a rebuild.
_chain = None


def _get_chain():
    """Return cached LCEL chain; build on first call (lazy init pattern)."""
    global _chain
    if _chain is None:
        llm = get_llm()
        prompt = ChatPromptTemplate.from_messages([
            ("system", "{system_prompt}"),
            ("human", "Context:\n{context}\n\nQuestion: {question}"),
        ])
        _chain = prompt | llm
    return _chain


def format_context_block(nodes: list[CodeNode]) -> str:
    """Format CodeNodes into the PRD-specified context string (AGNT-05).

    Format per node:
      --- [file_path:line_start-line_end] name (type) ---
      {signature}
      {docstring}
      {full_body if populated, else body_preview}
    """
    blocks = []
    for node in nodes:
        header = (
            f"--- [{node.file_path}:{node.line_start}-{node.line_end}]"
            f" {node.name} ({node.type}) ---"
        )
        code_body = node.full_body if node.full_body else node.body_preview
        parts = filter(None, [node.signature, node.docstring or "", code_body])
        body = "\n".join(parts)
        blocks.append(f"{header}\n{body}")
    return "\n\n".join(blocks)


async def explore_stream(
    nodes: list[CodeNode],
    question: str,
    project_name: str = "nexus-v1",
) -> AsyncGenerator[str, None]:
    """Stream answer tokens grounded in retrieved CodeNode context.

    Uses tracing_v2_enabled to record each invocation in LangSmith.
    LANGCHAIN_TRACING_V2=true in .env activates LangSmith globally;
    the context manager provides per-call scoping (AGNT-04).

    Yields:
        str: Individual non-empty token strings from the LLM.
    """
    chain = _get_chain()
    input_dict = {
        "system_prompt": SYSTEM_PROMPT,
        "context": format_context_block(nodes),
        "question": question,
    }
    with tracing_v2_enabled(project_name=project_name):
        async for chunk in chain.astream(input_dict):
            if chunk.content:   # skip empty first chunk (always empty)
                yield chunk.content
