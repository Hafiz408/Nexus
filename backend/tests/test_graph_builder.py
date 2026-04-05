import pytest
import networkx as nx
import warnings
from app.ingestion.graph_builder import build_graph


# --- GRAPH-01: Returns DiGraph with all node attributes ---

def test_returns_digraph(sample_nodes, sample_raw_edges):
    G = build_graph(sample_nodes, sample_raw_edges)
    assert isinstance(G, nx.DiGraph)

def test_node_count(sample_nodes, sample_raw_edges):
    G = build_graph(sample_nodes, sample_raw_edges)
    assert G.number_of_nodes() == 3

def test_node_attributes_preserved(sample_nodes, sample_raw_edges):
    G = build_graph(sample_nodes, sample_raw_edges)
    attrs = G.nodes["file_a.py::caller"]
    assert attrs["name"] == "caller"
    assert attrs["signature"] == "def caller():"
    assert attrs["type"] == "function"

def test_empty_graph(sample_nodes):
    G = build_graph([], [])
    assert isinstance(G, nx.DiGraph)
    assert G.number_of_nodes() == 0

# --- GRAPH-02: CALLS edge resolution ---

def test_calls_edge_resolved(sample_nodes, sample_raw_edges):
    G = build_graph(sample_nodes, sample_raw_edges)
    assert G.has_edge("file_a.py::caller", "file_a.py::helper")

def test_calls_edge_type_attribute(sample_nodes, sample_raw_edges):
    G = build_graph(sample_nodes, sample_raw_edges)
    data = G.edges["file_a.py::caller", "file_a.py::helper"]
    assert data["type"] == "CALLS"

def test_unresolvable_calls_edge_dropped_with_warning(sample_nodes):
    bad_edges = [("file_a.py::caller", "nonexistent_func", "CALLS")]
    with pytest.warns(UserWarning, match="Unresolvable"):
        G = build_graph(sample_nodes, bad_edges)
    # No orphan node created for the unresolvable target
    assert "nonexistent_func" not in str(list(G.nodes))
    # Still 3 original nodes
    assert G.number_of_nodes() == 3

def test_unresolvable_calls_no_extra_edges(sample_nodes):
    bad_edges = [("file_a.py::caller", "nonexistent_func", "CALLS")]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        G = build_graph(sample_nodes, bad_edges)
    assert G.number_of_edges() == 0

# --- GRAPH-03: IMPORTS edge resolution ---

def test_imports_edges_resolved(sample_nodes, sample_raw_edges):
    """__module__ source -> edges from all file_a nodes to all file_b nodes."""
    G = build_graph(sample_nodes, sample_raw_edges)
    # file_a has 2 nodes (caller + helper); file_b has 1 node (target)
    # Expect: caller->target and helper->target
    assert G.has_edge("file_a.py::caller", "file_b.py::target")
    assert G.has_edge("file_a.py::helper", "file_b.py::target")

def test_imports_edge_type_attribute(sample_nodes, sample_raw_edges):
    G = build_graph(sample_nodes, sample_raw_edges)
    data = G.edges["file_a.py::caller", "file_b.py::target"]
    assert data["type"] == "IMPORTS"

def test_unresolvable_imports_edge_dropped_with_warning(sample_nodes):
    bad_imports = [("file_a.py::__module__", "nonexistent.module", "IMPORTS")]
    with pytest.warns(UserWarning, match="Unresolvable"):
        G = build_graph(sample_nodes, bad_imports)
    assert G.number_of_nodes() == 3

def test_relative_import_skipped_with_warning(sample_nodes):
    relative_import = [("file_a.py::__module__", ".utils", "IMPORTS")]
    with pytest.warns(UserWarning):
        G = build_graph(sample_nodes, relative_import)
    assert G.number_of_edges() == 0

