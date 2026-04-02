# Phase 19: reviewer-agent — Research

**Researched:** 2026-03-22
**Domain:** Graph-traversal context assembly + structured LLM code review
**Confidence:** HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| REVW-01 | Reviewer assembles review context as: target node + 1-hop callers (predecessors) + 1-hop callees (successors) | NetworkX predecessors()/successors() filtered by CALLS-edge type; reviewer_context_hops=1 from Settings |
| REVW-02 | Reviewer generates structured Finding objects with severity, category, description, file_path, line_start, line_end, and suggestion | Pydantic BaseModel schema identical in structure to SuspectNode pattern from debugger.py |
| REVW-03 | When selected_file and selected_range are provided, reviewer targets the user-selected code range specifically | Accepted as optional parameters to review(); prompt engineering to focus LLM on the range |
| TST-03 | test_reviewer.py validates context assembly, schema completeness, hallucinated node reference absence using mock graph | Pattern mirrors test_debugger.py: fixture graph + mock_settings + mock_llm_factory; groundedness assertion compares Finding node references against retrieved_nodes set |
</phase_requirements>

---

## Summary

Phase 19 implements the Reviewer agent following the exact same structural pattern established in Phase 18 (Debugger). The core algorithm is simpler than the Debugger: instead of BFS traversal with anomaly scoring, the Reviewer performs a fixed 1-hop neighborhood expansion from a target node and passes that bounded context to the LLM to generate structured `Finding` objects. The key correctness invariant is groundedness: every node_id referenced in a Finding must exist in the set of nodes retrieved during context assembly.

The agent accepts an optional `selected_file` / `selected_range` pair. When provided, the LLM prompt focuses on that code region rather than the whole target node. This is purely prompt-engineering — no graph traversal change is required. The `reviewer_context_hops` setting (default 1) is already present in `Settings` and controls the expansion radius, but for this phase only 1-hop is required.

The test suite (TST-03) must mirror `test_debugger.py` exactly: offline fixtures, no live API calls, source-level patching of `app.core.model_factory.get_llm`, and explicit groundedness assertions checking that no Finding references a node outside `retrieved_nodes`.

**Primary recommendation:** Model `reviewer.py` directly on `debugger.py`. Reuse the lazy-import pattern, the Pydantic output schema approach, and the `settings=None` injection point. The new work is: 1-hop neighborhood assembly, `Finding` Pydantic model with 7 fields, prompt grounding constraint, and optional range targeting.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| networkx | Already a dep | 1-hop predecessor/successor traversal | Project graph is a NetworkX DiGraph; `G.predecessors()` / `G.successors()` are the exact API needed |
| pydantic | v2 (already a dep) | `Finding` output schema | All V2 agents use BaseModel for structured output; immutability pattern already established |
| langchain-core | Already a dep | `ChatPromptTemplate`, LCEL pipe operator | Same pattern as debugger.py — `prompt | llm`, then `chain.invoke()` |
| app.core.model_factory | Internal | `get_llm()` lazy import | Established project pattern — never import at module level |
| app.config | Internal | `get_settings()` lazy import, `reviewer_context_hops` | Settings already has the field (value=1) |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest + unittest.mock | Already a dep | `test_reviewer.py` fixtures, patch | All V2 tests use this combination |
| typing (Literal, Optional) | stdlib | Type annotations on Finding fields | Severity as `Literal["critical","warning","info"]` |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `with_structured_output(FindingList)` | manual JSON parsing | `with_structured_output` is established router pattern — but debugger uses plain `chain.invoke` with `.content`; reviewer should align with debugger (plain LLM call) since findings list requires iteration logic not a single Pydantic instance |

**Installation:** No new packages. All dependencies already present.

---

## Architecture Patterns

### Recommended Project Structure

```
backend/app/agent/
├── explorer.py        # V1 — DO NOT TOUCH
├── router.py          # Phase 17 — complete
├── debugger.py        # Phase 18 — complete (reference implementation)
└── reviewer.py        # Phase 19 — NEW

backend/tests/
├── test_debugger.py   # Phase 18 reference test
└── test_reviewer.py   # Phase 19 — NEW
```

### Pattern 1: Lazy Import Guards (established project standard)

**What:** `get_llm()` and `get_settings()` are imported inside the public function body, never at module level.

**When to use:** Every V2 agent function. This prevents `ValidationError` during pytest collection when API keys are absent.

