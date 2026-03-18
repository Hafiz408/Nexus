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
