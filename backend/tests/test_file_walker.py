from pathlib import Path

import pytest

from app.ingestion.walker import walk_repo


def test_returns_python_files_only(sample_repo_path):
    results = walk_repo(str(sample_repo_path), ["python"])
    assert len(results) == 1
    assert results[0]["language"] == "python"
    assert results[0]["path"].endswith("main.py")


def test_returns_typescript_files_only(sample_repo_path):
    results = walk_repo(str(sample_repo_path), ["typescript"])
    assert len(results) == 1
    assert results[0]["language"] == "typescript"
    assert results[0]["path"].endswith("app.ts")


def test_skips_node_modules(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "index.ts").write_text("export const x = 1;")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "pkg").mkdir()
    (tmp_path / "node_modules" / "pkg" / "lib.js").write_text("module.exports = {}")
    results = walk_repo(str(tmp_path), ["typescript"])
    # Check path parts to avoid false positives from the tmp_path directory name
    assert all(
        "node_modules" not in Path(r["path"]).relative_to(tmp_path.resolve()).parts
        for r in results
    )


def test_skips_pycache(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "util.py").write_text("def util(): pass")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "util.cpython-311.pyc").write_bytes(b"fake")
    results = walk_repo(str(tmp_path), ["python"])
    assert all("__pycache__" not in r["path"] for r in results)
    assert any("util.py" in r["path"] for r in results)


def test_skips_egg_info(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "util.py").write_text("def util(): pass")
    egg_info_dir = tmp_path / "my_pkg.egg-info"
    egg_info_dir.mkdir()
    (egg_info_dir / "PKG-INFO").write_text("Metadata-Version: 2.1")
    results = walk_repo(str(tmp_path), ["python"])
    assert all("egg-info" not in r["path"] for r in results)


def test_respects_root_gitignore(tmp_path):
    (tmp_path / ".gitignore").write_text("*.log\nbuild/\n")
    (tmp_path / "app.py").write_text("def app(): pass")
    (tmp_path / "debug.log").write_text("some log")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "output.py").write_text("# built file")
    results = walk_repo(str(tmp_path), ["python"])
    paths = [r["path"] for r in results]
    assert any("app.py" in p for p in paths)
    assert all(".log" not in p for p in paths)
    assert all("build" not in p for p in paths)


def test_respects_nested_gitignore(tmp_path):
    (tmp_path / "app.py").write_text("def app(): pass")
    (tmp_path / "subdir").mkdir()
    (tmp_path / "subdir" / ".gitignore").write_text("secret.py\n")
    (tmp_path / "subdir" / "main.py").write_text("def main(): pass")
    (tmp_path / "subdir" / "secret.py").write_text("SECRET = 'hidden'")
    results = walk_repo(str(tmp_path), ["python"])
    paths = [r["path"] for r in results]
    assert any("app.py" in p for p in paths)
    assert any("main.py" in p for p in paths)
    assert not any("secret.py" in p for p in paths)


def test_skips_oversized_files(tmp_path):
    (tmp_path / "big.py").write_text("x = 1" * 1000)
    results = walk_repo(str(tmp_path), ["python"], max_file_size_kb=0.001)
    assert results == []


def test_returns_absolute_paths(sample_repo_path):
    results = walk_repo(str(sample_repo_path), ["python"])
    assert all(Path(r["path"]).is_absolute() for r in results)


def test_size_kb_field(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "hello.py").write_text("def hello(): pass")
    results = walk_repo(str(tmp_path), ["python"])
    assert results[0]["size_kb"] >= 0


def test_tsx_detected_as_typescript(tmp_path):
    (tmp_path / "component.tsx").write_text("export default () => <div/>")
    results = walk_repo(str(tmp_path), ["typescript"])
    assert results[0]["language"] == "typescript"


def test_both_languages(sample_repo_path):
    results = walk_repo(str(sample_repo_path), ["python", "typescript"])
    languages = {r["language"] for r in results}
    assert "python" in languages
    assert "typescript" in languages
