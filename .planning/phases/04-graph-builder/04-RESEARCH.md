# Phase 4: Graph Builder - Research

**Researched:** 2026-03-18
**Domain:** NetworkX DiGraph construction, edge resolution, PageRank computation, Python 3.11
**Confidence:** HIGH

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| GRAPH-01 | `build_graph(nodes, raw_edges)` returns `nx.DiGraph` with all node attributes | NetworkX 3.6.1 `DiGraph.add_node(**attrs)` pattern confirmed; all CodeNode fields become node attributes |
| GRAPH-02 | Resolves raw CALLS edges by matching `target_name` against full node registry; unresolvable edges dropped with warning | Build a dict `{name: node_id}` registry; match target_name; use `warnings.warn()` for unresolvable; confirmed pattern |
| GRAPH-03 | Resolves IMPORTS edges: module import → IMPORTS edge to all nodes in target file | Build a dict `{rel_path_prefix: [node_ids]}` from node registry; resolve dotted module names to file paths |
| GRAPH-04 | Computes and stores `in_degree`, `out_degree`, `pagerank` as node attributes | `nx.pagerank(G)` returns dict; `nx.set_node_attributes()` stores it; `dict(G.in_degree())` converts to dict for same API |
| GRAPH-05 | Unit tests pass: edge resolution, PageRank presence, in/out degree correctness | pytest in-memory DiGraph fixtures; confirmed NetworkX can be constructed in-memory without files |
| TEST-04 | `tests/test_graph_builder.py` — edge resolution, unresolvable edge drop, PageRank, in/out degree | TDD: write tests first against `build_graph()` API; fixtures are small hand-crafted CodeNode lists |
</phase_requirements>

---

## Summary

Phase 4 builds `backend/app/ingestion/graph_builder.py`, which takes the output of `parse_file()` (a list of `CodeNode` objects and a list of raw edge tuples) and produces a fully resolved, attributed `nx.DiGraph`. This is the connective tissue between the AST parser (Phase 3) and the embedder/pipeline (Phase 5–6), and its output is also directly consumed by Graph RAG retrieval in Phase 8.

The core library is NetworkX 3.6.1 — the current stable release. The API is stable and well-documented. Key operations are: populating graph nodes from `CodeNode` attributes, resolving `(source_id, target_name, edge_type)` tuples to real node IDs via a lookup registry, and computing PageRank/degree stats and storing them back as node attributes. The resolution logic (GRAPH-02 and GRAPH-03) is the only non-trivial part — matching raw `target_name` strings to actual node IDs requires a carefully-designed lookup table built from the node registry.

The `raw_edges` from Phase 3 carry unresolved target names: `"standalone_function"` for CALLS, `"auth.utils"` for IMPORTS. CALLS resolution needs a `{name: node_id}` reverse index. IMPORTS resolution requires mapping dotted module paths (e.g., `"auth.utils"`) to relative file paths (e.g., `"auth/utils.py"`) and then finding all nodes in that file. Both lookups have collision cases (multiple nodes with the same name) that must be handled by choosing the best match or dropping with a warning.

**Primary recommendation:** Build `build_graph(nodes, raw_edges)` as a single function with internal helper functions for registry building, CALLS resolution, and IMPORTS resolution. Use `nx.set_node_attributes()` to store PageRank in bulk. Store degree values with a simple loop over `G.in_degree()` and `G.out_degree()`.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| networkx | 3.6.1 | DiGraph construction, PageRank computation, degree views | The standard Python graph library; PRD explicitly specifies `nx.DiGraph` and `nx.pagerank` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| warnings (stdlib) | stdlib | `warnings.warn()` for unresolvable edges | GRAPH-02 explicitly requires warning on dropped edges |
| logging (stdlib) | stdlib | Module-level logger for debug traces | Optional but good practice; `logger.warning()` acceptable alternative to `warnings.warn()` |
| pytest | latest (already in project) | Unit tests for test_graph_builder.py | Standard project test runner |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| networkx | igraph (python-igraph) | igraph is faster for large graphs but has a different API; PRD explicitly specifies networkx |
| networkx | graph-tool | graph-tool requires a C++ compile; networkx is pure Python, simpler install |
| nx.pagerank() | custom PageRank implementation | nx.pagerank() is battle-tested with dangling-node handling, convergence guarantees, and weighted edge support |

