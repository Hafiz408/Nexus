"""Debugger Agent — graph-traversal bug locator for the V2 multi-agent pipeline.

Exposes:
  - SuspectNode     Pydantic model (node_id, file_path, line_start, anomaly_score, reasoning)
  - DebugResult     Pydantic model (suspects, traversal_path, impact_radius, diagnosis)
  - debug(question, G, settings=None) -> DebugResult

Algorithm:
  1. Find entry nodes whose function name appears in the bug description.
  2. BFS forward along CALLS edges up to max_hops (default 4).
  3. Score each visited node with a deterministic 5-factor formula.
  4. Return top-5 suspects ranked by anomaly_score descending.
  5. Compute impact_radius (direct callers of top suspect).
  6. Call LLM to generate a grounded diagnosis narrative.

Critical: get_llm() and get_settings() are imported INSIDE debug() body —
never at module level. This prevents ValidationError during pytest collection
when API keys are absent.
"""
from __future__ import annotations

import re
from collections import deque
from typing import Literal

import networkx as nx
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Constants — safe at import time (no get_llm() / get_settings() here)
# ---------------------------------------------------------------------------

ERROR_KEYWORDS = frozenset({"try", "except", "raise", "catch", "throw", "error", "exception"})

DEBUGGER_SYSTEM = """You are a code debugging assistant. Given a bug description and a list
of suspect functions with anomaly scores, generate a concise diagnosis narrative (2-4 sentences).

CRITICAL: Only mention function names from this list: {traversal_names}
Do NOT hallucinate function names not in this list."""

DEBUGGER_PROMPT = ChatPromptTemplate.from_messages([
    ("system", DEBUGGER_SYSTEM),
    ("human", "Bug: {question}\n\nSuspects (ranked by anomaly score):\n{suspects_text}"),
])


# ---------------------------------------------------------------------------
# Pydantic output models
# ---------------------------------------------------------------------------

class SuspectNode(BaseModel):
    """A single suspect function node with its anomaly score."""

    node_id: str
    file_path: str
    line_start: int
    anomaly_score: float = Field(ge=0.0, le=1.0)
    reasoning: str


class DebugResult(BaseModel):
    """Complete debugging result from a single debug() call."""

    suspects: list[SuspectNode]           # ranked by anomaly_score desc, max 5
    traversal_path: list[str]             # node_ids visited in BFS order
    impact_radius: list[str]              # node_ids that directly call the top suspect
    diagnosis: str                        # LLM-generated narrative


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _find_entry_nodes(question: str, G: nx.DiGraph) -> list[str]:
    """Return node_ids whose 'name' attribute appears in the lowercased question.

    Never raises. Returns empty list if no match — caller handles fallback.
    """
    question_lower = question.lower()
    matches: list[str] = []
    for node_id in G.nodes():
        name = G.nodes[node_id].get("name", "")
        if name and name.lower() in question_lower:
            matches.append(node_id)
    return matches


def _forward_bfs(G: nx.DiGraph, entry_id: str, max_hops: int) -> list[str]:
    """BFS forward along CALLS edges starting at entry_id.

    Includes the entry node itself (depth 0) so isolated entry nodes still
    appear as suspects. Stops expanding at depth >= max_hops.

    Args:
        G: The project call graph.
        entry_id: Starting node for BFS.
        max_hops: Maximum traversal depth (inclusive of entry at depth 0).

    Returns:
        List of node_ids in BFS order, entry node first.
    """
    queue: deque[tuple[str, int]] = deque([(entry_id, 0)])
    seen: set[str] = {entry_id}
    visited: list[str] = []

    while queue:
        node_id, depth = queue.popleft()
        visited.append(node_id)  # include all depths (entry at 0)

        if depth >= max_hops:
            continue

        for _, neighbour, edge_data in G.out_edges(node_id, data=True):
            if edge_data.get("type") == "CALLS" and neighbour not in seen:
                seen.add(neighbour)
                queue.append((neighbour, depth + 1))

    return visited


def _score_node(attrs: dict, question_tokens: set[str]) -> float:
    """Deterministic 5-factor anomaly score for a single graph node.

    Factors and weights:
      0.30 — complexity      (cyclomatic / 10, clamped)
      0.25 — error absence   (1.0 if no error-handling keywords in body)
      0.20 — keyword match   (overlap of question tokens with body tokens)
      0.15 — out-degree      (coupling: out_degree / 10, clamped)
      0.10 — inverted PR     (less-central nodes score higher)

    Each factor is individually clamped to [0.0, 1.0] before weighting.
    Final score is clamped to [0.0, 1.0].
    """
    # Factor 1: complexity
    f1 = min(attrs.get("complexity", 1) / 10.0, 1.0)

    # Factor 2: absence of error handling
    body_lower = (
        (attrs.get("body_preview") or "") + " " + (attrs.get("docstring") or "")
    ).lower()
    f2 = 0.0 if any(kw in body_lower for kw in ERROR_KEYWORDS) else 1.0

    # Factor 3: keyword overlap with question
    body_tokens = set(re.findall(r"\w+", body_lower))
    overlap = len(question_tokens & body_tokens)
    f3 = min(overlap / max(len(question_tokens), 1), 1.0)

    # Factor 4: out-degree coupling
    f4 = min(attrs.get("out_degree", 0) / 10.0, 1.0)

    # Factor 5: inverted PageRank (low-centrality nodes are more suspect)
    pagerank = attrs.get("pagerank", 0.0)
    f5 = 1.0 - min(pagerank * 5.0, 1.0)

    score = 0.30 * f1 + 0.25 * f2 + 0.20 * f3 + 0.15 * f4 + 0.10 * f5
    return min(max(score, 0.0), 1.0)


