# Phase 2: File Walker - Research

**Researched:** 2026-03-18
**Domain:** Python file system traversal with gitignore-aware filtering
**Confidence:** HIGH

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| WALK-01 | `walk_repo(repo_path, languages)` returns list of `{path, language, size_kb}` dicts | `os.walk` + `pathlib.Path.stat()` for size; dict construction is stdlib only |
| WALK-02 | Respects `.gitignore` at repo root and nested directories (via pathspec) | `pathspec.GitIgnoreSpec.from_lines()` + per-directory spec stacking during `os.walk` |
| WALK-03 | Skips directories: `.git`, `node_modules`, `__pycache__`, `.venv`, `venv`, `dist`, `build`, `.next`, `coverage`, `*.egg-info` | `dirs[:] = [d for d in dirs if d not in SKIP_DIRS]` inline during `os.walk` |
| WALK-04 | Skips files larger than `settings.max_file_size_kb` (default 500 KB) | `Path.stat().st_size / 1024` compared against `settings.max_file_size_kb` |
| WALK-05 | Detects language per file extension (`.py` → python; `.ts/.tsx/.js/.jsx` → typescript) | Extension-to-language dict lookup via `Path.suffix` |
| WALK-06 | Unit tests pass with synthetic temp directory fixture | `pytest` `tmp_path` fixture creates isolated real directories; no mocking needed |
| TEST-02 | `tests/test_file_walker.py` — gitignore, skip dirs, extension filtering with temp dir fixture | Same `tmp_path` pattern; separate test cases per scenario |
</phase_requirements>

---

## Summary

Phase 2 implements `walk_repo()` — a Python function that traverses a code repository, returns qualifying source files as structured dicts, and correctly excludes noise (git-ignored files, heavy directories, oversized files). The core complexity is gitignore-aware traversal: `.gitignore` files can be nested at any depth and their patterns scope to the directory they live in. The standard Python solution is `pathspec` (v1.0.4, supports Python 3.11+), which is already present in the environment and provides `GitIgnoreSpec` for full git-compatible pattern matching.

The traversal engine itself is stdlib `os.walk`. The key technique is in-place mutation of the `dirs` list during traversal (`dirs[:] = [...]`) to prune entire subtrees early — this is more efficient than filtering results after the fact and prevents descending into `node_modules` or `.git` altogether. For nested `.gitignore` support, a spec-stack is maintained per directory as the walk descends.

Testing uses pytest's built-in `tmp_path` fixture which provides a real, isolated `pathlib.Path` directory cleaned up automatically after each test. No mocking of the file system is needed or desired — real directory fixtures give higher fidelity and are the standard approach for file-walker tests.

**Primary recommendation:** Use `pathspec.GitIgnoreSpec` (not `PathSpec`) for gitignore parsing; use `os.walk` with in-place `dirs[:]` pruning for traversal; use `pytest` `tmp_path` to create synthetic repo trees in tests.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `pathspec` | 1.0.4 | Parse and match `.gitignore` patterns | Explicitly named in WALK-02; only mature library that fully replicates Git's gitignore semantics including edge cases; already installed in environment |
| `os` (stdlib) | Python 3.11 | `os.walk()` for directory traversal | Battle-tested; `dirs[:]` in-place mutation trick enables efficient subtree pruning |
| `pathlib` (stdlib) | Python 3.11 | `Path.stat().st_size`, `Path.suffix` | Cleaner path API than string manipulation; `st_size` needed for WALK-04 |
| `pytest` | latest | Test framework with `tmp_path` fixture | Provides real isolated temp directories; modern standard (not `tmpdir`) |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pydantic-settings` | >=2.0.0 | Access `settings.max_file_size_kb` | Already in project; use `get_settings()` singleton to read config |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `pathspec.GitIgnoreSpec` | `pathspec.PathSpec('gitignore', ...)` | `GitIgnoreSpec` more accurately replicates Git edge cases (allow-in-excluded-dir pattern); prefer `GitIgnoreSpec` for correctness |
| `os.walk` | `pathlib.Path.walk()` | `Path.walk()` added in Python 3.12 only; project targets Python 3.11 — use `os.walk` |
| `os.walk` | `glob.glob` / `Path.rglob` | `rglob` cannot prune subtrees mid-traversal; `os.walk` is the only option that supports `dirs[:]` pruning |

**Installation:**
```bash
pip install pathspec
```
(Already present in the environment at v1.0.4 — add to `requirements.txt`.)

---

## Architecture Patterns

### Recommended Module Location
```
backend/
└── app/
    └── ingestion/
        ├── __init__.py
        ├── walker.py        # walk_repo() function lives here
        └── ...
