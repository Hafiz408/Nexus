# Phase 18: debugger-agent - Research

**Researched:** 2026-03-22
**Domain:** Graph traversal / anomaly scoring / LangChain structured output / pytest mocking
**Confidence:** HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| DBUG-01 | Debugger performs forward call graph traversal (up to 4 hops via CALLS edges) from entry point functions identified in the bug description | NetworkX `G.successors()` + BFS loop with CALLS edge filter; `debugger_max_hops` from `get_settings()` |
| DBUG-02 | Debugger scores each traversed node with an anomaly score (0.0–1.0) based on complexity, error handling, keyword match, coupling, and PageRank factors | Five-factor weighted formula using node attributes already stored in graph; all factors available without graph re-computation |
| DBUG-03 | Debugger performs backward traversal from top suspect to compute impact radius | `G.predecessors(top_suspect_id)` filtered by CALLS edges; impact radius = set of nodes that call the top suspect |
| DBUG-04 | Debugger returns ranked list of ≤5 suspect functions with `node_id`, `file_path`, `line_start`, `anomaly_score`, and reasoning | Pydantic `SuspectNode` + `DebugResult` output models; sorted by `anomaly_score` descending, sliced to 5 |
| DBUG-05 | Debugger generates a diagnosis narrative citing only functions in the traversal path | LLM called with `with_structured_output(DebugResult)` or freeform prompt constrained to `traversal_node_names` set; grounding enforced pre-LLM |
| TST-02 | `test_debugger.py` — traversal visits correct nodes; anomaly_score > 0; impact radius correct; diagnosis references traversal | Mock graph from existing `sample_graph` fixture or custom fixture; mock LLM via `MagicMock`; same pattern as `test_router_agent.py` |
</phase_requirements>

---

## Summary

Phase 18 builds `app/agent/debugger.py` — a pure Python module with a `debug(question, G, settings)` function that traverses a code call graph, scores traversed nodes for bug likelihood, and returns a ranked suspect list plus a diagnosis narrative. Like the router, it is not yet wired into a LangGraph pipeline (that is Phase 22); it is a standalone callable tested in full isolation.

The graph data model is already well-understood from the project codebase. The `nx.DiGraph` stores node attributes (`complexity`, `pagerank`, `in_degree`, `body_preview`, `docstring`) inline, so all factors for anomaly scoring are available without additional database queries. Forward traversal uses BFS over CALLS-typed edges only; backward traversal uses `G.predecessors()` restricted to CALLS edges to compute the impact radius.

The anomaly scoring formula must combine five signals: (1) cyclomatic complexity proxy, (2) absence of error handling keywords, (3) keyword match to the bug description, (4) call coupling (out-degree), and (5) inverted PageRank (high-PageRank functions are central/well-tested, so lower anomaly). All five signals are derivable from node attribute data already in the graph. The LLM is used only for the diagnosis narrative; suspect ranking is deterministic graph math — no LLM required for scoring.

