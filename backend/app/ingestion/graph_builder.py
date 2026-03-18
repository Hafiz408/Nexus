import warnings
import networkx as nx
from app.models.schemas import CodeNode


def build_graph(nodes: list[CodeNode], raw_edges: list[tuple]) -> nx.DiGraph:
    """Construct a fully resolved, PageRank-scored code graph.

    IMPORTS edge design (Option A from research):
    Raw IMPORTS edges from ast_parser.py use synthetic source_id "rel_path::__module__"
    which is not a real graph node. This function maps them back: when source_id ends with
    "::__module__", the file prefix is extracted and IMPORTS edges are emitted from each
    real node in that file to each real node in the imported target file.

    Args:
        nodes: All CodeNode objects from parse_file() across all files.
        raw_edges: List of (source_id, target_name, edge_type) tuples from ast_parser.

    Returns:
        nx.DiGraph with all CodeNode attributes + pagerank, in_degree, out_degree
        as node attributes on every node.
    """
    G = nx.DiGraph()

    # Build registries for edge resolution
    name_to_ids: dict[str, list[str]] = {}    # name -> [node_ids] for CALLS
    file_to_ids: dict[str, list[str]] = {}     # rel_path -> [node_ids] for IMPORTS

    # Pass 1: Add all nodes with attributes (MUST complete before any edges)
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

    # Pass 3: Compute graph metrics (after all edges are final)
    _compute_metrics(G)

    return G


def _add_calls_edge(
    G: nx.DiGraph,
    source_id: str,
    target_name: str,
    name_to_ids: dict[str, list[str]],
) -> None:
    """Resolve and add a CALLS edge. Drop with warning if target_name not found."""
    candidates = name_to_ids.get(target_name, [])
    if not candidates:
        warnings.warn(
            f"Unresolvable CALLS edge: {source_id!r} -> {target_name!r} (no matching node)",
            UserWarning,
            stacklevel=2,
        )
        return
    # V1: take first match; name collisions across files are a known limitation
    G.add_edge(source_id, candidates[0], type="CALLS")


def _add_imports_edges(
    G: nx.DiGraph,
    source_id: str,
    target_name: str,
    file_to_ids: dict[str, list[str]],
) -> None:
    """Resolve and add IMPORTS edges.

    Handles synthetic __module__ source IDs from ast_parser.py.
    If source_id ends with "::__module__", emits edges from all real nodes in the
    importing file to all real nodes in the target file (Option A from RESEARCH.md).
    Skips empty, ".", or relative (starts with ".") target_name values.
    """
    # Skip relative imports and empty targets (V1: only absolute module paths)
    if not target_name or target_name == "." or target_name.startswith("."):
        warnings.warn(
            f"Skipping relative/empty IMPORTS edge: {source_id!r} -> {target_name!r}",
            UserWarning,
            stacklevel=2,
        )
        return

    # Resolve target module path: "auth.utils" -> "auth/utils.py" (also try __init__.py)
    as_path = target_name.replace(".", "/") + ".py"
    target_node_ids = file_to_ids.get(as_path, [])
    if not target_node_ids:
        init_path = target_name.replace(".", "/") + "/__init__.py"
        target_node_ids = file_to_ids.get(init_path, [])

    if not target_node_ids:
        warnings.warn(
            f"Unresolvable IMPORTS edge: {source_id!r} -> {target_name!r} (no matching file)",
            UserWarning,
            stacklevel=2,
        )
        return

    # Determine source node IDs
    if source_id.endswith("::__module__"):
        # Synthetic source: emit edges from all real nodes in the importing file
        file_prefix = source_id[: -len("::__module__")]
        source_node_ids = file_to_ids.get(file_prefix, [])
    else:
        source_node_ids = [source_id] if source_id in G.nodes else []

    for src in source_node_ids:
        for tgt in target_node_ids:
            G.add_edge(src, tgt, type="IMPORTS")


def _compute_metrics(G: nx.DiGraph) -> None:
    """Compute pagerank, in_degree, out_degree and store as node attributes."""
    if G.number_of_nodes() == 0:
        return
    pr = nx.pagerank(G, alpha=0.85)
    nx.set_node_attributes(G, pr, "pagerank")
    nx.set_node_attributes(G, dict(G.in_degree()), "in_degree")
    nx.set_node_attributes(G, dict(G.out_degree()), "out_degree")