backend/
└── tests/
    └── test_file_walker.py  # TEST-02
```

### Pattern 1: In-Place `dirs[:]` Pruning for Subtree Exclusion
**What:** Mutate `dirs` list in-place during `os.walk` to prevent descending into excluded directories entirely.
**When to use:** Any time you need to skip whole subtrees (noise dirs, gitignored dirs). Do this BEFORE any file processing in each iteration.
**Example:**
```python
# Source: https://docs.python.org/3/library/os.html#os.walk
SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".next", "coverage",
}

for root, dirs, files in os.walk(repo_path):
    # Prune noise directories first — prevents all descent
    dirs[:] = [
        d for d in dirs
        if d not in SKIP_DIRS and not d.endswith(".egg-info")
    ]
    # ... then filter files
```

### Pattern 2: GitIgnoreSpec Stack for Nested `.gitignore` Support
**What:** Load each `.gitignore` encountered during traversal and stack it with the parent specs. A file is excluded if ANY applicable spec matches it.
**When to use:** WALK-02 requires nested `.gitignore` respect.
**Example:**
```python
# Source: pathspec official docs https://python-path-specification.readthedocs.io/en/stable/readme.html
import pathspec
from pathlib import Path

def _load_gitignore_specs(repo_path: str) -> dict[str, pathspec.GitIgnoreSpec]:
    """Pre-load all .gitignore specs keyed by their directory."""
    specs = {}
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        if ".gitignore" in files:
            gitignore_path = Path(root) / ".gitignore"
            with open(gitignore_path, "r", encoding="utf-8", errors="ignore") as f:
                specs[root] = pathspec.GitIgnoreSpec.from_lines(f)
    return specs

def _is_gitignored(file_path: str, repo_path: str, specs: dict) -> bool:
    """Check if file_path is ignored by any applicable .gitignore."""
    p = Path(file_path)
    for spec_dir, spec in specs.items():
        # Spec applies to files under its directory
        try:
            relative = p.relative_to(spec_dir)
            if spec.match_file(str(relative)):
                return True
        except ValueError:
            pass
    return False
```

### Pattern 3: Language Detection via Extension Map
**What:** A simple dict lookup from `Path.suffix` to language string.
**When to use:** WALK-05 requires `.py` → `"python"` and `.ts/.tsx/.js/.jsx` → `"typescript"`.
**Example:**
```python
EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "typescript",
    ".jsx": "typescript",
}

suffix = Path(file_name).suffix.lower()
language = EXTENSION_TO_LANGUAGE.get(suffix)
if language is None:
    continue  # skip unsupported extensions
```

### Pattern 4: pytest `tmp_path` Synthetic Repo Fixture
**What:** Use pytest's built-in `tmp_path` fixture to create real files and directories in a per-test temp location. No mocking.
**When to use:** TEST-02 — gitignore, skip dirs, extension filtering tests.
**Example:**
```python
# Source: https://docs.pytest.org/en/stable/how-to/tmp_path.html
def test_skips_node_modules(tmp_path):
    # Create synthetic repo structure
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "index.ts").write_text("export const x = 1;")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "lodash" / "index.js").mkdir(parents=True)

    results = walk_repo(str(tmp_path), languages=["typescript"])
    paths = [r["path"] for r in results]

    assert not any("node_modules" in p for p in paths)
    assert any("index.ts" in p for p in paths)

