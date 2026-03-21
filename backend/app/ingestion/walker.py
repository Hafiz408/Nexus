import logging
import os
from pathlib import Path
from typing import TypedDict

import pathspec

logger = logging.getLogger(__name__)

SKIP_DIRS: set[str] = {
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


def _is_gitignored(
    file_path: Path,
    specs: dict[str, pathspec.GitIgnoreSpec],
) -> bool:
    """Return True if file_path is matched by any applicable .gitignore spec."""
    for spec_dir_str, spec in specs.items():
        spec_dir = Path(spec_dir_str)
        try:
            relative = file_path.relative_to(spec_dir)
            if spec.match_file(str(relative)):
                return True
        except ValueError:
            continue
    return False


def walk_repo(
    repo_path: str,
    languages: list[str],
    max_file_size_kb: float = 500.0,
) -> list[FileEntry]:
    """
    Traverse repo_path and return qualifying source files as FileEntry dicts.

    Args:
        repo_path: Absolute or relative path to the repository root.
        languages: List of languages to include (e.g. ["python", "typescript"]).
        max_file_size_kb: Files larger than this are silently dropped.

    Returns:
        List of FileEntry dicts with path (absolute), language, and size_kb.
    """
    repo_root = Path(repo_path).resolve()
    if not repo_root.exists():
        logger.error("walk_repo: path does not exist: %s", repo_root)
        return []
    results: list[FileEntry] = []

    # Pass 1: collect all .gitignore specs keyed by their directory (absolute str)
    gitignore_specs: dict[str, pathspec.GitIgnoreSpec] = {}
    for root, dirs, files in os.walk(str(repo_root)):
        dirs[:] = [
            d for d in dirs
            if d not in SKIP_DIRS and not d.endswith(".egg-info")
        ]
        if ".gitignore" in files:
            gi_path = Path(root) / ".gitignore"
            with open(gi_path, "r", encoding="utf-8", errors="ignore") as fh:
                gitignore_specs[root] = pathspec.GitIgnoreSpec.from_lines(fh)

    # Pass 2: collect qualifying files
    for root, dirs, files in os.walk(str(repo_root)):
        dirs[:] = [
            d for d in dirs
            if d not in SKIP_DIRS and not d.endswith(".egg-info")
        ]

        for file_name in files:
            # Check extension first (avoid stat syscall on unneeded files)
            suffix = Path(file_name).suffix.lower()
            language = EXTENSION_TO_LANGUAGE.get(suffix)
            if language is None or language not in languages:
                continue

            full_path = Path(root) / file_name

            # Check gitignore (pass relative path — absolute paths never match)
            if _is_gitignored(full_path, gitignore_specs):
                continue

            # Check size
            size_bytes = full_path.stat().st_size
            size_kb = round(size_bytes / 1024, 2)
            if size_kb > max_file_size_kb:
                continue

            results.append({
                "path": str(full_path),
                "language": language,
                "size_kb": size_kb,
            })

    lang_counts: dict[str, int] = {}
    for e in results:
        lang_counts[e["language"]] = lang_counts.get(e["language"], 0) + 1
    logger.info(
        "walk_repo: found %d files in %s — %s",
        len(results),
        repo_root,
        lang_counts if lang_counts else "no matching files",
    )
    return results