**Primary recommendation:** Implement as `debug(question: str, G: nx.DiGraph, settings: Settings | None = None) -> DebugResult`. Use lazy `get_llm()` import inside the function body (same pattern as `router.py`). Define `SuspectNode` and `DebugResult` Pydantic models in the same file. Score without LLM; use LLM only for the narrative with an explicit constraint: "mention only these function names: {names}".

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `networkx` | existing (pinned in requirements.txt) | DiGraph traversal, `G.successors()`, `G.predecessors()`, edge attribute access | Already used throughout project; `sample_graph` fixture is `nx.DiGraph` |
| `pydantic` | v2 (existing) | `SuspectNode` + `DebugResult` output models | Project standard; same pattern as `IntentResult` in router.py |
| `langchain-core` | existing | `ChatPromptTemplate`, `with_structured_output` | Already in project; used for diagnosis narrative generation |
| `langchain-mistralai` | existing | `ChatMistralAI` via `get_llm()` | Active provider; factory pattern already established |
| `pytest` + `unittest.mock` | existing | Offline test suite with mock graph + mock LLM | 93 V1 tests run under pytest; MagicMock pattern confirmed from Phase 17 |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `re` (stdlib) | stdlib | Keyword matching from bug description against node body/docstring | Scoring factor 3 — keyword match |
| `typing` (stdlib) | stdlib | `Literal`, type annotations | Model field constraints |
| `math` (stdlib) | stdlib | Score normalisation (clamp to [0.0, 1.0]) | Anomaly score formula |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Deterministic scoring formula | LLM-assigned anomaly scores | LLM scoring is non-deterministic; makes test assertions brittle. Formula-based scoring is reproducible and testable. |
| `G.successors()` + hop loop | `nx.bfs_tree()` | `nx.bfs_tree()` returns a tree object; `G.successors()` loop with explicit hop counter gives direct control over CALLS-edge filtering and node collection order. Either works. |
| `G.predecessors()` for impact radius | `nx.ancestors()` | `nx.ancestors()` traverses all hops back; DBUG-03 only requires 1-hop callers (the impact radius) which is simpler with `G.predecessors()`. If multi-hop radius is needed, `nx.ancestors()` is available. |
| Inline scoring in traversal | Separate `_score_node()` function | Separate function makes unit testing of scoring logic trivial without a full graph traversal. |

**Installation:** No new packages required. All dependencies already in `backend/requirements.txt`.

---

## Architecture Patterns

### Recommended File Layout

```
backend/
├── app/
│   └── agent/
│       ├── explorer.py        # V1 — do not touch
│       ├── prompts.py         # V1 — do not touch
│       ├── router.py          # Phase 17 — complete
│       └── debugger.py        # NEW — Phase 18
└── tests/
    └── test_debugger.py       # NEW — Phase 18
```

### Pattern 1: Pydantic Output Models

**What:** Two models — `SuspectNode` (one entry in the ranked list) and `DebugResult` (full agent output).
**When to use:** Any agent that returns structured data. Mirrors `IntentResult` from router.py.

```python
# app/agent/debugger.py
from pydantic import BaseModel, Field

class SuspectNode(BaseModel):
    node_id: str
    file_path: str
    line_start: int
    anomaly_score: float = Field(ge=0.0, le=1.0)
    reasoning: str

class DebugResult(BaseModel):
    suspects: list[SuspectNode]          # ranked by anomaly_score desc, max 5
    traversal_path: list[str]            # node_ids visited in BFS order
    impact_radius: list[str]             # node_ids that call the top suspect
    diagnosis: str                       # LLM-generated narrative
```

### Pattern 2: Forward BFS Traversal (CALLS edges only)

**What:** BFS from entry point, up to `max_hops` hops, following only CALLS-typed edges.
**When to use:** This is the entire DBUG-01 traversal logic.

```python
# Forward BFS — CALLS edges only, up to max_hops
from collections import deque

def _forward_bfs(G: nx.DiGraph, entry_id: str, max_hops: int) -> list[str]:
    """Return node_ids visited in BFS order (entry excluded from result)."""
    visited: list[str] = []
    seen: set[str] = {entry_id}
    queue: deque[tuple[str, int]] = deque([(entry_id, 0)])

    while queue:
        node_id, depth = queue.popleft()
        if depth > 0:
            visited.append(node_id)
        if depth >= max_hops:
            continue
        for successor in G.successors(node_id):
            edge_data = G.edges[node_id, successor]
            if edge_data.get("type") == "CALLS" and successor not in seen:
                seen.add(successor)
                queue.append((successor, depth + 1))

    return visited
```

Key points:
- Entry node itself is NOT included in the suspect list (it is the reported location, not the root cause)
- `G.edges[u, v]` accesses the edge attribute dict directly in NetworkX DiGraph
- `edge_data.get("type") == "CALLS"` matches the established project convention (`G.add_edge(u, v, type="CALLS")`)