def test_respects_gitignore(tmp_path):
    (tmp_path / ".gitignore").write_text("*.log\nbuild/\n")
    (tmp_path / "app.py").write_text("print('hello')")
    (tmp_path / "debug.log").write_text("log data")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "output.py").write_text("built")

    results = walk_repo(str(tmp_path), languages=["python"])
    paths = [r["path"] for r in results]

    assert any("app.py" in p for p in paths)
    assert not any(".log" in p for p in paths)
    assert not any("build" in p for p in paths)
```

### Anti-Patterns to Avoid
- **Do not use `dirs.remove()` in a loop:** Mutating the list while iterating it causes items to be skipped. Use `dirs[:] = [...]` slice assignment instead.
- **Do not use `Path.rglob('**/*.py')`:** Cannot prune subtrees mid-traversal; will descend into `node_modules` etc. before you can filter.
- **Do not use `pathspec.PathSpec.from_lines('gitignore', ...)`:** Use `GitIgnoreSpec.from_lines()` instead — `PathSpec` with `'gitignore'` factory misses some edge-case git behaviors.
- **Do not call `Path.stat()` on every file unconditionally before extension check:** Check extension first, then stat only qualifying files — avoids unnecessary syscalls.
- **Do not use `tmpdir` pytest fixture:** Deprecated; use `tmp_path` (returns `pathlib.Path`) instead.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Gitignore pattern parsing | Custom regex for `*.log`, `build/`, `!important` negation | `pathspec.GitIgnoreSpec` | Gitignore has complex semantics: negation rules, trailing slash directory matching, `**` globbing, character classes. Hand-rolled parsers miss edge cases. |
| Nested `.gitignore` scoping | Manual path-prefix checks | `pathspec.GitIgnoreSpec` + relative path comparison | Git scopes each `.gitignore` to its directory; relative path math must be correct or files from other dirs get incorrectly filtered |
| File size in KB | `os.path.getsize` + division | `Path.stat().st_size / 1024` | Same result; `pathlib` is cleaner and already in use |

**Key insight:** The gitignore format has 15+ special cases in the git documentation. `pathspec` has been battle-tested against git's actual behavior. Any custom parser will fail on real-world repos within weeks.

---

## Common Pitfalls

### Pitfall 1: Using `GitIgnoreSpec.match_file()` with Absolute Paths
**What goes wrong:** `spec.match_file("/absolute/path/to/file.py")` always returns `False` — patterns in `.gitignore` are relative to the directory containing the `.gitignore`.
**Why it happens:** Pathspec compares the pattern against the path string as given; absolute paths never match relative patterns.
**How to avoid:** Always pass the path relative to the `.gitignore`'s directory: `spec.match_file(str(Path(file_path).relative_to(spec_dir)))`.
**Warning signs:** All gitignore tests pass with empty `.gitignore` but fail when patterns are added.

### Pitfall 2: Not Pruning `dirs[:]` Before gitignore Check
**What goes wrong:** You check gitignore patterns on all files found, but you've already descended into `node_modules` (10,000+ files), making the walk slow.
**Why it happens:** `os.walk` descends into all dirs unless you prune `dirs` before the next iteration.
**How to avoid:** Apply the hard SKIP_DIRS exclusion on `dirs[:]` at the top of each loop iteration, before any gitignore check.
**Warning signs:** Walk takes >1 second on a repo that has `node_modules`.

### Pitfall 3: `.egg-info` Directory Matching
**What goes wrong:** WALK-03 requires `*.egg-info` skipping, but `*.egg-info` is a glob pattern, not a literal name — you cannot put it in a `set` and do `d in SKIP_DIRS`.
**Why it happens:** Treating all exclusion patterns as set membership checks ignores glob patterns.
**How to avoid:** Check literal names with `in SKIP_DIRS` set, then add a separate `d.endswith(".egg-info")` check in the same filter expression.
**Warning signs:** Directories like `my_package.egg-info` appear in results.

### Pitfall 4: `size_kb` Float Precision
**What goes wrong:** `st_size / 1024` returns a float with many decimal places; downstream code may expect clean values.
**Why it happens:** Integer division in Python 3 always returns float with `/`.
**How to avoid:** Use `round(path.stat().st_size / 1024, 2)` or keep as float — just be consistent. WALK-04 only requires skipping files exceeding the limit, so truncation is acceptable.

### Pitfall 5: `tmp_path` Fixture Scope in conftest
**What goes wrong:** Using `tmp_path_factory` when you mean `tmp_path`, or sharing a mutable temp dir across tests via session scope.
**Why it happens:** `tmp_path` is function-scoped (new dir per test); `tmp_path_factory` is session-scoped (shared).
**How to avoid:** Use `tmp_path` for isolation (one dir per test). If a shared synthetic repo fixture is needed in `conftest.py`, use `tmp_path_factory` and treat it as read-only.

### Pitfall 6: Missing `__init__.py` in `ingestion/` Module
**What goes wrong:** `from app.ingestion.walker import walk_repo` raises `ModuleNotFoundError`.
**Why it happens:** Python requires `__init__.py` for namespace packages unless the project uses implicit namespace packages.
**How to avoid:** Create `backend/app/ingestion/__init__.py` alongside `walker.py`.

---

## Code Examples

Verified patterns from official sources:

### Full `walk_repo()` Skeleton
```python
# Source: pathspec docs https://python-path-specification.readthedocs.io/en/stable/readme.html
# + Python stdlib os.walk https://docs.python.org/3/library/os.html#os.walk
import os
from pathlib import Path
from typing import TypedDict
import pathspec

SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".next", "coverage",
}

EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "typescript",
    ".jsx": "typescript",
}

class FileEntry(TypedDict):
    path: str
    language: str
    size_kb: float

def walk_repo(
    repo_path: str,
    languages: list[str],
    max_file_size_kb: float = 500.0,
) -> list[FileEntry]:
    repo_root = Path(repo_path).resolve()
    results: list[FileEntry] = []

    # Pre-load all .gitignore specs keyed by their directory (absolute path str)
    gitignore_specs: dict[str, pathspec.GitIgnoreSpec] = {}
    for root, dirs, files in os.walk(str(repo_root)):
        dirs[:] = [
            d for d in dirs
            if d not in SKIP_DIRS and not d.endswith(".egg-info")
        ]
        if ".gitignore" in files:
            gi_path = Path(root) / ".gitignore"
            with open(gi_path, "r", encoding="utf-8", errors="ignore") as f:
                gitignore_specs[root] = pathspec.GitIgnoreSpec.from_lines(f)

    # Main traversal
    for root, dirs, files in os.walk(str(repo_root)):
        dirs[:] = [
            d for d in dirs
            if d not in SKIP_DIRS and not d.endswith(".egg-info")
        ]

        for file_name in files:
            suffix = Path(file_name).suffix.lower()
            language = EXTENSION_TO_LANGUAGE.get(suffix)
            if language is None or language not in languages:
                continue

            full_path = Path(root) / file_name

            # Check gitignore
            if _is_gitignored(full_path, gitignore_specs):
                continue

            # Check size
            size_bytes = full_path.stat().st_size
            size_kb = size_bytes / 1024
            if size_kb > max_file_size_kb:
                continue

            results.append({
                "path": str(full_path),
                "language": language,
                "size_kb": round(size_kb, 2),
            })

    return results

def _is_gitignored(
    file_path: Path,
    specs: dict[str, pathspec.GitIgnoreSpec],
) -> bool:
    for spec_dir_str, spec in specs.items():
        spec_dir = Path(spec_dir_str)
        try:
            relative = file_path.relative_to(spec_dir)
            if spec.match_file(str(relative)):
                return True
        except ValueError:
            continue
    return False