**Example (from debugger.py — copy this pattern exactly):**
```python
def review(question: str, G: nx.DiGraph, target_node_id: str,
           selected_file: str | None = None,
           selected_range: tuple[int, int] | None = None,
           settings=None) -> ReviewResult:
    if settings is None:
        from app.config import get_settings  # noqa: PLC0415
        settings = get_settings()

    # ... later ...
    from app.core.model_factory import get_llm  # noqa: PLC0415
    llm = get_llm()
```

### Pattern 2: 1-Hop Context Assembly (REVW-01)

**What:** Collect target node + all CALLS-edge predecessors (callers) + all CALLS-edge successors (callees) within 1 hop.

**When to use:** At the start of `review()`, before LLM call.

**Example:**
```python
def _assemble_context(G: nx.DiGraph, target_id: str) -> tuple[list[str], set[str]]:
    """Return (ordered node_id list, retrieved_nodes set) for target + 1-hop neighbors."""
    nodes = [target_id]
    # 1-hop callers (predecessors via CALLS edges)
    callers = [
        pred for pred in G.predecessors(target_id)
        if G.edges[pred, target_id].get("type") == "CALLS"
    ]
    # 1-hop callees (successors via CALLS edges)
    callees = [
        succ for succ in G.successors(target_id)
        if G.edges[target_id, succ].get("type") == "CALLS"
    ]
    nodes.extend(callers)
    nodes.extend(callees)
    retrieved_nodes = set(nodes)
    return nodes, retrieved_nodes
```

**Note:** `reviewer_context_hops` from settings is available for future expansion; for this phase it is effectively hardwired at 1 by the requirement.

### Pattern 3: Finding Pydantic Model (REVW-02)

**What:** Seven-field structured output model. The LLM produces findings in structured form.

**Example:**
```python
from typing import Literal
from pydantic import BaseModel, Field

class Finding(BaseModel):
    severity: Literal["critical", "warning", "info"]
    category: str          # e.g. "security", "error-handling", "style", "performance"
    description: str
    file_path: str
    line_start: int
    line_end: int
    suggestion: str

class ReviewResult(BaseModel):
    findings: list[Finding]
    retrieved_nodes: list[str]   # node_ids assembled into context
    summary: str                 # LLM narrative summary
```

**Critical:** `retrieved_nodes` is stored on `ReviewResult` so downstream (Critic agent, tests) can verify groundedness without re-running graph traversal.

### Pattern 4: Groundedness Enforcement (Success Criterion 4)

**What:** After LLM generates findings, verify that every `file_path` referenced can be traced back to a node in `retrieved_nodes`. Since findings reference `file_path` (not `node_id` directly), the check is: for each Finding, at least one node in `retrieved_nodes` has `G.nodes[n]["file_path"] == finding.file_path`.

**Alternatively (simpler approach):** Instruct the LLM in the system prompt that it MUST only produce findings for nodes listed explicitly in the context block. Then post-filter: drop any Finding whose `file_path` does not appear in the set of file paths from `retrieved_nodes`.

**Recommended approach — post-filter:**
```python
valid_file_paths = {
    G.nodes[n].get("file_path", "") for n in retrieved_nodes if n in G
}
findings = [f for f in raw_findings if f.file_path in valid_file_paths]
```

This is deterministic and testable. The test asserts `len(findings) == len(validated_findings)`.

### Pattern 5: Optional Range Targeting (REVW-03)

**What:** When `selected_file` and `selected_range=(line_start, line_end)` are provided, the LLM prompt is augmented to focus on that range.

**When to use:** Only when both parameters are non-None.

**Example prompt augmentation:**
```python
range_clause = ""
if selected_file and selected_range:
    range_clause = (
        f"\n\nFOCUS: The user has selected lines {selected_range[0]}–{selected_range[1]} "
        f"of {selected_file}. Target your findings to this range specifically."
    )
```

This is purely additive to the prompt — no graph traversal change. The reviewer still assembles the full 1-hop context for groundedness, but the LLM is directed to prioritize the selection.

### Pattern 6: LLM Invocation (mirrors debugger.py)

**What:** Plain LCEL pipe. The LLM is asked to return findings in a structured format using `with_structured_output` OR by prompting for a JSON block then parsing.

**Recommended:** Use `with_structured_output(ReviewResult)` for a single structured call. This is consistent with how `router.py` uses structured output. However, note the mock pattern difference:

