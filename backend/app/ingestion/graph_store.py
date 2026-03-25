"""SQLite persistence layer for NetworkX DiGraphs.

Provides four public functions:
  - save_graph(G, repo_path, db_path): persist all nodes and edges to SQLite
  - load_graph(repo_path, db_path): reconstruct a DiGraph with all attributes
  - delete_nodes_for_files(file_paths, repo_path, db_path): remove nodes by file_path + incident edges
  - delete_graph_for_repo(repo_path, db_path): remove all graph data for a repo
"""

import json
import os
import sqlite3

import networkx as nx


def _get_conn(db_path: str) -> sqlite3.Connection:
    """Connect to SQLite, create schema if needed, return connection.

    Creates the parent directory automatically so callers do not need to
    pre-create the .nexus/ directory.

    Uses sqlite3.Row as row_factory so columns can be accessed by name.
    """
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS graph_nodes (
            node_id    TEXT NOT NULL,
            repo_path  TEXT NOT NULL,
            file_path  TEXT NOT NULL,
            attrs_json TEXT NOT NULL,
            PRIMARY KEY (node_id, repo_path)
        );

        CREATE TABLE IF NOT EXISTS graph_edges (
            source     TEXT NOT NULL,
            target     TEXT NOT NULL,
            repo_path  TEXT NOT NULL,
            attrs_json TEXT NOT NULL DEFAULT '{}',
            PRIMARY KEY (source, target, repo_path)
        );
    """)
    conn.commit()
    return conn


def save_graph(G: nx.DiGraph, repo_path: str, db_path: str) -> None:
    """Persist a NetworkX DiGraph to SQLite for the given repo_path.

    Clears any existing data for this repo_path before writing so the
    operation is idempotent (full replace, not incremental merge).

    Node attributes are stored as JSON. The ``file_path`` attribute is
    promoted to its own column so delete_nodes_for_files() can use a
    parameterized WHERE clause without JSON parsing.

    Args:
        G: DiGraph produced by graph_builder.build_graph(). Node attrs
           are expected to be plain dicts (model_dump() already called).
           ``default=str`` is used as a safety net for any non-serialisable
           values (e.g. pagerank floats are fine; numpy types are not).
        repo_path: Logical identifier for the repository (typically the
                   absolute path on disk).
        db_path: Path to the SQLite database file.
    """
    conn = _get_conn(db_path)

    # Clear existing data for this repo so the write is idempotent.
    conn.execute("DELETE FROM graph_nodes WHERE repo_path = ?", (repo_path,))
    conn.execute("DELETE FROM graph_edges WHERE repo_path = ?", (repo_path,))

    # Insert nodes
    node_rows = [
        (
            node_id,
            repo_path,
            attrs.get("file_path", ""),
            json.dumps(attrs, default=str),
        )
        for node_id, attrs in G.nodes(data=True)
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO graph_nodes (node_id, repo_path, file_path, attrs_json) "
        "VALUES (?, ?, ?, ?)",
        node_rows,
    )

    # Insert edges
    edge_rows = [
        (
            u,
            v,
            repo_path,
            json.dumps(edge_attrs, default=str),
        )
        for u, v, edge_attrs in G.edges(data=True)
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO graph_edges (source, target, repo_path, attrs_json) "
        "VALUES (?, ?, ?, ?)",
        edge_rows,
    )

    conn.commit()
    conn.close()


def delete_graph_for_repo(repo_path: str, db_path: str) -> None:
    """Remove all graph_nodes and graph_edges rows for the given repo_path.

    Args:
        repo_path: Repository identifier used to scope the delete.
        db_path: Path to the SQLite database file.
    """
    conn = _get_conn(db_path)
    conn.execute("DELETE FROM graph_nodes WHERE repo_path = ?", (repo_path,))
    conn.execute("DELETE FROM graph_edges WHERE repo_path = ?", (repo_path,))
    conn.commit()
    conn.close()


def load_graph(repo_path: str, db_path: str) -> nx.DiGraph:
    """Reconstruct a DiGraph from SQLite for the given repo_path.

    Args:
        repo_path: Logical identifier for the repository used when saving.
        db_path: Path to the SQLite database file.

    Returns:
        nx.DiGraph with all stored node attributes and edges restored.
        Returns an empty DiGraph if no data exists for repo_path.
    """
    conn = _get_conn(db_path)
    G = nx.DiGraph()

    for row in conn.execute(
        "SELECT node_id, attrs_json FROM graph_nodes WHERE repo_path = ?",
        (repo_path,),
    ):
        G.add_node(row["node_id"], **json.loads(row["attrs_json"]))

    for row in conn.execute(
        "SELECT source, target, attrs_json FROM graph_edges WHERE repo_path = ?",
        (repo_path,),
    ):
        G.add_edge(row["source"], row["target"], **json.loads(row["attrs_json"]))

    conn.close()
    return G


def delete_nodes_for_files(file_paths: list[str], repo_path: str, db_path: str) -> None:
    """Remove nodes whose file_path matches any entry in file_paths, plus their edges.

    This supports incremental re-indexing: caller deletes stale nodes for
    modified/deleted files, then rebuilds and saves the new nodes.

    Args:
        file_paths: List of file_path values to remove (e.g. ["src/auth.py"]).
                    No-op if the list is empty.
        repo_path: Repository identifier used to scope the delete.
        db_path: Path to the SQLite database file.
    """
    if not file_paths:
        return

    conn = _get_conn(db_path)

    # Build parameterized placeholders for the IN clause
    placeholders = ", ".join("?" * len(file_paths))

    # Find all node_ids that belong to the files being deleted
    rows = conn.execute(
        f"SELECT node_id FROM graph_nodes "
        f"WHERE repo_path = ? AND file_path IN ({placeholders})",
        [repo_path, *file_paths],
    ).fetchall()

    node_ids = [row["node_id"] for row in rows]

    if node_ids:
        node_placeholders = ", ".join("?" * len(node_ids))
        # Delete incident edges (source or target in the affected set)
        conn.execute(
            f"DELETE FROM graph_edges "
            f"WHERE repo_path = ? AND ("
            f"  source IN ({node_placeholders}) OR "
            f"  target IN ({node_placeholders})"
            f")",
            [repo_path, *node_ids, *node_ids],
        )

    # Delete the nodes themselves (by file_path, not node_id — consistent with spec)
    conn.execute(
        f"DELETE FROM graph_nodes "
        f"WHERE repo_path = ? AND file_path IN ({placeholders})",
        [repo_path, *file_paths],
    )

    conn.commit()
    conn.close()