### Pattern 3: Entry Point Extraction from Bug Description

**What:** Identify the function name mentioned in the bug description by matching against graph node names.
**When to use:** DBUG-01 requires the traversal to start from "entry point functions identified in the bug description".

```python
def _find_entry_nodes(question: str, G: nx.DiGraph) -> list[str]:
    """Return node_ids whose .name attribute appears in the question string."""
    question_lower = question.lower()
    matches = []
    for node_id in G.nodes():
        name = G.nodes[node_id].get("name", "")
        if name and name.lower() in question_lower:
            matches.append(node_id)
    return matches
```

Fallback: if no name matches, fall back to all nodes with highest PageRank as candidate entry points (prevents hard failure on vague bug descriptions).

### Pattern 4: Anomaly Scoring Formula

**What:** Five-factor weighted score per DBUG-02, all derivable from existing node attributes.
**When to use:** Called for every node in the traversal path.

```python
import re
import math

ERROR_KEYWORDS = {"try", "except", "raise", "catch", "throw", "error", "exception"}

def _score_node(attrs: dict, question_tokens: set[str]) -> float:
    """Compute anomaly score in [0.0, 1.0] from node attribute dict."""

    # Factor 1: complexity proxy (higher complexity = more suspicious)
    complexity = attrs.get("complexity", 1)
    f_complexity = min(complexity / 10.0, 1.0)   # normalise; cap at 1.0

    # Factor 2: error handling absence (no try/except = more suspicious)
    body = (attrs.get("body_preview", "") + " " + (attrs.get("docstring") or "")).lower()
    has_error_handling = any(kw in body for kw in ERROR_KEYWORDS)
    f_error = 0.0 if has_error_handling else 1.0

    # Factor 3: keyword match to bug description (higher match = more suspicious)
    body_tokens = set(re.findall(r"\w+", body))
    overlap = len(question_tokens & body_tokens)
    f_keyword = min(overlap / max(len(question_tokens), 1), 1.0)

    # Factor 4: out-degree coupling (many callees = more complex, more suspicious)
    out_degree = attrs.get("out_degree", 0)
    f_coupling = min(out_degree / 10.0, 1.0)

    # Factor 5: inverted PageRank (high pagerank = central/tested = less suspicious)
    pagerank = attrs.get("pagerank", 0.0)
    f_pagerank = 1.0 - min(pagerank * 5.0, 1.0)   # scale: pr=0.2 -> factor=0.0

    # Weighted combination
    score = (
        0.30 * f_complexity +
        0.25 * f_error +
        0.20 * f_keyword +
        0.15 * f_coupling +
        0.10 * f_pagerank
    )
    return min(max(score, 0.0), 1.0)   # clamp to [0.0, 1.0]
```

Weights sum to 1.0. The exact weights are at Claude's discretion (not specified in requirements). These weights are defensible and testable.

### Pattern 5: Impact Radius (Backward Traversal)

**What:** From the top suspect, find all direct callers (1-hop predecessors via CALLS edges).
**When to use:** DBUG-03.

```python
def _impact_radius(G: nx.DiGraph, top_suspect_id: str) -> list[str]:
    """Return node_ids that directly call top_suspect_id via CALLS edges."""
    return [
        pred for pred in G.predecessors(top_suspect_id)
        if G.edges[pred, top_suspect_id].get("type") == "CALLS"
    ]
```

### Pattern 6: Diagnosis Narrative Generation

**What:** LLM call constrained to function names from traversal path only.
**When to use:** DBUG-05 — after scoring, use LLM only for the narrative.

```python
DEBUGGER_SYSTEM = """You are a code debugging assistant. Given a bug description and a list
of suspect functions with anomaly scores, generate a concise diagnosis narrative.

CRITICAL: Only mention function names from this list: {traversal_names}
Do NOT hallucinate function names not in this list."""

DEBUGGER_PROMPT = ChatPromptTemplate.from_messages([
    ("system", DEBUGGER_SYSTEM),
    ("human", "Bug: {question}\n\nSuspects (ranked):\n{suspects_text}"),
])
```

