"""Reviewer Agent — graph-grounded code review for the V2 multi-agent pipeline.

Exposes:
  - Finding       Pydantic model (severity, category, description, file_path,
                  line_start, line_end, suggestion)
  - ReviewResult  Pydantic model (findings, retrieved_nodes, summary)
  - review(question, G, target_node_id, selected_file=None,
           selected_range=None, settings=None) -> ReviewResult

Algorithm:
  1. Assemble 1-hop context: target node + CALLS-edge predecessors + successors.
  2. Build prompt, optionally augmented with selected_file / selected_range.
  3. Call LLM with with_structured_output(ReviewResult) for schema-validated output.
  4. Post-filter findings: drop any Finding whose file_path is not in retrieved context.
  5. Return ReviewResult with validated findings, retrieved_nodes, and summary.

Critical: get_llm() and get_settings() are imported INSIDE review() body —
never at module level. This prevents ValidationError during pytest collection
when API keys are absent.
"""
from __future__ import annotations

from typing import Literal

import networkx as nx
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Constants — safe at import time (no get_llm() / get_settings() here)
# ---------------------------------------------------------------------------

REVIEWER_SYSTEM = """You are a senior code reviewer. Given a target function and its
1-hop callers and callees from the call graph, generate structured code review findings.

For each issue found, produce a Finding with:
  severity: "critical" | "warning" | "info"
  category: one of "security", "error-handling", "performance", "style", "correctness"
  description: what the problem is
  file_path: MUST be one of the files listed in the context block below
  line_start: starting line number (integer)
  line_end: ending line number (integer)
  suggestion: concrete fix recommendation

CRITICAL: file_path must ONLY reference files explicitly listed in the context.
Do NOT hallucinate file paths or function names not present in the context.{range_clause}"""

REVIEWER_PROMPT = ChatPromptTemplate.from_messages([
    ("system", REVIEWER_SYSTEM),
    ("human", "Review request: {question}\n\nContext nodes:\n{context_text}"),
])


# ---------------------------------------------------------------------------
# Pydantic output models
# ---------------------------------------------------------------------------

class Finding(BaseModel):
    """A single structured code review finding."""

    severity: Literal["critical", "warning", "info"]
    category: str
    description: str
    file_path: str
    line_start: int
    line_end: int
    suggestion: str


class ReviewResult(BaseModel):
    """Complete review result from a single review() call."""

    findings: list[Finding]
    retrieved_nodes: list[str]   # node_ids assembled into context
    summary: str                 # LLM narrative summary


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _assemble_context(G: nx.DiGraph, target_id: str) -> tuple[list[str], set[str]]:
    """Return (ordered node_id list, retrieved_nodes set) for target + 1-hop CALLS neighbors.

    Raises ValueError if target_id is not in G.
    """
    if target_id not in G:
        raise ValueError(f"target_node_id {target_id!r} not found in graph")

    nodes = [target_id]
    callers = [
        pred for pred in G.predecessors(target_id)
        if G.edges[pred, target_id].get("type") == "CALLS"
    ]
    callees = [
        succ for succ in G.successors(target_id)
        if G.edges[target_id, succ].get("type") == "CALLS"
    ]
    nodes.extend(callers)
    nodes.extend(callees)
    return nodes, set(nodes)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def review(
    question: str,
    G: nx.DiGraph,
    target_node_id: str,
    selected_file: str | None = None,
    selected_range: tuple[int, int] | None = None,
    settings=None,
) -> ReviewResult:
    """Assemble graph context and generate structured code review findings.

    Args:
        question: Natural-language review request.
        G: Project call graph (NetworkX DiGraph with CALLS-typed edges).
        target_node_id: The function being reviewed (must exist in G).
        selected_file: Optional file the user has selected in the editor.
        selected_range: Optional (line_start, line_end) selected by the user.
        settings: Optional Settings instance; lazy-loaded from app.config if None.

    Returns:
        ReviewResult with validated findings, retrieved_nodes, and summary.
    """
    # Step 1: Settings (lazy import)
    if settings is None:
        from app.config import get_settings  # noqa: PLC0415
        settings = get_settings()
    # reviewer_context_hops is read for future N-hop expansion; currently always 1
    _ = settings.reviewer_context_hops

    # Step 2: Assemble 1-hop context
    node_ids, retrieved_nodes = _assemble_context(G, target_node_id)

    # Step 3: Build context text for the prompt (list files available)
    context_lines = []
    for nid in node_ids:
        if nid not in G:
            continue
        attrs = G.nodes[nid]
        role = "TARGET" if nid == target_node_id else (
            "CALLER" if nid in [
                p for p in G.predecessors(target_node_id)
                if G.edges[p, target_node_id].get("type") == "CALLS"
            ] else "CALLEE"
        )
        context_lines.append(
            f"[{role}] {nid} | file={attrs.get('file_path', '')} "
            f"lines={attrs.get('line_start', 0)}-{attrs.get('line_end', 0)} "
            f"name={attrs.get('name', '')}"
        )
    context_text = "\n".join(context_lines) or "No context nodes found."

    # Step 4: Range clause for optional selection targeting (REVW-03)
    range_clause = ""
    if selected_file and selected_range:
        range_clause = (
            f"\n\nFOCUS: The user has selected lines {selected_range[0]}\u2013{selected_range[1]} "
            f"of {selected_file}. Target your findings to this range specifically."
        )

    # Step 5: LLM call with structured output (lazy import — CRITICAL: inside function body)
    from app.core.model_factory import get_llm  # noqa: PLC0415
    llm = get_llm()
    structured_llm = llm.with_structured_output(ReviewResult)
    prompt = REVIEWER_PROMPT.partial(range_clause=range_clause)
    chain = prompt | structured_llm
    result: ReviewResult = chain.invoke({
        "question": question,
        "context_text": context_text,
    })

    # Step 6: Groundedness post-filter — drop findings with file_path not in retrieved context
    valid_file_paths = {
        G.nodes[n].get("file_path", "")
        for n in retrieved_nodes
        if n in G
    }
    validated_findings = [f for f in result.findings if f.file_path in valid_file_paths]

    # Step 7: Return with validated data
    return ReviewResult(
        findings=validated_findings,
        retrieved_nodes=list(retrieved_nodes),
        summary=result.summary,
    )
