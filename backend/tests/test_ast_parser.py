import pytest
from pathlib import Path
from app.ingestion.ast_parser import parse_file


class TestPythonParsing:
    def test_returns_correct_node_count(self, python_sample_file):
        file_path, repo_root = python_sample_file
        nodes, edges = parse_file(str(file_path), str(repo_root), "python")
        assert len(nodes) == 4  # 2 functions + 1 class + 1 method

    def test_node_id_format(self, python_sample_file):
        file_path, repo_root = python_sample_file
        nodes, _ = parse_file(str(file_path), str(repo_root), "python")
        node_ids = {n.node_id for n in nodes}
        assert "sample.py::standalone_function" in node_ids

    def test_docstring_extraction(self, python_sample_file):
        file_path, repo_root = python_sample_file
        nodes, _ = parse_file(str(file_path), str(repo_root), "python")
        func_node = next(n for n in nodes if n.name == "standalone_function")
        assert func_node.docstring == "A standalone function."

    def test_class_node(self, python_sample_file):
        file_path, repo_root = python_sample_file
        nodes, _ = parse_file(str(file_path), str(repo_root), "python")
        class_node = next(n for n in nodes if n.name == "MyClass")
        assert class_node.type == "class"
        assert class_node.docstring == "A sample class."

    def test_method_node(self, python_sample_file):
        file_path, repo_root = python_sample_file
        nodes, _ = parse_file(str(file_path), str(repo_root), "python")
        method_node = next(n for n in nodes if n.name == "method_one")
        assert method_node.type == "method"
        assert method_node.node_id == "sample.py::method_one"

    def test_complexity_minimum_one(self, python_sample_file):
        file_path, repo_root = python_sample_file
        nodes, _ = parse_file(str(file_path), str(repo_root), "python")
        assert all(n.complexity >= 1 for n in nodes)

    def test_body_preview_max_300_chars(self, python_sample_file):
        file_path, repo_root = python_sample_file
        nodes, _ = parse_file(str(file_path), str(repo_root), "python")
        assert all(len(n.body_preview) <= 300 for n in nodes)

    def test_embedding_text_format(self, python_sample_file):
        file_path, repo_root = python_sample_file
        nodes, _ = parse_file(str(file_path), str(repo_root), "python")
        func_node = next(n for n in nodes if n.name == "standalone_function")
        assert func_node.signature in func_node.embedding_text
        assert (func_node.docstring or "") in func_node.embedding_text

    def test_calls_edge_detected(self, python_sample_file):
        file_path, repo_root = python_sample_file
        nodes, edges = parse_file(str(file_path), str(repo_root), "python")
        calls_edges = [(s, t, et) for s, t, et in edges if et == "CALLS"]
        target_names = [t for _, t, _ in calls_edges]
        assert "standalone_function" in target_names

    def test_node_id_uses_forward_slashes(self, tmp_path):
        repo = tmp_path / "repo"
        subdir = repo / "pkg"
        subdir.mkdir(parents=True)
        f = subdir / "mod.py"
        f.write_text("def foo(): pass\n")
        nodes, _ = parse_file(str(f), str(repo), "python")
        assert len(nodes) == 1
        assert "\\" not in nodes[0].node_id


class TestTypeScriptParsing:
    def test_function_declaration_extracted(self, typescript_sample_file):
        file_path, repo_root = typescript_sample_file
        nodes, _ = parse_file(str(file_path), str(repo_root), "typescript")
        names = {n.name for n in nodes}
        assert "greet" in names

    def test_class_declaration_extracted(self, typescript_sample_file):
        file_path, repo_root = typescript_sample_file
        nodes, _ = parse_file(str(file_path), str(repo_root), "typescript")
        class_node = next((n for n in nodes if n.name == "UserService"), None)
        assert class_node is not None
        assert class_node.type == "class"

    def test_method_definition_extracted(self, typescript_sample_file):
        file_path, repo_root = typescript_sample_file
        nodes, _ = parse_file(str(file_path), str(repo_root), "typescript")
        names = {n.name for n in nodes}
        assert "getName" in names

    def test_arrow_function_extracted(self, typescript_sample_file):
        file_path, repo_root = typescript_sample_file
        nodes, _ = parse_file(str(file_path), str(repo_root), "typescript")
        names = {n.name for n in nodes}
        assert "formatUser" in names

    def test_typescript_nodes_have_signature(self, typescript_sample_file):
        file_path, repo_root = typescript_sample_file
        nodes, _ = parse_file(str(file_path), str(repo_root), "typescript")
        assert all(len(n.signature) > 0 for n in nodes)


class TestClassContainsEdges:
    def test_class_contains_edge_emitted_python(self, python_sample_file):
        """CLASS_CONTAINS edge emitted from class → method for Python."""
        file_path, repo_root = python_sample_file
        _, edges = parse_file(str(file_path), str(repo_root), "python")
        cc_edges = [(s, t, et) for s, t, et in edges if et == "CLASS_CONTAINS"]
        assert len(cc_edges) >= 1

    def test_class_contains_source_is_class(self, python_sample_file):
        """CLASS_CONTAINS source node_id references the class, not the method."""
        file_path, repo_root = python_sample_file
        _, edges = parse_file(str(file_path), str(repo_root), "python")
        cc_edges = [(s, t, et) for s, t, et in edges if et == "CLASS_CONTAINS"]
        sources = {s for s, _, _ in cc_edges}
        assert any("MyClass" in s for s in sources)

    def test_class_contains_target_is_method(self, python_sample_file):
        """CLASS_CONTAINS target node_id references the method."""
        file_path, repo_root = python_sample_file
        _, edges = parse_file(str(file_path), str(repo_root), "python")
        cc_edges = [(s, t, et) for s, t, et in edges if et == "CLASS_CONTAINS"]
        targets = {t for _, t, _ in cc_edges}
        assert any("method_one" in t for t in targets)

    def test_standalone_function_no_class_contains(self, python_sample_file):
        """Functions outside a class do not get CLASS_CONTAINS edges."""
        file_path, repo_root = python_sample_file
        _, edges = parse_file(str(file_path), str(repo_root), "python")
        cc_edges = [(s, t, et) for s, t, et in edges if et == "CLASS_CONTAINS"]
        targets = {t for _, t, _ in cc_edges}
        assert not any("standalone_function" in t for t in targets)
        assert not any("another_function" in t for t in targets)

    def test_class_contains_emitted_typescript(self, typescript_sample_file):
        """CLASS_CONTAINS edge emitted from TS class → method."""
        file_path, repo_root = typescript_sample_file
        _, edges = parse_file(str(file_path), str(repo_root), "typescript")
        cc_edges = [(s, t, et) for s, t, et in edges if et == "CLASS_CONTAINS"]
        assert len(cc_edges) >= 1
        sources = {s for s, _, _ in cc_edges}
        targets = {t for _, t, _ in cc_edges}
        assert any("UserService" in s for s in sources)
        assert any("getName" in t for t in targets)


class TestEdgeCases:
    def test_unsupported_language_returns_empty(self, tmp_path):
        f = tmp_path / "code.rb"
        f.write_text("def hello; end\n")
        nodes, edges = parse_file(str(f), str(tmp_path), "ruby")
        assert nodes == []
        assert edges == []

    def test_empty_python_file_returns_empty(self, tmp_path):
        f = tmp_path / "empty.py"
        f.write_text("")
        nodes, edges = parse_file(str(f), str(tmp_path), "python")
        assert nodes == []
        assert edges == []