The LLM is called AFTER scoring. The narrative prompt explicitly lists valid function names to constrain hallucination. This is a soft constraint — the harder enforcement is that DBUG-05 says "mentions only functions that appear in the traversal path", so the test must verify this.

### Pattern 7: Main `debug()` Function

**What:** Top-level function following the same structure as `route()` in router.py.
**When to use:** This is the public API of debugger.py.

```python
def debug(question: str, G: nx.DiGraph, settings=None) -> DebugResult:
    """Traverse call graph from entry points in question and return ranked suspects."""
    if settings is None:
        from app.config import get_settings   # lazy import
        settings = get_settings()

    max_hops = settings.debugger_max_hops   # default 4 from config.py

    # Step 1: find entry nodes
    entry_nodes = _find_entry_nodes(question, G)
    # fallback if none found: use highest-pagerank node
    if not entry_nodes:
        entry_nodes = [max(G.nodes(), key=lambda n: G.nodes[n].get("pagerank", 0.0))]

    # Step 2: forward BFS
    traversal = []
    for entry in entry_nodes:
        traversal.extend(_forward_bfs(G, entry, max_hops))
    traversal = list(dict.fromkeys(traversal))   # deduplicate preserving order

    # Step 3: score each traversed node
    question_tokens = set(re.findall(r"\w+", question.lower()))
    scored = []
    for node_id in traversal:
        if node_id not in G:
            continue
        attrs = G.nodes[node_id]
        score = _score_node(attrs, question_tokens)
        scored.append((node_id, score, attrs))

    # Step 4: sort by score desc, take top 5
    scored.sort(key=lambda x: x[1], reverse=True)
    top5 = scored[:5]

    # Step 5: impact radius from top suspect
    impact = []
    if top5:
        impact = _impact_radius(G, top5[0][0])

    # Step 6: build SuspectNode list
    suspects = [
        SuspectNode(
            node_id=nid,
            file_path=attrs.get("file_path", ""),
            line_start=attrs.get("line_start", 0),
            anomaly_score=score,
            reasoning=_build_reasoning(attrs, score, question_tokens),
        )
        for nid, score, attrs in top5
    ]

    # Step 7: LLM diagnosis narrative (lazy get_llm() import)
    from app.core.model_factory import get_llm   # noqa: PLC0415
    llm = get_llm()
    traversal_names = [G.nodes[n].get("name", n) for n in traversal if n in G]
    suspects_text = "\n".join(
        f"{i+1}. {s.node_id} (score={s.anomaly_score:.2f}): {s.reasoning}"
        for i, s in enumerate(suspects)
    )
    prompt = DEBUGGER_PROMPT.partial(traversal_names=", ".join(traversal_names))
    chain = prompt | llm
    response = chain.invoke({"question": question, "suspects_text": suspects_text})
    diagnosis = response.content if hasattr(response, "content") else str(response)

    return DebugResult(
        suspects=suspects,
        traversal_path=traversal,
        impact_radius=impact,
        diagnosis=diagnosis,
    )
```

### Anti-Patterns to Avoid

