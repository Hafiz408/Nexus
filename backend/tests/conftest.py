import pytest
from pathlib import Path


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