def test_empty_target_import_skipped(sample_nodes):
    empty_import = [("file_a.py::__module__", "", "IMPORTS")]
    with pytest.warns(UserWarning):
        G = build_graph(sample_nodes, empty_import)
    assert G.number_of_edges() == 0

# --- GRAPH-04: PageRank and degree attributes ---

def test_pagerank_present_on_all_nodes(sample_nodes, sample_raw_edges):
    G = build_graph(sample_nodes, sample_raw_edges)
    for node_id in G.nodes:
        assert "pagerank" in G.nodes[node_id], f"Missing pagerank on {node_id}"
        assert isinstance(G.nodes[node_id]["pagerank"], float)

def test_in_degree_present_on_all_nodes(sample_nodes, sample_raw_edges):
    G = build_graph(sample_nodes, sample_raw_edges)
    for node_id in G.nodes:
        assert "in_degree" in G.nodes[node_id]
        assert isinstance(G.nodes[node_id]["in_degree"], int)

def test_out_degree_present_on_all_nodes(sample_nodes, sample_raw_edges):
    G = build_graph(sample_nodes, sample_raw_edges)
    for node_id in G.nodes:
        assert "out_degree" in G.nodes[node_id]
        assert isinstance(G.nodes[node_id]["out_degree"], int)

def test_degree_correctness(sample_nodes, sample_raw_edges):
    """caller calls helper and imports target — check directional degrees."""
    G = build_graph(sample_nodes, sample_raw_edges)
    # caller: out_degree includes CALLS(helper) + IMPORTS(target) = 2
    assert G.nodes["file_a.py::caller"]["out_degree"] >= 1
    # helper: in_degree includes CALLS from caller + IMPORTS from caller = 2
    assert G.nodes["file_a.py::helper"]["in_degree"] >= 1
    # target: in_degree includes IMPORTS from caller + IMPORTS from helper
    assert G.nodes["file_b.py::target"]["in_degree"] >= 1

def test_pagerank_no_crash_on_empty_graph():
    G = build_graph([], [])
    assert G.number_of_nodes() == 0


# --- CLASS_CONTAINS edge resolution ---

def test_class_contains_edge_added(sample_nodes):
    """CLASS_CONTAINS edge is added between two existing nodes."""
    edges = [("file_a.py::caller", "file_a.py::helper", "CLASS_CONTAINS")]
    G = build_graph(sample_nodes, edges)
    assert G.has_edge("file_a.py::caller", "file_a.py::helper")

def test_class_contains_edge_type_attribute(sample_nodes):
    """CLASS_CONTAINS edge has type='CLASS_CONTAINS' attribute."""
    edges = [("file_a.py::caller", "file_a.py::helper", "CLASS_CONTAINS")]
    G = build_graph(sample_nodes, edges)
    assert G.edges["file_a.py::caller", "file_a.py::helper"]["type"] == "CLASS_CONTAINS"

def test_class_contains_missing_source_silently_skipped(sample_nodes):
    """CLASS_CONTAINS edge with unknown source node does not raise."""
    edges = [("nonexistent::node", "file_a.py::helper", "CLASS_CONTAINS")]
    G = build_graph(sample_nodes, edges)
    assert G.number_of_nodes() == 3  # no phantom nodes created

def test_class_contains_missing_target_silently_skipped(sample_nodes):
    """CLASS_CONTAINS edge with unknown target node does not raise."""
    edges = [("file_a.py::caller", "nonexistent::method", "CLASS_CONTAINS")]
    G = build_graph(sample_nodes, edges)
    assert G.number_of_edges() == 0

def test_class_contains_does_not_affect_pagerank_computation(sample_nodes):
    """Graph with CLASS_CONTAINS edges still computes pagerank on all nodes."""
    edges = [("file_a.py::caller", "file_a.py::helper", "CLASS_CONTAINS")]
    G = build_graph(sample_nodes, edges)
    for nid in G.nodes:
        assert "pagerank" in G.nodes[nid]