- Router pattern (`with_structured_output`): mock needs `mock_llm.with_structured_output.return_value` then `.invoke()` on the chain result
- Debugger pattern (plain pipe): mock needs `mock_llm.__or__` returning a chain mock, then `chain.invoke()`

**Decision:** Use `with_structured_output(ReviewResult)` for cleaner schema enforcement. This means the mock in `test_reviewer.py` follows the router mock pattern, not the debugger mock pattern.

```python
# In review():
llm = get_llm()
structured_llm = llm.with_structured_output(ReviewResult)
chain = REVIEWER_PROMPT | structured_llm
result: ReviewResult = chain.invoke({...})
```

**Mock pattern for tests:**
```python
mock_chain = MagicMock()
mock_chain.invoke.return_value = ReviewResult(findings=[...], retrieved_nodes=[...], summary="...")

mock_llm = MagicMock()
mock_llm.with_structured_output.return_value = mock_chain
# Note: pipe operator still needed
mock_pipe_chain = MagicMock()
mock_pipe_chain.invoke.return_value = ReviewResult(...)
mock_llm.__or__ = MagicMock(return_value=mock_pipe_chain)
```

**Simpler alternative:** Keep plain pipe (like debugger) and have the LLM return JSON text, then parse. This avoids the structured output mock complexity at the cost of less reliable LLM output in production.

**Recommendation:** Use `with_structured_output` — it is the established pattern from router.py and gives schema validation for free. The mock is slightly more complex but follows documented precedent.

### Anti-Patterns to Avoid

- **Modifying `explorer.py`:** Absolute project constraint — never touch this file.
- **Module-level `get_llm()` call:** Causes `ValidationError` at test collection time. Always import lazily inside function body.
- **Patching `app.agent.reviewer.get_llm`:** The lazy import makes this invisible at the consumer module level. Patch `app.core.model_factory.get_llm` instead (same as debugger tests).
- **Multi-hop traversal:** REVW-01 says 1-hop. `reviewer_context_hops=1` from settings. Do not implement multi-hop BFS for this phase.
- **Returning node IDs in Finding fields:** The `Finding` schema uses `file_path`, not `node_id`. Groundedness check must map file paths, not node IDs directly.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Graph neighbor traversal | Custom adjacency walking | `G.predecessors(n)`, `G.successors(n)` from NetworkX | Already returns the correct iterator; edge filtering is one `.get("type")` call |
| Structured LLM output | JSON regex parsing | `with_structured_output(ReviewResult)` via LangChain | Schema validation + retry built in; consistent with router.py |
| Settings injection in tests | Env var manipulation | `MagicMock()` with `settings.reviewer_context_hops = 1` passed to `review()` | Exact same pattern as `mock_settings` in `test_debugger.py` — just add the new field |

---

## Common Pitfalls

### Pitfall 1: Wrong Patch Target for Lazy Imports

**What goes wrong:** Test patches `app.agent.reviewer.get_llm` — patch has no effect, real `get_llm()` is called, `ValidationError` raised.

**Why it happens:** `review()` imports `get_llm` inside the function body. At the time of import, Python looks up `app.core.model_factory.get_llm` — not a module-level name in `app.agent.reviewer`.

**How to avoid:** Always patch `app.core.model_factory.get_llm`. This is documented in `test_debugger.py` line 11-12 and the `mock_llm_factory` fixture docstring.

**Warning signs:** Test passes without hitting the mock; `mock_factory.call_count` is 0.

### Pitfall 2: `with_structured_output` Mock Chain Is Different from Plain Pipe Mock

**What goes wrong:** Test mocks `mock_llm.__or__` (debugger pattern) but reviewer uses `with_structured_output`. The `__or__` mock is never called; `with_structured_output` returns the real (unmocked) object.

**Why it happens:** Mixing the two invocation patterns from different agents without checking which this agent uses.

**How to avoid:** In `test_reviewer.py`, if `review()` uses `with_structured_output`:
```python
mock_chain = MagicMock()
mock_chain.invoke.return_value = ReviewResult(...)
mock_llm.with_structured_output.return_value = mock_chain
# then pipe: prompt | structured_llm calls structured_llm.__ror__ or similar
```
The safest mock is to check that `mock_chain.invoke` is called and returns the fixture `ReviewResult`.

### Pitfall 3: Groundedness Test — file_path vs node_id Confusion