def _build_reasoning(attrs: dict, score: float, question_tokens: set[str]) -> str:  # noqa: ARG001
    """One-sentence human-readable reasoning for a suspect node."""
    complexity = attrs.get("complexity", 1)
    body_lower = (
        (attrs.get("body_preview") or "") + " " + (attrs.get("docstring") or "")
    ).lower()
    has_error_handling = any(kw in body_lower for kw in ERROR_KEYWORDS)
    err_str = "no error handling" if not has_error_handling else "has error handling"
    return (
        f"complexity={complexity}, {err_str}, anomaly_score={score:.2f}"
    )


def _impact_radius(G: nx.DiGraph, top_suspect_id: str) -> list[str]:
    """Return node_ids that directly call top_suspect_id via CALLS edges."""
    return [
        pred
        for pred in G.predecessors(top_suspect_id)
        if G.edges[pred, top_suspect_id].get("type") == "CALLS"
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def debug(question: str, G: nx.DiGraph, settings=None) -> DebugResult:
    """Traverse the call graph forward from the bug entry point and rank suspects.

    Steps:
      1. Discover entry nodes whose name appears in the question.
      2. BFS forward along CALLS edges up to max_hops.
      3. Score each visited node with _score_node().
      4. Rank top-5 by anomaly_score descending.
      5. Compute impact_radius for the top suspect.
      6. Generate an LLM diagnosis narrative grounded in traversed function names.

    Args:
        question: Natural-language bug description.
        G: Project call graph (NetworkX DiGraph with CALLS-typed edges).
        settings: Optional Settings instance; lazy-loaded from app.config if None.

    Returns:
        DebugResult with suspects, traversal_path, impact_radius, and diagnosis.
    """
    # Step 1: Settings (lazy import — keeps module importable without API key)
    if settings is None:
        from app.config import get_settings  # noqa: PLC0415
        settings = get_settings()
    max_hops: int = settings.debugger_max_hops

    # Step 2: Entry node discovery
    entry_nodes = _find_entry_nodes(question, G)
    if not entry_nodes and G.number_of_nodes() > 0:
        # Fallback: node with highest in_degree (most-called); ties broken by sort
        entry_nodes = [max(G.nodes(), key=lambda n: G.nodes[n].get("in_degree", 0))]

    # Step 3: Forward BFS traversal across all entry nodes
    traversal: list[str] = []
    for entry in entry_nodes:
        traversal.extend(_forward_bfs(G, entry, max_hops))
    traversal = list(dict.fromkeys(traversal))  # deduplicate, preserve BFS order

    # Step 4: Score each visited node
    question_tokens = set(re.findall(r"\w+", question.lower()))
    scored: list[tuple[str, float, dict]] = []
    for node_id in traversal:
        if node_id not in G:
            continue
        attrs = dict(G.nodes[node_id])
        score = _score_node(attrs, question_tokens)
        scored.append((node_id, score, attrs))

    # Step 5: Rank top 5
    scored.sort(key=lambda x: x[1], reverse=True)
    top5 = scored[:5]

    # Step 6: Impact radius from top suspect
    impact: list[str] = []
    if top5:
        impact = _impact_radius(G, top5[0][0])

    # Step 7: Build SuspectNode list
    suspects = [
        SuspectNode(
            node_id=nid,
            file_path=attrs.get("file_path", ""),
            line_start=int(attrs.get("line_start", 0)),
            anomaly_score=score,
            reasoning=_build_reasoning(attrs, score, question_tokens),
        )
        for nid, score, attrs in top5
    ]

    # Step 8: LLM diagnosis narrative (lazy import — CRITICAL: inside function body)
    from app.core.model_factory import get_llm  # noqa: PLC0415

    llm = get_llm()
    traversal_names = [G.nodes[n].get("name", n) for n in traversal if n in G]
    suspects_text = "\n".join(
        f"{i + 1}. {s.node_id} (score={s.anomaly_score:.2f}): {s.reasoning}"
        for i, s in enumerate(suspects)
    ) or "No suspects identified."
    prompt = DEBUGGER_PROMPT.partial(traversal_names=", ".join(traversal_names) or "none")
    chain = prompt | llm
    response = chain.invoke({"question": question, "suspects_text": suspects_text})
    raw_content = response.content if hasattr(response, "content") else response
    diagnosis = raw_content if isinstance(raw_content, str) else str(raw_content)

    # Step 9: Return
    return DebugResult(
        suspects=suspects,
        traversal_path=traversal,
        impact_radius=impact,
        diagnosis=diagnosis,
    )
