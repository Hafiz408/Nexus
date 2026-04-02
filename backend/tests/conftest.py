import pytest
from pathlib import Path
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Patch _check_sqlite_vec for all tests that spin up the FastAPI app via
# TestClient.  The check guards production users against a broken Python
# build; it must not prevent the test suite from running on a dev machine
# whose Python was built without --enable-loadable-sqlite-extensions.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _skip_sqlite_vec_check():
    with patch("app.main._check_sqlite_vec", return_value=None):
        yield


@pytest.fixture
def sample_repo_path(tmp_path: Path) -> Path:
    """Minimal synthetic Python+TypeScript repo for walker tests."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def hello(): pass")
    (tmp_path / "src" / "app.ts").write_text("export const x = 1;")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "pkg").mkdir()
    (tmp_path / "node_modules" / "pkg" / "index.js").write_text("module.exports = {}")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "main.cpython-311.pyc").write_bytes(b"fake")
    return tmp_path


@pytest.fixture
def python_sample_file(tmp_path: Path) -> tuple[Path, Path]:
    """Returns (file_path, repo_root). File has 2 functions + 1 class + 1 method."""
    repo = tmp_path / "repo"
    repo.mkdir()
    content = '''def standalone_function(x: int) -> int:
    """A standalone function."""
    return x * 2


def another_function(name: str) -> str:
    """Another standalone function."""
    if name:
        return f"Hello {name}"
    return "Hello"


class MyClass:
    """A sample class."""

    def method_one(self):
        """First method."""
        result = standalone_function(42)
        return result
'''
    f = repo / "sample.py"
    f.write_text(content)
    return f, repo


@pytest.fixture
def typescript_sample_file(tmp_path: Path) -> tuple[Path, Path]:
    """Returns (file_path, repo_root). File has function, class, method, arrow function."""
    repo = tmp_path / "repo"
    repo.mkdir()
    content = '''import { helper } from "./utils";

export function greet(name: string): string {
    return `Hello, ${name}`;
}

export class UserService {
    private name: string;

    constructor(name: string) {
        this.name = name;
    }

    getName(): string {
        return this.name;
    }
}

const formatUser = (user: UserService): string => {
    return user.getName();
};
'''
    f = repo / "service.ts"
    f.write_text(content)
    return f, repo


@pytest.fixture
def sample_nodes() -> list:
    """Three CodeNode objects: two functions in file_a.py, one function in file_b.py."""
    from app.models.schemas import CodeNode
    return [
        CodeNode(
            node_id="file_a.py::caller",
            name="caller",
            type="function",
            file_path="/repo/file_a.py",
            line_start=1,
            line_end=5,
            signature="def caller():",
            docstring="Calls helper.",
            body_preview="helper()",
            complexity=1,
            embedding_text="def caller():\nCalls helper.\nhelper()",
        ),
        CodeNode(
            node_id="file_a.py::helper",
            name="helper",
            type="function",
            file_path="/repo/file_a.py",
            line_start=7,
            line_end=10,
            signature="def helper():",
            docstring="",
            body_preview="pass",
            complexity=0,
            embedding_text="def helper():\n\npass",
        ),
        CodeNode(
            node_id="file_b.py::target",
            name="target",
            type="function",
            file_path="/repo/file_b.py",
            line_start=1,
            line_end=3,
            signature="def target():",
            docstring="",
            body_preview="pass",
            complexity=0,
            embedding_text="def target():\n\npass",
        ),
    ]


@pytest.fixture
def sample_raw_edges() -> list:
    """One CALLS edge (resolvable) and one IMPORTS edge (synthetic __module__ source)."""
    return [
        ("file_a.py::caller", "helper", "CALLS"),
        ("file_a.py::__module__", "file_b", "IMPORTS"),
    ]


import numpy as np
import networkx as nx


@pytest.fixture
def sample_graph() -> nx.DiGraph:
    """5-node DiGraph with known topology.

    Topology:
      a.py::func_a -> b.py::func_b (CALLS)
      b.py::func_b -> c.py::func_c (CALLS)
      d.py::func_d -> b.py::func_b (CALLS)
      e.py::func_e  (isolated)

    PageRank and in_degree pre-computed for deterministic reranking tests.
    """
    G = nx.DiGraph()
    nodes = [
        {"node_id": "a.py::func_a", "name": "func_a", "type": "function",
         "file_path": "/repo/a.py", "line_start": 1, "line_end": 5,
         "signature": "def func_a():", "docstring": None, "body_preview": "pass",
         "complexity": 1, "embedding_text": "def func_a():",
         "pagerank": 0.15, "in_degree": 0, "out_degree": 1},
        {"node_id": "b.py::func_b", "name": "func_b", "type": "function",
         "file_path": "/repo/b.py", "line_start": 1, "line_end": 5,
         "signature": "def func_b():", "docstring": None, "body_preview": "pass",
         "complexity": 1, "embedding_text": "def func_b():",
         "pagerank": 0.25, "in_degree": 2, "out_degree": 1},
        {"node_id": "c.py::func_c", "name": "func_c", "type": "function",
         "file_path": "/repo/c.py", "line_start": 1, "line_end": 5,
         "signature": "def func_c():", "docstring": None, "body_preview": "pass",
         "complexity": 1, "embedding_text": "def func_c():",
         "pagerank": 0.30, "in_degree": 1, "out_degree": 0},
        {"node_id": "d.py::func_d", "name": "func_d", "type": "function",
         "file_path": "/repo/d.py", "line_start": 1, "line_end": 5,
         "signature": "def func_d():", "docstring": None, "body_preview": "pass",
         "complexity": 1, "embedding_text": "def func_d():",
         "pagerank": 0.15, "in_degree": 0, "out_degree": 1},
        {"node_id": "e.py::func_e", "name": "func_e", "type": "function",
         "file_path": "/repo/e.py", "line_start": 1, "line_end": 5,
         "signature": "def func_e():", "docstring": None, "body_preview": "pass",
         "complexity": 1, "embedding_text": "def func_e():",
         "pagerank": 0.10, "in_degree": 0, "out_degree": 0},
    ]
    for n in nodes:
        G.add_node(n["node_id"], **n)
    G.add_edge("a.py::func_a", "b.py::func_b", type="CALLS")
    G.add_edge("b.py::func_b", "c.py::func_c", type="CALLS")
    G.add_edge("d.py::func_d", "b.py::func_b", type="CALLS")
    return G


@pytest.fixture
def mock_embedder(monkeypatch):
    """Patches get_embedding_client at the graph_rag call site — no API key or DB needed.

    Uses np.random.seed(42) for reproducible 1024-d vectors.
    Patching at the factory call site makes tests provider-agnostic.
    """
    from unittest.mock import MagicMock

    np.random.seed(42)

    mock_client = MagicMock()
    mock_client.embed.side_effect = lambda texts: [
        np.random.rand(1024).tolist() for _ in texts
    ]
    mock_client.dimensions = 1024
    monkeypatch.setattr("app.retrieval.graph_rag.get_embedding_client", lambda: mock_client)
    return mock_client