**What goes wrong:** Test asserts `finding.file_path in result.retrieved_nodes` — this fails because `retrieved_nodes` contains node IDs (`"src.py::func_a"`), not file paths (`"src.py"`).

**Why it happens:** The success criterion says "no Finding references a node ID not in retrieved_nodes" but `Finding` has `file_path`, not `node_id`.

**How to avoid:** Build the groundedness check as:
```python
valid_file_paths = {G.nodes[n].get("file_path", "") for n in result.retrieved_nodes}
for f in result.findings:
    assert f.file_path in valid_file_paths
```

### Pitfall 4: Target Node Not in Graph

**What goes wrong:** Caller passes a `target_node_id` that does not exist in `G`. `G.predecessors(target_node_id)` raises `NetworkXError`.

**Why it happens:** No guard on node existence before traversal.

**How to avoid:** Check `if target_node_id not in G` at the top of `_assemble_context()`. Return empty context or raise a clear `ValueError`. The test suite should include one test for this edge case.

### Pitfall 5: Empty Findings List Not Tested

**What goes wrong:** When no code issues are found, `findings=[]` — `ReviewResult` is valid but the test may not cover this path.

**Why it happens:** Focus on happy-path testing only.

**How to avoid:** Include one test where mock LLM returns `ReviewResult(findings=[], ...)`. Assert `len(result.findings) == 0` and `result.summary` is a non-empty string.

---

## Code Examples

Verified patterns from the project codebase:

### 1-hop neighbor query with edge type filter

```python
# From test_debugger.py and debugger.py — established CALLS-edge filter pattern
callers = [
    pred for pred in G.predecessors(target_id)
    if G.edges[pred, target_id].get("type") == "CALLS"
]
callees = [
    succ for succ in G.successors(target_id)
    if G.edges[target_id, succ].get("type") == "CALLS"
]
```

### Settings injection (mock_settings fixture pattern from test_debugger.py)

```python
@pytest.fixture
def mock_settings():
    settings = MagicMock()
    settings.reviewer_context_hops = 1  # only field reviewer needs
    return settings
```

### mock_llm_factory for with_structured_output path

```python
@pytest.fixture
def mock_llm_factory():
    """Patch get_llm at source module for reviewer's with_structured_output path."""
    with patch("app.core.model_factory.get_llm") as mock_factory:
        mock_chain = MagicMock()
        mock_chain.invoke.return_value = ReviewResult(
            findings=[
                Finding(
                    severity="warning",
                    category="error-handling",
                    description="Missing error handling in process_data.",
                    file_path="src.py",
                    line_start=10,
                    line_end=20,
                    suggestion="Wrap in try/except and log exceptions.",
                )
            ],
            retrieved_nodes=["src.py::target", "src.py::caller", "lib.py::callee"],
            summary="One warning found in process_data.",
        )

        mock_structured = MagicMock()
        mock_structured.__or__ = MagicMock(return_value=mock_chain)

        mock_llm = MagicMock()
        mock_llm.with_structured_output.return_value = mock_structured

        mock_factory.return_value = mock_llm
        yield mock_factory
```

### Reviewer graph fixture (mirrors debug_graph)

```python
@pytest.fixture
def reviewer_graph() -> nx.DiGraph:
    """5-node DiGraph: target + 2 callers + 2 callees, all CALLS edges.

    Topology:
      caller_a -> target -> callee_a
      caller_b -> target -> callee_b
    """
    G = nx.DiGraph()
    nodes = [
        {"node_id": "src.py::target",   "name": "target",   "file_path": "src.py",  "line_start": 10, "line_end": 30},
        {"node_id": "src.py::caller_a", "name": "caller_a", "file_path": "src.py",  "line_start": 1,  "line_end": 9},
        {"node_id": "src.py::caller_b", "name": "caller_b", "file_path": "other.py","line_start": 5,  "line_end": 15},
        {"node_id": "lib.py::callee_a", "name": "callee_a", "file_path": "lib.py",  "line_start": 1,  "line_end": 10},
        {"node_id": "lib.py::callee_b", "name": "callee_b", "file_path": "lib.py",  "line_start": 12, "line_end": 20},
    ]
    for n in nodes:
        G.add_node(n["node_id"], **n)
    G.add_edge("src.py::caller_a", "src.py::target",   type="CALLS")
    G.add_edge("src.py::caller_b", "src.py::target",   type="CALLS")
    G.add_edge("src.py::target",   "lib.py::callee_a", type="CALLS")
    G.add_edge("src.py::target",   "lib.py::callee_b", type="CALLS")
    return G
```