**Installation:**
```bash
pip install networkx
```

NetworkX 3.6.1 has no mandatory dependencies for basic graph operations and PageRank (scipy is optional for the scipy-based variant). The core `nx.pagerank()` function uses a pure Python power iteration algorithm by default — no scipy needed.

---

## Architecture Patterns

### Recommended Project Structure
```
backend/app/
├── ingestion/
│   ├── __init__.py
│   ├── walker.py           # Phase 2 (done)
│   ├── ast_parser.py       # Phase 3 (done)
│   └── graph_builder.py    # CREATE THIS PHASE
backend/tests/
├── conftest.py             # UPDATE: add graph builder fixtures
└── test_graph_builder.py   # CREATE THIS PHASE
```

### Pattern 1: Two-Pass Graph Population

**What:** First pass adds all nodes (with attributes) to build the registry. Second pass resolves and adds edges. PageRank/degree computed after all edges are added.
**When to use:** Always — computing PageRank on a partially-constructed graph gives wrong results.
**Example:**
```python
# Source: NetworkX 3.6.1 official docs https://networkx.org/documentation/stable/tutorial.html
import networkx as nx
import warnings

def build_graph(nodes: list[CodeNode], raw_edges: list[tuple]) -> nx.DiGraph:
    G = nx.DiGraph()

    # Pass 1: Add all nodes with their attributes
    name_to_ids: dict[str, list[str]] = {}       # name → [node_ids] for CALLS resolution
    file_to_ids: dict[str, list[str]] = {}        # rel_path → [node_ids] for IMPORTS resolution

    for node in nodes:
        G.add_node(node.node_id, **node.model_dump())
        name_to_ids.setdefault(node.name, []).append(node.node_id)
        file_key = node.node_id.split("::")[0]    # "rel/path.py" from "rel/path.py::func"
        file_to_ids.setdefault(file_key, []).append(node.node_id)

    # Pass 2: Resolve and add edges
    _resolve_edges(G, raw_edges, name_to_ids, file_to_ids)

    # Pass 3: Compute and store graph metrics
    _compute_metrics(G)

    return G
```

### Pattern 2: CALLS Edge Resolution

**What:** Match `target_name` against the name registry to find the target node_id. If multiple matches exist (overloaded names across files), use the first match. Drop with warning if no match.
**When to use:** For every raw edge with `edge_type == "CALLS"`.
**Example:**
```python
# Source: derived from REQUIREMENTS.md GRAPH-02 and PRD design
def _resolve_calls(G, source_id, target_name, name_to_ids):
    candidates = name_to_ids.get(target_name, [])
    if not candidates:
        warnings.warn(
            f"Unresolvable CALLS edge: {source_id} -> {target_name!r} (no matching node)",
            stacklevel=2,
        )
        return
    # Take first candidate; for V1 we don't disambiguate across files
    target_id = candidates[0]
    G.add_edge(source_id, target_id, type="CALLS")
```

### Pattern 3: IMPORTS Edge Resolution

**What:** Convert a dotted module name (e.g., `"auth.utils"`) to a file path key (e.g., `"auth/utils.py"`), then add edges from the source to ALL nodes in that file.
**When to use:** For every raw edge with `edge_type == "IMPORTS"`.
**Example:**
```python
# Source: derived from REQUIREMENTS.md GRAPH-03
def _resolve_imports(G, source_id, target_name, file_to_ids):
    # Convert "auth.utils" -> "auth/utils.py" (and also try "auth/utils/__init__.py")
    as_path = target_name.replace(".", "/") + ".py"
    target_node_ids = file_to_ids.get(as_path, [])

    # Also try package __init__ style
    if not target_node_ids:
        init_path = target_name.replace(".", "/") + "/__init__.py"
        target_node_ids = file_to_ids.get(init_path, [])

    if not target_node_ids:
        warnings.warn(
            f"Unresolvable IMPORTS edge: {source_id} -> {target_name!r} (no matching file)",
            stacklevel=2,
        )
        return

    for target_id in target_node_ids:
        G.add_edge(source_id, target_id, type="IMPORTS")
```