```

### Minimal `conftest.py` for Phase 2 Tests
```python
# Source: https://docs.pytest.org/en/stable/how-to/tmp_path.html
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
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `pathspec.PathSpec.from_lines('gitwildmatch', ...)` | `pathspec.GitIgnoreSpec.from_lines(...)` | pathspec ~0.10 | `GitIgnoreSpec` is now the correct class for gitignore; `gitwildmatch` factory name still works but `gitignore` is preferred |
| `tmpdir` pytest fixture | `tmp_path` pytest fixture | pytest 3.9 | `tmp_path` returns `pathlib.Path`; `tmpdir` is deprecated |
| `pathlib.Path.walk()` | Only available in Python 3.12+; project targets 3.11 so use `os.walk` | Python 3.12 | Cannot use `Path.walk()` until project upgrades to 3.12 |

**Deprecated/outdated:**
- `tmpdir` pytest fixture: deprecated, use `tmp_path` instead (returns `pathlib.Path`)
- `pathspec.PathSpec.from_lines('gitwildmatch', ...)`: still works but `GitIgnoreSpec.from_lines()` is preferred for correctness

---

## Open Questions

1. **Two-pass vs single-pass `os.walk` for gitignore + file collection**
   - What we know: The skeleton above does two passes (one to find `.gitignore` files, one to collect files). This is simple and correct but traverses the tree twice.
   - What's unclear: Whether a single-pass approach (building gitignore spec on-the-fly as dirs are entered) would be materially faster for large repos.
   - Recommendation: Use two-pass for simplicity. For repos up to tens of thousands of files, the overhead is negligible. Can optimize in a later phase if profiling shows it as a bottleneck.

2. **Return absolute vs relative paths in `{path}` field**
   - What we know: WALK-01 says `{path, language, size_kb}` without specifying absolute vs relative.
   - What's unclear: Phase 3 (AST Parser) will consume these paths — it needs to know whether paths are absolute or relative to `repo_root`.
   - Recommendation: Return absolute paths in `walk_repo()` for unambiguous downstream use. Phase 3 can compute `relative_to(repo_root)` when needed for node IDs.

3. **`pathspec` not in `requirements.txt` yet**
   - What we know: `pathspec` 1.0.4 is already installed in the environment but is not listed in `backend/requirements.txt`.
   - What's unclear: Whether it was installed as a transitive dependency.
   - Recommendation: Explicitly add `pathspec>=1.0.0` to `requirements.txt` as part of Phase 2.

---

## Sources

### Primary (HIGH confidence)
- `pathspec` PyPI page (v1.0.4, released 2026-01-27) — version, Python 3.11 support confirmed: https://pypi.org/project/pathspec/
- pathspec official API docs — `GitIgnoreSpec.from_lines()`, `match_file()`, `match_tree_files()`: https://python-path-specification.readthedocs.io/en/latest/api.html
- pathspec stable README — usage patterns, `GitIgnoreSpec` vs `PathSpec` distinction: https://python-path-specification.readthedocs.io/en/stable/readme.html
- Python 3.11 stdlib `os.walk` — `dirs[:]` in-place mutation pattern: https://docs.python.org/3/library/os.html#os.walk
- pytest official docs — `tmp_path` fixture (function-scoped, `pathlib.Path`): https://docs.pytest.org/en/stable/how-to/tmp_path.html

### Secondary (MEDIUM confidence)
- cpburnz/python-pathspec GitHub — `gitignore.py` source confirms `GitIgnoreSpec` rejects `GitIgnoreBasicPattern`: https://github.com/cpburnz/python-pathspec/blob/master/pathspec/gitignore.py
- Python.org discussion confirming `Path.walk()` added in Python 3.12: https://discuss.python.org/t/add-pathlib-path-walk-method/12968

### Tertiary (LOW confidence)
- None — all critical claims verified against official sources.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — `pathspec` is explicitly named in WALK-02; version confirmed from PyPI; all stdlib tools
- Architecture: HIGH — patterns derived from official pathspec and pytest docs; `dirs[:]` idiom from Python stdlib docs
- Pitfalls: HIGH — absolute-vs-relative path pitfall is documented behavior from pathspec API; `dirs[:]` mutation is stdlib-documented; `.egg-info` glob vs literal is a logical consequence of the requirement text

**Research date:** 2026-03-18
**Valid until:** 2026-04-18 (pathspec is stable; `tmp_path` is stable; no fast-moving dependencies)