### Groundedness assertion (TST-03)

```python
def test_no_hallucinated_nodes(mock_llm_factory, mock_settings, reviewer_graph):
    """No Finding.file_path may reference a file not present in retrieved_nodes."""
    result = review("review process_data for quality issues", reviewer_graph,
                    target_node_id="src.py::target", settings=mock_settings)
    valid_file_paths = {
        reviewer_graph.nodes[n].get("file_path", "")
        for n in result.retrieved_nodes
        if n in reviewer_graph
    }
    for finding in result.findings:
        assert finding.file_path in valid_file_paths, (
            f"Hallucinated file_path: {finding.file_path!r} not in retrieved context"
        )
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Global `get_llm()` import | Lazy import inside function body | Phase 17 decision | Prevents `ValidationError` at test collection without API keys |
| Generic LLM text output | `with_structured_output(Pydantic model)` | Phase 17 router established | Schema-validated output, no manual JSON parsing |
| Patching consumer module | Patching source module (`app.core.model_factory`) | Phase 17 decision | Required for lazy imports — documented in test_debugger.py |

---

## Open Questions

1. **`with_structured_output` vs. plain pipe for LLM call**
   - What we know: Router uses `with_structured_output` (single Pydantic object). Debugger uses plain pipe (returns `.content` string).
   - What's unclear: `ReviewResult` with a `list[Finding]` — does `with_structured_output` handle nested lists reliably with Mistral?
   - Recommendation: Use `with_structured_output(ReviewResult)`. If Mistral structured output struggles with nested lists, fall back to prompting for JSON + `model_validate_json()`. Document this as a known risk in the plan.

2. **Where does groundedness filtering happen — in `review()` or in Critic?**
   - What we know: CRIT-04 says "groundedness is pre-computed from cited node IDs vs `retrieved_nodes` set". REVW-02 / success criterion 4 says reviewer enforces no hallucinated node references.
   - What's unclear: Should `reviewer.py` post-filter findings, or just expose `retrieved_nodes` for the Critic to check later?
   - Recommendation: Reviewer post-filters (drops invalid findings) AND exposes `retrieved_nodes` on `ReviewResult`. Critic can then verify the already-filtered list. Belt-and-suspenders approach.

3. **`reviewer_context_hops` from settings — enforce or ignore?**
   - What we know: Config field exists with default=1. REVW-01 says "1-hop callers and callees".
   - What's unclear: Should the code loop `reviewer_context_hops` times (generalizing to N-hop), or hardcode 1-hop logic?
   - Recommendation: Implement 1-hop logic directly (not a loop) for simplicity, but read `settings.reviewer_context_hops` and assert it equals 1 in tests. This keeps the config field meaningful without over-engineering multi-hop for a phase that only needs 1.

---

## Sources

### Primary (HIGH confidence)

- `backend/app/agent/debugger.py` — Reference implementation: lazy import pattern, Pydantic model shape, BFS traversal with CALLS-edge filter, LLM invocation
- `backend/app/agent/router.py` — `with_structured_output` pattern and mock approach
- `backend/tests/test_debugger.py` — Test fixture pattern: `debug_graph`, `mock_settings`, `mock_llm_factory`, groundedness test structure
- `backend/tests/conftest.py` — `sample_graph` fixture showing node attribute conventions (`file_path`, `line_start`, `line_end`, `type`)
- `backend/app/config.py` — `reviewer_context_hops: int = 1` confirmed present
- `.planning/REQUIREMENTS.md` — REVW-01, REVW-02, REVW-03, TST-03 requirement text verbatim
- `.planning/STATE.md` — All architectural decisions (lazy import, patch target, mock_settings pattern, Pydantic v2 immutability)

### Secondary (MEDIUM confidence)

- `.claude/projects/.../memory/project_architecture.md` — Stack overview confirming NetworkX DiGraph, model factory paths

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already in use; no new dependencies
- Architecture patterns: HIGH — directly derived from debugger.py (Phase 18) reference implementation
- Pitfalls: HIGH — sourced from documented Phase 17/18 decisions in STATE.md and test file docstrings
- Test patterns: HIGH — test_debugger.py is a complete, working reference

**Research date:** 2026-03-22
**Valid until:** 2026-04-22 (stable internal codebase; no external API churn expected)