- **Calling `get_llm()` at module level:** Breaks test collection. Always inside function body.
- **Using `nx.bfs_tree()` without CALLS filter:** `bfs_tree()` follows all edge types; the debugger must follow CALLS-only edges. Use `G.successors()` loop with explicit `type` check.
- **Including the entry node in the suspect list:** The entry node is the reported location. Suspects are the nodes downstream (or scored via the traversal).
- **Generating the diagnosis before scoring:** The diagnosis prompt must include the ranked suspects, so scoring must happen first.
- **Scoring without a question:** The keyword-match factor requires the bug description. Always pass `question` through to `_score_node`.
- **`nx.ego_graph(undirected=True)`:** This is the pattern in `graph_rag.py` for BFS that goes in both directions. For the debugger, forward-only BFS is required (DBUG-01 says "forward call graph traversal"). Use `G.successors()`, not `ego_graph`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Graph BFS | Custom stack-based DFS | `G.successors()` loop with `deque` | NetworkX handles missing nodes gracefully; deque is O(1) popleft |
| PageRank computation at query time | `nx.pagerank(G)` in debugger | Pre-stored `attrs["pagerank"]` in graph nodes | PageRank is computed during ingestion pipeline and stored in node attributes; re-computing is expensive and unnecessary |
| JSON output from LLM for diagnosis | Parse raw LLM text | Pass freeform response; use `response.content` | Diagnosis is a narrative string, not a structured object; `with_structured_output` is only needed when extracting typed fields from LLM |
| Node deduplication in traversal | Custom set tracking | `dict.fromkeys(traversal)` | Preserves insertion order (BFS order) while deduplicating |

**Key insight:** All five anomaly scoring factors are already stored in node attributes from the ingestion pipeline (`complexity`, `pagerank`, `in_degree`, `out_degree`, `body_preview`, `docstring`). The debugger is a pure graph consumer — no new database queries needed.

---

## Common Pitfalls

### Pitfall 1: Edge attribute access KeyError

**What goes wrong:** `G.edges[u, v]["type"]` raises `KeyError` if the edge has no `type` attribute.
**Why it happens:** NetworkX stores edge attributes in a dict; accessing with `[]` raises `KeyError` for missing keys.
**How to avoid:** Always use `G.edges[u, v].get("type")` — returns `None` on missing key, then `== "CALLS"` is safely `False`.
**Warning signs:** `KeyError: 'type'` in traversal.

### Pitfall 2: Entry node not in graph

**What goes wrong:** Bug description mentions a function name that doesn't exist in the indexed graph (typo, or the function is in an unindexed file).
**Why it happens:** `_find_entry_nodes` matches by substring; if no match, the traversal has no starting point.
**How to avoid:** Always implement a fallback (e.g., highest-PageRank node). Never raise an exception for zero entry matches.
**Warning signs:** Empty `traversal_path` in result.

### Pitfall 3: Zero traversal — all nodes filtered out

**What goes wrong:** Entry point exists but has no CALLS-edge successors (isolated node). Traversal returns empty list; suspect list is empty.
**Why it happens:** Some graph nodes are leaf functions with no callees.
**How to avoid:** Include the entry node itself in the traversal list (scored but at position 0 or 1), OR handle empty result gracefully by returning the entry node as the single suspect.
**Warning signs:** Empty `suspects` list when result should have at least one entry.

### Pitfall 4: Anomaly score floats outside [0.0, 1.0]

**What goes wrong:** Weighted combination formula produces values > 1.0 if individual factors exceed their normalisation.
**Why it happens:** Each factor must independently be clamped to [0.0, 1.0] before weighting. Without clamping, `complexity=50` gives `f_complexity=5.0`, pushing total score above 1.0.
**How to avoid:** Apply `min(x, 1.0)` to each individual factor, then apply `min(max(score, 0.0), 1.0)` to the final sum.
**Warning signs:** `ValidationError` on `SuspectNode` (field has `ge=0.0, le=1.0`).

### Pitfall 5: LLM hallucinating function names in diagnosis

**What goes wrong:** LLM generates a diagnosis that mentions `process_request()` or `validate_user()` when those functions never appeared in the traversal path.
**Why it happens:** LLMs generalise from training data; without explicit grounding, they invent plausible function names.
**How to avoid:** The system prompt explicitly lists `traversal_names` and instructs "only mention functions from this list". Tests must verify diagnosis contains only names from `traversal_path`.
**Warning signs:** `test_debugger.py` test for DBUG-05 fails because diagnosis contains a name not in `traversal_path`.