### Pattern 4: PageRank and Degree Storage

**What:** Compute PageRank, in_degree, and out_degree, and store as node attributes using `nx.set_node_attributes()` and direct assignment loops.
**When to use:** After all edges are added (Pass 3).
**Example:**
```python
# Source: NetworkX 3.6.1 docs https://networkx.org/documentation/stable/reference/generated/networkx.classes.function.set_node_attributes.html
def _compute_metrics(G: nx.DiGraph) -> None:
    # PageRank — returns {node_id: score}
    if G.number_of_nodes() > 0:
        pr = nx.pagerank(G, alpha=0.85)
        nx.set_node_attributes(G, pr, "pagerank")
    else:
        return

    # In-degree and out-degree
    in_deg = dict(G.in_degree())
    out_deg = dict(G.out_degree())
    nx.set_node_attributes(G, in_deg, "in_degree")
    nx.set_node_attributes(G, out_deg, "out_degree")
```

### Pattern 5: CodeNode Attribute Preservation

**What:** All original `CodeNode` fields must be preserved on each graph node.
**When to use:** When calling `G.add_node()`.
**Example:**
```python
# Source: NetworkX 3.6.1 docs — node attributes dict
# node.model_dump() returns all CodeNode fields as a plain dict
G.add_node(node.node_id, **node.model_dump())
# Access later: G.nodes["rel/path.py::func_name"]["signature"]
```

**Important:** After `build_graph()` returns, Phase 8 (Graph RAG) will access `G.nodes[node_id]` to reconstruct `CodeNode`-like objects. All original fields must be accessible.

### Anti-Patterns to Avoid

- **Building edges before nodes:** If `G.add_edge(src, tgt)` is called before nodes are added, NetworkX creates bare nodes with no attributes. Always add nodes first in Pass 1.
- **Running PageRank before all edges are added:** PageRank results depend on the complete edge structure. Compute only after Pass 2 completes.
- **Using `G.degree()` instead of `G.in_degree()` / `G.out_degree()`:** For DiGraph, `G.degree()` returns total degree (in + out), not the directional values the requirements specify. Use `G.in_degree()` and `G.out_degree()` explicitly.
- **Silently dropping unresolvable edges:** GRAPH-02 requires a warning for each dropped edge. Do not silently skip.
- **String-matching target_name as substring:** CALLS resolution must match the FULL `target_name` string, not a substring. `"validate"` should not match `"validate_token"`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| PageRank computation | Custom power iteration loop | `nx.pagerank(G)` | Handles dangling nodes, convergence tolerance, weighted edges; extensively tested |
| Degree computation | Manual counting of neighbors | `G.in_degree()`, `G.out_degree()` | Built-in DiGraph views; correct, O(1) per node, no iteration bugs |
| Storing dicts of scores back to nodes | Loop with `G.nodes[n]["attr"] = val` | `nx.set_node_attributes(G, dict, "attr_name")` | Bulk assignment in one call; ignores missing nodes safely |
| Graph traversal / BFS for RAG | Custom BFS implementation | `nx.bfs_edges()`, `nx.ego_graph()` | Phase 8 will need these; NetworkX provides them. Do not pre-implement in Phase 4. |

**Key insight:** NetworkX's graph metric functions are the entire reason for using the library. Never re-implement what the library provides.

---

## Common Pitfalls

### Pitfall 1: Nodes Created Without Attributes by Edge-First Addition

**What goes wrong:** `G.add_edge("a::foo", "b::bar", type="CALLS")` silently creates nodes `"a::foo"` and `"b::bar"` with no attributes if they don't already exist. These bare nodes then fail when downstream code tries to read `G.nodes["a::foo"]["signature"]`.
**Why it happens:** NetworkX auto-creates nodes when edges reference non-existent nodes — it's a feature, but here it's a trap.
**How to avoid:** Always complete the full node-population pass (Pass 1) before adding any edges (Pass 2). After `build_graph()`, verify `assert all("name" in G.nodes[n] for n in G.nodes)`.
**Warning signs:** `KeyError` on `G.nodes[node_id]["name"]` during Phase 8 retrieval.

