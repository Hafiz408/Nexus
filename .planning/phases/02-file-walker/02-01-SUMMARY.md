---
phase: 02-file-walker
plan: 01
subsystem: ingestion
tags: [pathspec, gitignore, file-walker, python, typescript, tdd, pytest]

# Dependency graph
requires:
  - phase: 01-infrastructure
    provides: FastAPI app skeleton, backend/app/ package structure, requirements.txt baseline
provides:
  - walk_repo() function returning FileEntry dicts for qualifying source files
  - gitignore-aware two-pass traversal (root + nested .gitignore specs)
  - SKIP_DIRS noise directory pruning (node_modules, __pycache__, .venv, dist, build, etc.)
  - EXTENSION_TO_LANGUAGE mapping for python and typescript
  - 12-test suite verifying all filtering contracts
  - sample_repo_path pytest fixture (synthetic repo in tmp_path)
affects: [03-ast-parser, 04-graph-builder, 05-pipeline]

# Tech tracking
tech-stack:
  added: [pathspec>=1.0.0]
  patterns: [TDD red-green cycle, two-pass os.walk for gitignore-then-files, TypedDict for typed dict contracts]

key-files:
  created:
    - backend/app/ingestion/__init__.py
    - backend/app/ingestion/walker.py
    - backend/tests/__init__.py
    - backend/tests/conftest.py
    - backend/tests/test_file_walker.py
  modified:
    - backend/requirements.txt

key-decisions:
  - "pathspec.GitIgnoreSpec.from_lines() used (not PathSpec factory) — correct class per research for gitignore semantics"
  - "Two-pass os.walk: collect all .gitignore specs first, then filter files — ensures nested gitignore specs are loaded before checking files in subdirs"
  - "os.walk used (not Path.walk) — project targets Python 3.11; Path.walk only available in Python 3.12+"
  - "Relative paths passed to spec.match_file() — absolute paths always return False in pathspec"
  - "Extension check before stat() call — avoids unnecessary filesystem syscalls on non-target files"
  - "Test assertion fixed to use Path.parts instead of substring match — pytest tmp_path dir name can contain 'node_modules' (test_skips_node_modules0), causing false assertion failures"

patterns-established:
  - "TDD red-green: commit failing tests first, then implement to green"
  - "TypedDict for return type contracts: FileEntry with path/language/size_kb"
  - "SKIP_DIRS as module-level set for easy extension by downstream phases"
  - "EXTENSION_TO_LANGUAGE as module-level dict — single source of truth for language detection"

requirements-completed: [WALK-01, WALK-02, WALK-03, WALK-04, WALK-05, WALK-06, TEST-02]

# Metrics
duration: 3min
completed: 2026-03-18
---

# Phase 2 Plan 01: File Walker Summary

**gitignore-aware two-pass repository walker using pathspec.GitIgnoreSpec, with 12-test TDD suite covering language filtering, skip dirs, gitignore (root + nested), size limits, and absolute path output**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-18T10:47:32Z
- **Completed:** 2026-03-18T10:50:49Z
- **Tasks:** 2 (RED + GREEN)
- **Files modified:** 6

## Accomplishments
- `walk_repo(repo_path, languages, max_file_size_kb)` implemented with full filtering contract
- Noise directories pruned via `dirs[:] =` in `os.walk` — prevents descent into node_modules, __pycache__, .venv, dist, build, .next, coverage, *.egg-info
- Root and nested `.gitignore` specs collected in pass 1, applied in pass 2 using relative paths for correct pathspec matching
- 12 unit tests all passing, covering every behavior case from the plan's feature spec
- `sample_repo_path` fixture provides reusable synthetic Python+TypeScript repo for downstream test suites

## Task Commits

Each task was committed atomically:

1. **Task 1: RED — Write failing tests for walk_repo** - `b5d0644` (test)
2. **Task 2: GREEN — Implement walker.py to pass all tests** - `a97bf05` (feat)

**Plan metadata:** (docs commit follows)

_Note: TDD tasks follow red-green cycle — test commit then implementation commit_

## Files Created/Modified
- `backend/app/ingestion/__init__.py` - Package marker for ingestion module
- `backend/app/ingestion/walker.py` - walk_repo() implementation with FileEntry TypedDict, SKIP_DIRS, EXTENSION_TO_LANGUAGE, _is_gitignored() helper
- `backend/tests/__init__.py` - Package marker for tests
- `backend/tests/conftest.py` - sample_repo_path fixture (function-scoped synthetic repo in tmp_path)
- `backend/tests/test_file_walker.py` - 12 unit tests covering all filtering contracts
- `backend/requirements.txt` - Added pathspec>=1.0.0

## Decisions Made
- Used `pathspec.GitIgnoreSpec.from_lines()` not `PathSpec.from_lines('gitignore', ...)` — GitIgnoreSpec is the correct class for gitignore semantics per research
- Two-pass os.walk design: first collect all .gitignore specs, then collect files — ensures specs from nested subdirectories are loaded before those files are evaluated
- os.walk instead of Path.walk — project targets Python 3.11, Path.walk only available 3.12+
- Relative paths passed to spec.match_file() — pathspec always returns False for absolute paths

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed test_skips_node_modules assertion using Path.parts instead of substring match**
- **Found during:** Task 2 (GREEN — Implement walker.py to pass all tests)
- **Issue:** The assertion `"node_modules" not in r["path"]` was a substring check that failed because pytest names the tmp_path directory after the test function (`test_skips_node_modules0`), which itself contains the string "node_modules". The walker correctly excludes node_modules/ but the assertion falsely failed.
- **Fix:** Changed assertion to check `"node_modules" not in Path(r["path"]).relative_to(tmp_path.resolve()).parts` — checks directory components, not substring
- **Files modified:** backend/tests/test_file_walker.py
- **Verification:** All 12 tests pass including test_skips_node_modules
- **Committed in:** a97bf05 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - test assertion bug)
**Impact on plan:** Fix required for correctness — test was producing false negative against correct implementation. No scope creep.

## Issues Encountered
- Python 3.14.3 (pyenv) detected at test runtime — no compatibility issues since plan correctly used os.walk (not Path.walk) and standard typing

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `walk_repo()` contract is verified and stable — ready for 03-ast-parser to consume FileEntry dicts
- `sample_repo_path` fixture available for downstream test suites via conftest.py
- `SKIP_DIRS` and `EXTENSION_TO_LANGUAGE` exported at module level for extension by later phases

---
*Phase: 02-file-walker*
*Completed: 2026-03-18*