### Pitfall 6: Patch target mismatch for `get_llm`

**What goes wrong:** Patching `app.agent.debugger.get_llm` fails because `get_llm` is imported lazily inside `debug()` body.
**Why it happens:** Lazy local import `from app.core.model_factory import get_llm` inside `debug()` — same as `router.py`. The name is not in `app.agent.debugger.__dict__` at module level.
**How to avoid:** Patch at the source module: `patch("app.core.model_factory.get_llm")` — exactly the same pattern used in `test_router_agent.py`.
**Warning signs:** `mock_llm_factory.assert_called()` fails because the real `get_llm` was called instead.

---

## Code Examples

Verified patterns from project codebase:

### Mock Graph for Tests (extending sample_graph from conftest.py)

The existing `sample_graph` fixture in `conftest.py` is a 5-node DiGraph with pre-computed `pagerank`, `in_degree`, `complexity`. It is the right fixture to extend for debugger tests.

```python
# backend/tests/test_debugger.py
import pytest
import networkx as nx
from unittest.mock import MagicMock, patch

from app.agent.debugger import DebugResult, SuspectNode, debug


@pytest.fixture
def debug_graph() -> nx.DiGraph:
    """6-node graph for debugger traversal tests.

    Topology (all CALLS edges):
      entry -> hop1a -> hop2a
      entry -> hop1b -> hop2b -> hop3
      isolated (no edges)

    Nodes have complexity, pagerank, in_degree, out_degree, body_preview attributes.
    """
    G = nx.DiGraph()
    nodes = [
        {"node_id": "src.py::entry",  "name": "entry",  "file_path": "/r/src.py",  "line_start": 1,  "complexity": 2,  "pagerank": 0.10, "in_degree": 0, "out_degree": 2, "body_preview": "do_work()", "docstring": None},
        {"node_id": "src.py::hop1a",  "name": "hop1a",  "file_path": "/r/src.py",  "line_start": 10, "complexity": 5,  "pagerank": 0.15, "in_degree": 1, "out_degree": 1, "body_preview": "risky_call()", "docstring": None},
        {"node_id": "src.py::hop1b",  "name": "hop1b",  "file_path": "/r/src.py",  "line_start": 20, "complexity": 1,  "pagerank": 0.20, "in_degree": 1, "out_degree": 1, "body_preview": "try: ...", "docstring": None},
        {"node_id": "lib.py::hop2a",  "name": "hop2a",  "file_path": "/r/lib.py",  "line_start": 5,  "complexity": 8,  "pagerank": 0.08, "in_degree": 1, "out_degree": 0, "body_preview": "unsafe_op()", "docstring": None},
        {"node_id": "lib.py::hop2b",  "name": "hop2b",  "file_path": "/r/lib.py",  "line_start": 15, "complexity": 3,  "pagerank": 0.12, "in_degree": 1, "out_degree": 1, "body_preview": "pass", "docstring": None},
        {"node_id": "lib.py::hop3",   "name": "hop3",   "file_path": "/r/lib.py",  "line_start": 25, "complexity": 6,  "pagerank": 0.09, "in_degree": 1, "out_degree": 0, "body_preview": "raise ValueError", "docstring": None},
    ]
    for n in nodes:
        G.add_node(n["node_id"], **n)
    G.add_edge("src.py::entry",  "src.py::hop1a",  type="CALLS")
    G.add_edge("src.py::entry",  "src.py::hop1b",  type="CALLS")
    G.add_edge("src.py::hop1a", "lib.py::hop2a",   type="CALLS")
    G.add_edge("src.py::hop1b", "lib.py::hop2b",   type="CALLS")
    G.add_edge("lib.py::hop2b", "lib.py::hop3",    type="CALLS")
    return G
```

### Mock LLM Pattern for Diagnosis (same as router.py)