### Pitfall 2: PageRank Fails on Disconnected/Empty Graph

**What goes wrong:** `nx.pagerank(G)` raises `PowerIterationFailedConvergence` on certain degenerate graphs, or silently returns incorrect results on empty graphs.
**Why it happens:** The power iteration algorithm needs at least one node and can fail to converge on pathological graphs within `max_iter=100` iterations.
**How to avoid:** Guard with `if G.number_of_nodes() == 0: return`. For graphs with no edges at all (all isolated nodes), `nx.pagerank()` still works — isolated nodes get uniform 1/N scores. Only raises on graphs where convergence fails within max_iter.
**Warning signs:** `nx.exception.PowerIterationFailedConvergence` in tests with tiny graphs.

### Pitfall 3: IMPORTS Source ID is Synthetic (`rel_path::__module__`)

**What goes wrong:** The source_id for IMPORTS edges from the AST parser is `"rel/path.py::__module__"` — a synthetic ID that does NOT correspond to any node in the graph. Adding a graph edge with this source will create a bare orphan node.
**Why it happens:** This is documented in STATE.md: "IMPORTS edges use synthetic `rel_path::__module__` source_id — avoids requiring a file-level node in the graph." Phase 4 must handle this correctly.
**How to avoid:** For IMPORTS edges, the source_id `"rel/path.py::__module__"` is not a valid graph node. Skip adding the IMPORTS edge as-is. Instead, IMPORTS edges represent "the file imports module X", and the graph should represent this as edges from each node in the importing file to each node in the imported file. Or simply skip IMPORTS source validation and only add them if the source exists as a node (which it won't for `__module__` synthetics). Re-read REQUIREMENTS.md carefully: GRAPH-03 says "IMPORTS edges link **caller files** to all nodes in the imported target file" — the source should be the file itself, not a specific node. The implementation must decide: skip `__module__` sources, or treat the IMPORTS edge differently from CALLS edges.
**Warning signs:** Orphan `"rel/path.py::__module__"` nodes in the graph that have no CodeNode attributes.

### Pitfall 4: CALLS Resolution Name Collisions

**What goes wrong:** Multiple functions across different files share the same name (e.g., `"validate"` in `auth/utils.py` and `"validate"` in `models/user.py`). The `name_to_ids` registry maps `"validate"` → `[id1, id2]`.
**Why it happens:** Code bases routinely have duplicate function names across modules.
**How to avoid:** For V1, take the first match. Document this as a known limitation. For improved accuracy in future phases, prefer matching the name that's in the same file as the caller.
**Warning signs:** Tests pass but graph has wrong edges for multi-file codebases.

### Pitfall 5: IMPORTS Module Path Mapping Fails for Relative Imports

**What goes wrong:** Python relative imports like `from . import utils` produce `target_name = ""` or `"."` which maps to nothing useful.
**Why it happens:** The AST parser in Phase 3 captures `dotted_name` nodes from `import_from_statement` which for relative imports (starting with `.`) may not yield a clean module path.
**How to avoid:** In the IMPORTS resolver, skip `target_name` values that are empty, `"."`, or start with `"."`. Drop these with a warning. For V1, only absolute module paths are resolved.
**Warning signs:** Many "unresolvable IMPORTS" warnings for relative imports.

### Pitfall 6: model_dump() vs dict() for Pydantic v2

**What goes wrong:** `node.dict()` is called instead of `node.model_dump()` — Pydantic v2 deprecated `.dict()`.
**Why it happens:** Most online examples predate Pydantic v2.
**How to avoid:** Use `node.model_dump()` (Pydantic v2 API). The project uses Pydantic v2 (`pydantic-settings>=2.0.0` in requirements.txt).
**Warning signs:** Pydantic `PydanticDeprecatedSince20` warning at runtime.

---

## Code Examples

Verified patterns from official sources:

### Complete build_graph() Structure
```python
# Source: NetworkX 3.6.1 docs + PRD GRAPH-01 through GRAPH-04
import warnings
import networkx as nx
from app.models.schemas import CodeNode


def build_graph(nodes: list[CodeNode], raw_edges: list[tuple]) -> nx.DiGraph:
    """Construct a fully resolved, PageRank-scored code graph.

    Args:
        nodes: All CodeNode objects from parse_file() across all files
        raw_edges: List of (source_id, target_name, edge_type) tuples

    Returns:
        nx.DiGraph with all node attributes + pagerank, in_degree, out_degree
    """
    G = nx.DiGraph()

    # Build registries for edge resolution
    name_to_ids: dict[str, list[str]] = {}
    file_to_ids: dict[str, list[str]] = {}

    # Pass 1: Add nodes with all attributes
    for node in nodes:
        G.add_node(node.node_id, **node.model_dump())
        name_to_ids.setdefault(node.name, []).append(node.node_id)
        file_key = node.node_id.split("::")[0]
        file_to_ids.setdefault(file_key, []).append(node.node_id)

    # Pass 2: Resolve and add edges
    for source_id, target_name, edge_type in raw_edges:
        if edge_type == "CALLS":
            _add_calls_edge(G, source_id, target_name, name_to_ids)
        elif edge_type == "IMPORTS":
            _add_imports_edges(G, source_id, target_name, file_to_ids)

    # Pass 3: Compute graph metrics
    _compute_metrics(G)

    return G
```

### PageRank + Degree Storage
```python
# Source: https://networkx.org/documentation/stable/reference/generated/networkx.classes.function.set_node_attributes.html
def _compute_metrics(G: nx.DiGraph) -> None:
    if G.number_of_nodes() == 0:
        return

    # PageRank — alpha=0.85 is the standard damping factor
    pr = nx.pagerank(G, alpha=0.85)
    nx.set_node_attributes(G, pr, "pagerank")

    # Degree counts — convert DegreeView to plain dict
    nx.set_node_attributes(G, dict(G.in_degree()), "in_degree")
    nx.set_node_attributes(G, dict(G.out_degree()), "out_degree")
```

### Node Attribute Access Pattern
```python
# Source: NetworkX 3.6.1 docs https://networkx.org/documentation/stable/tutorial.html
# Accessing a node's attributes after build_graph()
attrs = G.nodes["src/auth/utils.py::validate_token"]
# attrs["name"]       == "validate_token"
# attrs["type"]       == "function"
# attrs["pagerank"]   == 0.023...
# attrs["in_degree"]  == 3
# attrs["out_degree"] == 1

# Iterating all nodes with data
for node_id, data in G.nodes(data=True):
    print(node_id, data["pagerank"])
```

### Test Fixture Pattern (Small In-Memory Graph)
```python
# Location: backend/tests/conftest.py — ADD these fixtures
import pytest
import networkx as nx
from app.models.schemas import CodeNode


@pytest.fixture
def sample_nodes() -> list[CodeNode]:
    """Three nodes: two functions in file_a.py, one function in file_b.py."""
    return [
        CodeNode(node_id="file_a.py::caller", name="caller", type="function",
                 file_path="/repo/file_a.py", line_start=1, line_end=5,
                 signature="def caller():"),
        CodeNode(node_id="file_a.py::helper", name="helper", type="function",
                 file_path="/repo/file_a.py", line_start=7, line_end=10,
                 signature="def helper():"),
        CodeNode(node_id="file_b.py::target", name="target", type="function",
                 file_path="/repo/file_b.py", line_start=1, line_end=3,
                 signature="def target():"),
    ]


@pytest.fixture
def sample_raw_edges() -> list[tuple]:
    """One CALLS edge and one IMPORTS edge."""
    return [
        ("file_a.py::caller", "helper", "CALLS"),
        ("file_a.py::caller", "helper", "CALLS"),       # duplicate — should not double-add
        ("file_a.py::__module__", "file_b", "IMPORTS"),  # synthetic __module__ source
    ]
```

### Key Test Cases
```python
# Location: backend/tests/test_graph_builder.py
from app.ingestion.graph_builder import build_graph

def test_returns_digraph(sample_nodes, sample_raw_edges):
    G = build_graph(sample_nodes, sample_raw_edges)
    assert isinstance(G, nx.DiGraph)

def test_all_nodes_present(sample_nodes, sample_raw_edges):
    G = build_graph(sample_nodes, sample_raw_edges)
    assert G.number_of_nodes() == 3

def test_node_attributes_preserved(sample_nodes, sample_raw_edges):
    G = build_graph(sample_nodes, sample_raw_edges)
    attrs = G.nodes["file_a.py::caller"]
    assert attrs["name"] == "caller"
    assert attrs["signature"] == "def caller():"

def test_calls_edge_resolved(sample_nodes, sample_raw_edges):
    G = build_graph(sample_nodes, sample_raw_edges)
    assert G.has_edge("file_a.py::caller", "file_a.py::helper")

def test_unresolvable_calls_edge_dropped_with_warning(sample_nodes):
    bad_edges = [("file_a.py::caller", "nonexistent_func", "CALLS")]
    with pytest.warns(UserWarning, match="Unresolvable"):
        G = build_graph(sample_nodes, bad_edges)
    assert not any(
        "nonexistent_func" in str(n) for n in G.nodes
    )

def test_pagerank_present(sample_nodes, sample_raw_edges):
    G = build_graph(sample_nodes, sample_raw_edges)
    for node_id in G.nodes:
        assert "pagerank" in G.nodes[node_id]
        assert isinstance(G.nodes[node_id]["pagerank"], float)

def test_in_out_degree_present(sample_nodes, sample_raw_edges):
    G = build_graph(sample_nodes, sample_raw_edges)
    for node_id in G.nodes:
        assert "in_degree" in G.nodes[node_id]
        assert "out_degree" in G.nodes[node_id]

def test_degree_correctness(sample_nodes, sample_raw_edges):
    G = build_graph(sample_nodes, sample_raw_edges)
    # caller calls helper — caller has out_degree=1, helper has in_degree=1
    assert G.nodes["file_a.py::caller"]["out_degree"] >= 1
    assert G.nodes["file_a.py::helper"]["in_degree"] >= 1
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `node.dict()` (Pydantic v1) | `node.model_dump()` (Pydantic v2) | Pydantic 2.0 (2023) | `.dict()` still works but raises deprecation warning in v2 |
| `nx.pagerank_scipy()` (separate function) | `nx.pagerank()` (unified) | NetworkX 2.x | `pagerank_scipy` still exists but `pagerank()` is the standard |
| `G.node[n]` dict access | `G.nodes[n]` dict access | NetworkX 2.4 | `G.node` was deprecated and removed; use `G.nodes` |

**Deprecated/outdated:**
- `G.node`: Removed in NetworkX 2.4+. Use `G.nodes` (with the `s`).
- `node.dict()`: Deprecated in Pydantic v2. Use `node.model_dump()`.
- `nx.pagerank_numpy()`: Works but is slower than power iteration for large graphs; not needed here.

---

## IMPORTS Edge Design Decision

**This is the most ambiguous part of the specification (GRAPH-03).** The PRD says:

> "Resolves IMPORTS edges: module import → IMPORTS edge to all nodes in target file"

But the AST parser (from STATE.md) emits IMPORTS edges with a synthetic `"rel_path::__module__"` source_id that is not a real node. The implementation must decide how to handle this:

**Option A (Recommended for V1):** The source of IMPORTS edges in the graph is any node that lives in the same file as the import statement. Concretely: if `file_a.py::__module__` is the source, map it back to all nodes in `file_a.py` and add IMPORTS edges from each of those nodes to all nodes in the target file.

**Option B:** Add a special file-level node for each file (e.g., `file_a.py::__file__`) and use it as the source for IMPORTS edges. This keeps the source consistent but adds non-code nodes to the graph.

**Option C:** Skip the `__module__` source nodes entirely — emit no IMPORTS edges into the graph since the file-level node doesn't exist. Only CALLS edges are added.

The planner should choose **Option A** since it produces a graph where function-level IMPORTS relationships are visible, which directly enables Phase 8's BFS expansion to find related nodes. Document this design choice clearly in the implementation.

---

## Open Questions

1. **IMPORTS edge source: which approach to implement?**
   - What we know: raw IMPORTS edges have `"rel_path::__module__"` source IDs (synthetic, not real nodes). GRAPH-03 says "link caller files to all nodes in imported target file."
   - What's unclear: "caller files" could mean the file itself (no node exists), or all nodes in that file.
   - Recommendation: Implement Option A — map `__module__` back to all nodes in the same file and emit per-node IMPORTS edges. If the importing file has no nodes yet (empty file), no IMPORTS edges are emitted. Add this interpretation as a docstring in graph_builder.py.

2. **What happens to `__module__` synthetic node IDs if added as graph edges?**
   - What we know: `G.add_edge(source_id, target_id)` will auto-create `source_id` as a bare node if it doesn't exist.
   - What's unclear: Whether downstream phases will break if bare `__module__` nodes appear in the graph.
   - Recommendation: Never add bare `__module__` nodes. Guard `_add_imports_edges()` to skip if `source_id.endswith("::__module__")` and use the file-prefix lookup instead.

3. **Should `networkx` be pinned to an exact version?**
   - What we know: NetworkX 3.6.1 is current stable (released December 2025). API is stable; no breaking changes expected in patch versions.
   - What's unclear: Whether `>=3.4` or `==3.6.1` is preferable.
   - Recommendation: Pin to `networkx>=3.4` to allow minor version updates while avoiding pre-3.4 API differences. The key APIs used (`set_node_attributes`, `pagerank`, `DiGraph`) are stable across 3.x.

---

## Sources

### Primary (HIGH confidence)
- `https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.link_analysis.pagerank_alg.pagerank.html` — pagerank() signature, parameters, return type, exceptions (NetworkX 3.6.1)
- `https://networkx.org/documentation/stable/reference/generated/networkx.classes.function.set_node_attributes.html` — set_node_attributes() signature, dict-keyed usage (NetworkX 3.6.1)
- `https://networkx.org/documentation/stable/reference/classes/digraph.html` — DiGraph API: in_degree, out_degree, add_node, nodes (NetworkX 3.6.1)
- `https://networkx.org/documentation/stable/tutorial.html` — Node attribute patterns, DiGraph construction (NetworkX 3.6.1)
- `https://pypi.org/project/networkx/` — Current version 3.6.1 confirmed, Python 3.11+ required
- `.planning/STATE.md` — Documents that IMPORTS edges use `rel_path::__module__` synthetic source_id (Phase 3 decision)
- `backend/app/models/schemas.py` — Confirmed CodeNode fields: `model_dump()` available (Pydantic v2)

### Secondary (MEDIUM confidence)
- `https://github.com/networkx/networkx/issues/7879` — PowerIterationFailedConvergence issue (active 2025), confirms exception behavior
- `https://networkx.org/documentation/stable/release/release_3.6.html` — NetworkX 3.6.1 release notes (December 2025)

### Tertiary (LOW confidence)
- `https://memgraph.github.io/networkx-guide/algorithms/centrality-algorithms/pagerank/` — PageRank usage patterns (third-party guide, not official)

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — NetworkX 3.6.1 confirmed on PyPI; official docs verified; API signatures confirmed
- Architecture (pass structure): HIGH — Derived directly from requirements and NetworkX API; no ambiguity
- CALLS resolution pattern: HIGH — Simple dict lookup; well-understood pattern
- IMPORTS resolution pattern: MEDIUM — Synthetic `__module__` source IDs require interpretation; design decision documented
- Pitfalls: HIGH — Most confirmed from official docs or STATE.md prior decisions
- Test fixture patterns: HIGH — Standard pytest patterns; NetworkX in-memory graphs require no external resources

**Research date:** 2026-03-18
**Valid until:** 2026-04-18 (NetworkX API is stable; no breaking changes expected in this timeframe)