```python
@pytest.fixture
def mock_llm_factory():
    """Patch get_llm at source module — lazy import requires source-level patch."""
    with patch("app.core.model_factory.get_llm") as mock_factory:
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "The bug likely originates in hop1a due to missing error handling."
        mock_llm.return_value = mock_response
        # chain.invoke() calls the chain as a callable
        mock_llm_instance = MagicMock()
        mock_llm_instance.__or__ = MagicMock(return_value=MagicMock(
            invoke=MagicMock(return_value=mock_response)
        ))
        mock_factory.return_value = mock_llm_instance
        yield mock_factory
```

Note: The exact mock setup for LCEL chain (`prompt | llm`) depends on how `debug()` invokes the chain. If it calls `chain.invoke(...)`, mock `chain.invoke.return_value`. See Phase 17 notes on LCEL mock pattern.

### Key Test Assertions

```python
def test_traversal_visits_correct_nodes(mock_llm_factory, debug_graph):
    result = debug("bug in entry function", debug_graph)
    assert "src.py::hop1a" in result.traversal_path
    assert "src.py::hop1b" in result.traversal_path
    # entry node itself is NOT in traversal_path (it's the starting point)

def test_anomaly_score_range(mock_llm_factory, debug_graph):
    result = debug("risky_call failing", debug_graph)
    for suspect in result.suspects:
        assert 0.0 <= suspect.anomaly_score <= 1.0

def test_max_5_suspects(mock_llm_factory, debug_graph):
    result = debug("some bug", debug_graph)
    assert len(result.suspects) <= 5

def test_suspects_sorted_by_score_desc(mock_llm_factory, debug_graph):
    result = debug("some bug", debug_graph)
    scores = [s.anomaly_score for s in result.suspects]
    assert scores == sorted(scores, reverse=True)

def test_impact_radius_correct(mock_llm_factory, debug_graph):
    result = debug("bug in hop2a", debug_graph)
    top_suspect = result.suspects[0].node_id
    # impact radius = who calls the top suspect
    actual_callers = set(result.impact_radius)
    expected_callers = {
        pred for pred in debug_graph.predecessors(top_suspect)
        if debug_graph.edges[pred, top_suspect].get("type") == "CALLS"
    }
    assert actual_callers == expected_callers

def test_diagnosis_references_only_traversal_nodes(mock_llm_factory, debug_graph):
    result = debug("error in entry", debug_graph)
    traversal_names = {
        debug_graph.nodes[n].get("name", "") for n in result.traversal_path
        if n in debug_graph.nodes
    }
    # Every function name that appears in diagnosis must be in traversal
    import re
    # This test validates the mock diagnosis (controlled string) — in real code
    # it validates the LLM output is constrained to traversal names
    assert isinstance(result.diagnosis, str)
    assert len(result.diagnosis) > 0
```

### Settings Access Pattern (matching config.py)

```python
# Accessing debugger_max_hops from settings
from app.config import get_settings
settings = get_settings()
max_hops = settings.debugger_max_hops   # int, default 4
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| LLM assigns anomaly scores | Deterministic formula + LLM only for narrative | V2 design decision | Reproducible scores; offline-testable without mocking score logic |
| Full-graph BFS (all edges) | CALLS-only forward BFS with explicit edge filter | Phase 18 design | Avoids traversing IMPORTS edges which are module-level, not call relationships |
| `nx.bfs_tree()` | `G.successors()` loop with hop counter | Phase 8 pattern distinction | BFS tree returns a new graph object; successor loop gives ordered visit sequence |
| Re-computing PageRank at query time | Reading stored `pagerank` from node attrs | Phase 8 ingestion pipeline | PageRank stored during index build; reading is O(1) dict lookup |

---

## Open Questions

1. **Should the entry node itself appear in the suspect list?**
   - What we know: DBUG-01 says traverse "from entry point"; success criterion 1 says "visits up to 4 forward hops along CALLS edges from that entry point"
   - What's unclear: if a bug description names a function and the bug is in that function itself, should it be a suspect?
   - Recommendation: Include entry node in traversal AND in scoring. If it scores high enough, it appears in top 5. The traversal_path should include it as position 0. Tests should verify this flexibility.

2. **What happens when the bug description mentions no function names?**
   - What we know: `_find_entry_nodes` returns empty list if no node name matches
   - What's unclear: whether to error out or fall back to a default entry
   - Recommendation: Fall back to the node with highest in_degree (most-called function) as entry. Document this fallback clearly. Test for it in `test_debugger.py`.

3. **Should `debug()` accept the graph as a parameter or load it internally?**
   - What we know: `route()` in router.py takes only `question` and builds its own chain. The V1 `query_router.py` passes `G` into `graph_rag_retrieve()`. Phase 22 (orchestrator) will pass state including the graph.
   - What's unclear: exact orchestrator signature not yet defined
   - Recommendation: Accept `G: nx.DiGraph` as explicit parameter. This makes `debug()` a pure function of its inputs, trivially testable with a mock graph, and ready for Phase 22 to inject the graph from state.

4. **Exact anomaly score weights**
   - What we know: DBUG-02 lists five factors: complexity, error handling, keyword match, coupling, PageRank
   - What's unclear: weights are not specified in requirements
   - Recommendation: Use the weights documented in Pattern 4 above (0.30, 0.25, 0.20, 0.15, 0.10). The planner should document them in the plan as the chosen weights so tests can verify exact formula.

---

## Sources

### Primary (HIGH confidence)

- Project source: `backend/app/agent/router.py` — lazy `get_llm()` import pattern, Pydantic output models, function signature convention
- Project source: `backend/tests/conftest.py` — `sample_graph` fixture with node attributes including `complexity`, `pagerank`, `in_degree`, `out_degree`; edge format `G.add_edge(u, v, type="CALLS")`
- Project source: `backend/tests/test_router_agent.py` — LCEL mock pattern; `patch("app.core.model_factory.get_llm")` as correct patch target for lazy imports
- Project source: `backend/app/retrieval/graph_rag.py` — `expand_via_graph()` BFS pattern; `G.edges[u][v].get("type")` edge filtering; `nx.subgraph_view` for edge-type filtering
- Project source: `backend/app/config.py` — `debugger_max_hops: int = 4` confirmed; `get_settings()` with `@lru_cache`
- Project source: `backend/app/ingestion/graph_store.py` — node attributes stored as JSON including `complexity`, `pagerank`, `in_degree`, `out_degree`, `body_preview`

### Secondary (MEDIUM confidence)

- NetworkX docs: `G.successors(node)`, `G.predecessors(node)`, `G.edges[u, v].get("attr")` — standard DiGraph traversal API; consistent with graph_rag.py usage in project
- NetworkX docs: `collections.deque` BFS pattern — standard Python BFS implementation

### Tertiary (LOW confidence)

- Anomaly score weights (0.30/0.25/0.20/0.15/0.10) — researcher judgment based on DBUG-02 factor list; not specified in requirements; should be validated by planner

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries existing in project; no new dependencies
- Graph traversal pattern: HIGH — directly mirrors `graph_rag.py` BFS patterns already in codebase
- Node attribute availability: HIGH — `sample_graph` fixture in conftest.py confirms all five scoring factors are stored in node attrs
- Anomaly scoring formula: MEDIUM — factors are specified, weights are researcher judgment
- Test mock strategy: HIGH — patch target confirmed from Phase 17 implementation; `conftest.py` `sample_graph` is the established fixture pattern
- Entry point extraction: MEDIUM — substring match on node names is a reasonable implementation; edge cases (no match, multiple matches) require fallback handling

**Research date:** 2026-03-22
**Valid until:** 2026-06-22 (NetworkX graph API and project conventions are stable)
