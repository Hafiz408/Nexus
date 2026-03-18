# Phase 6: Pipeline - Research

**Researched:** 2026-03-18
**Domain:** Python asyncio orchestration, concurrent ingestion pipeline, in-memory status tracking
**Confidence:** HIGH

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| PIPE-01 | `run_ingestion(repo_path, languages)` orchestrates walk → parse → build → embed → save | Orchestrator pattern with async wrapper around sync stages; signature and return type defined below |
| PIPE-02 | File parsing runs concurrently via `asyncio.gather` with semaphore limiting to 10 concurrent parses | `asyncio.Semaphore(10)` + `asyncio.to_thread()` wraps the sync `parse_file()`; gather over all file coroutines |
| PIPE-03 | Supports `changed_files: list[str]` for incremental re-index (re-parse only changed, remove old nodes) | `delete_nodes_for_files()` already implemented in graph_store; incremental path re-walks and re-parses only the listed files |
| PIPE-04 | Stores current status in in-memory dict keyed by `repo_path` for status polling | Module-level `_status: dict[str, IndexStatus]` dict; updated at each pipeline stage; thread-safe for single-process FastAPI workers |
| PIPE-05 | Returns `IndexStatus` with `{status, nodes_indexed, edges_indexed, files_processed, error}` | Pydantic model added to `app/models/schemas.py`; returned by `run_ingestion()` and read from `_status` dict |
</phase_requirements>

---

## Summary

Phase 6 wires together all previously built ingestion components (walker, ast_parser, graph_builder, embedder, graph_store) into a single `run_ingestion()` async function. This is a pure orchestration phase — no new algorithms, no new storage layers — just coordination of existing synchronous modules via Python's asyncio primitives.

The key complexity is PIPE-02: `parse_file()` is a CPU-bound synchronous function. To run it concurrently without blocking the asyncio event loop, it must be offloaded to a `ThreadPoolExecutor` using `asyncio.to_thread()`. The correct pattern is `asyncio.to_thread(parse_file, path, repo_root, language)` wrapped in an `async with semaphore:` block, gathered over all files.

Status tracking (PIPE-04) is a module-level `dict[str, IndexStatus]` updated during ingestion. Since FastAPI runs in a single worker process for V1, no cross-process sharing is needed — the dict is accessible to both the background task and the `/index/status` polling endpoint.

**Primary recommendation:** Implement `pipeline.py` in `app/ingestion/` as an async module. Add `IndexStatus` Pydantic model to `schemas.py`. Use `asyncio.Semaphore(10)` + `asyncio.to_thread()` for concurrent parsing, update the module-level status dict at each stage, and handle the incremental path by calling `delete_nodes_for_files()` before re-parsing changed files. No new dependencies required.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| asyncio | stdlib (3.11) | Concurrent parse orchestration | Built-in; no install required; already used by FastAPI |
| asyncio.to_thread | stdlib 3.9+ | Run sync `parse_file()` off event loop | Cleaner API vs run_in_executor; reuses default ThreadPoolExecutor |
| pydantic BaseModel | 2.x (already installed) | `IndexStatus` schema definition | Consistent with rest of project (CodeNode, CodeEdge use same pattern) |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| asyncio.Semaphore | stdlib | Limit to 10 concurrent parses | Prevent OOM on large repos with hundreds of files |
| asyncio.gather | stdlib | Fan-out parse coroutines, collect results | When all tasks must complete before next stage |
| logging | stdlib | Warn on per-file parse errors | Non-fatal errors should log and continue, not crash pipeline |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| ThreadPoolExecutor (via to_thread) | ProcessPoolExecutor | Separate processes avoid GIL fully but module-level tree-sitter Language singletons cannot be serialized for IPC — threads are correct here |
| asyncio.gather + semaphore | asyncio.TaskGroup (3.11+) | TaskGroup cancels all tasks on first exception — gather with return_exceptions=True allows partial success, correct for ingestion |
| In-memory dict | Redis / external store | Redis is V2 complexity; single-worker FastAPI does not need external store in V1 |

**Installation:** No new packages needed. All required libraries are stdlib or already in requirements.txt.

---

## Architecture Patterns

### Recommended Project Structure

```
backend/app/ingestion/
├── walker.py         # DONE — walk_repo(), EXTENSION_TO_LANGUAGE
├── ast_parser.py     # DONE — parse_file()
├── graph_builder.py  # DONE — build_graph()
├── embedder.py       # DONE — embed_and_store()
├── graph_store.py    # DONE — save_graph(), delete_nodes_for_files()
└── pipeline.py       # NEW — run_ingestion(), _status dict, get_status()

backend/app/models/
└── schemas.py        # ADD IndexStatus Pydantic model here

backend/tests/
└── test_pipeline.py  # NEW — unit tests for pipeline
```

### Pattern 1: Async Wrapper Over Sync Orchestration

**What:** The outer `run_ingestion()` is `async def`. Synchronous stages (walk, build, embed, save) run directly (they are fast or IO-light relative to parsing). Parsing is fanned out with `asyncio.gather` + `asyncio.Semaphore`.

**When to use:** When most pipeline stages are synchronous but one stage is embarrassingly parallel (parsing each file independently).

**Example:**
```python
# Source: Python official docs asyncio-task + asyncio-sync
import asyncio
from asyncio import Semaphore

PARSE_CONCURRENCY = 10

async def _parse_file_async(
    sem: Semaphore,
    file_path: str,
    repo_root: str,
    language: str,
) -> tuple[list, list]:
    async with sem:
        return await asyncio.to_thread(
            parse_file,
            file_path,
            repo_root,
            language,
        )

async def run_ingestion(
    repo_path: str,
    languages: list[str],
    changed_files: list[str] | None = None,
) -> "IndexStatus":
    ...
    sem = Semaphore(PARSE_CONCURRENCY)
    tasks = [
        _parse_file_async(sem, entry["path"], repo_path, entry["language"])
        for entry in files_to_parse
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    ...
```

### Pattern 2: Module-Level Status Dict

**What:** A `dict[str, IndexStatus]` at module level holds one entry per active/completed `repo_path`. The `/index/status` endpoint reads from it directly.

**When to use:** Single-process servers where no cross-worker state sharing is needed (V1 constraint).

**Example:**
```python
# Module-level — initialized at import time
_status: dict[str, "IndexStatus"] = {}

async def run_ingestion(repo_path: str, ...) -> "IndexStatus":
    _status[repo_path] = IndexStatus(status="running")
    # ... each stage updates _status[repo_path] ...
    _status[repo_path] = IndexStatus(status="complete", nodes_indexed=N, ...)
    return _status[repo_path]

def get_status(repo_path: str) -> "IndexStatus | None":
    return _status.get(repo_path)
```

### Pattern 3: Incremental Re-Index Path

**What:** When `changed_files` is provided, skip the full walk and only re-parse the listed files. Before re-parsing, delete stale graph nodes for those files using the already-implemented `delete_nodes_for_files()`.

**When to use:** PIPE-03 — triggered by file watcher in Phase 13.

**Example:**
```python
if changed_files:
    # Step 1: remove old nodes (graph_store already implements this)
    delete_nodes_for_files(changed_files, repo_path)
    # Step 2: determine language per changed file by extension
    ext_map = {ext.lstrip("."): lang for ext, lang in EXTENSION_TO_LANGUAGE.items()}
    files_to_parse = [
        {"path": f, "language": ext_map[f.rsplit(".", 1)[-1].lower()], "size_kb": 0}
        for f in changed_files
        if "." in f and f.rsplit(".", 1)[-1].lower() in ext_map
        and ext_map[f.rsplit(".", 1)[-1].lower()] in languages
    ]
else:
    files_to_parse = walk_repo(repo_path, languages)
```

Note: For incremental mode, `build_graph` must receive nodes from the changed files merged with surviving nodes from the existing graph. See Open Questions for the design decision.

### Anti-Patterns to Avoid

- **Calling `parse_file()` directly in async def without thread offload:** This blocks the event loop. Tree-sitter parsing is CPU-bound; even if fast per file, 100+ files creates measurable event loop blocking.
- **Calling `asyncio.run()` inside `run_ingestion`:** `run_ingestion` is itself async; never nest `asyncio.run()` calls. The FastAPI `BackgroundTask` (Phase 7) will call it with `await`.
- **Storing raw `nx.DiGraph` in the status dict:** `IndexStatus` should store counts only, not the graph itself. The graph is persisted to SQLite by `save_graph()`.
- **Not handling exceptions from `asyncio.gather`:** When `return_exceptions=True`, each result may be an `Exception` instance. Must check `isinstance(result, Exception)` before unpacking.
- **Using ProcessPoolExecutor for parse workers:** Module-level tree-sitter Language singletons cannot be serialized for inter-process communication. ThreadPoolExecutor is the correct choice.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Concurrent execution limiting | Custom semaphore class | `asyncio.Semaphore` | stdlib, composable with `async with`, handles exceptions correctly |
| Thread-based offloading | Custom thread pool | `asyncio.to_thread()` | Reuses FastAPI's default executor, proper event loop integration |
| Status field validation | Plain dict with string keys | Pydantic `IndexStatus` model | Consistent with `CodeNode`/`CodeEdge` patterns; validated at construction |
| Language detection in incremental path | Re-implement extension mapping | `EXTENSION_TO_LANGUAGE` from `walker.py` | Already correct and tested; import it directly |
| Incremental delete | Custom node removal logic | `delete_nodes_for_files()` from `graph_store.py` | Already implemented and tested in Phase 5 |

**Key insight:** All algorithmic complexity was solved in Phases 2–5. Phase 6 is pure plumbing — resist any temptation to re-implement parsing, graph resolution, or embedding inside the pipeline module.

---

## Common Pitfalls

### Pitfall 1: tree-sitter Parser Singletons and Thread Safety

**What goes wrong:** Multiple threads calling `parse_file()` simultaneously share the module-level `py_parser`, `ts_parser`, `tsx_parser` objects. Tree-sitter's C-extension Parser objects have internal mutable state and are not safe for concurrent use from multiple threads.

**Why it happens:** `ast_parser.py` declares `py_parser = Parser(PY_LANGUAGE)` at module level. When `parse_file()` is called from 10 concurrent threads via `asyncio.to_thread`, all threads share these parser instances.

**How to avoid:** Modify `parse_file()` to create a new `Parser(LANGUAGE)` instance per call. `Language` objects (the expensive part) remain module-level singletons. `Parser` construction is cheap.

**Warning signs:** Intermittent segfaults or corrupted node data when testing with many concurrent parses.

### Pitfall 2: Incremental Re-Index Leaves Orphaned Graph Edges

**What goes wrong:** `delete_nodes_for_files()` removes stale nodes from SQLite. If `build_graph()` receives only the newly parsed nodes (not the full set of surviving nodes), it cannot resolve CALLS/IMPORTS edges to unchanged files, producing a disconnected graph.

**Why it happens:** `build_graph()` needs ALL nodes to resolve `target_name` references. Passing only re-parsed file nodes means surviving nodes' CALLS targets are unresolvable.

**How to avoid:** For incremental mode, either: (a) load the full graph from SQLite after deletion, merge new nodes, run `build_graph()` with the merged node set; or (b) for V1 simplicity, always perform a full re-index even when `changed_files` is provided (walks full repo, re-parses everything). Document which approach is chosen.

**Warning signs:** Edge counts drop to near-zero after incremental re-index; `test_pipeline.py` incremental test shows zero cross-file edges.

### Pitfall 3: `asyncio.gather` Exception Swallowing

**What goes wrong:** Failed parse tasks silently return `Exception` objects when `return_exceptions=True`. If the caller unpacks results without checking, `Exception` objects are passed to `build_graph()` as `CodeNode` lists, causing `AttributeError` on `.model_dump()`.

**Why it happens:** Developer adds `return_exceptions=True` to avoid task cancellation but forgets to filter results.

**How to avoid:** Always filter after gather:
```python
results = await asyncio.gather(*tasks, return_exceptions=True)
all_nodes, all_edges = [], []
for r in results:
    if isinstance(r, Exception):
        logger.warning("Parse failed: %s", r)
        continue
    nodes, edges = r
    all_nodes.extend(nodes)
    all_edges.extend(edges)
```

**Warning signs:** `TypeError: cannot unpack non-sequence Exception` or `AttributeError: 'ParseError' object has no attribute 'model_dump'`.

### Pitfall 4: Status Dict Concurrent Update

**What goes wrong:** Two rapid calls to `run_ingestion()` with the same `repo_path` overwrite each other's status mid-run.

**Why it happens:** Module-level `_status` dict is shared state between concurrent async tasks.

**How to avoid:** For V1 with a single FastAPI worker, this is acceptable but should be documented. The API layer (Phase 7) should check for "running" status and reject or queue duplicate requests. The pipeline itself can return early if status is already "running" for that path.

**Warning signs:** Status oscillates or shows stale `nodes_indexed` counts after rapid re-index requests.

### Pitfall 5: `embed_and_store` is Synchronous and Blocking

**What goes wrong:** `embed_and_store()` makes network calls to OpenAI (batched, but still I/O-bound) and SQLite writes. Called synchronously inside `async def run_ingestion()`, it blocks the event loop during embedding.

**Why it happens:** Phase 5 implemented `embed_and_store()` as a synchronous function.

**How to avoid:** Wrap `embed_and_store()` in `asyncio.to_thread()` as well:
```python
nodes_stored = await asyncio.to_thread(embed_and_store, all_nodes, repo_path)
```

**Warning signs:** Server becomes unresponsive to health check requests during embedding of large repos.

---

## Code Examples

Verified patterns from official sources and project codebase:

### IndexStatus Pydantic Model
```python
# Add to app/models/schemas.py — consistent with existing CodeNode pattern
from pydantic import BaseModel

class IndexStatus(BaseModel):
    status: str           # "running" | "complete" | "failed"
    nodes_indexed: int = 0
    edges_indexed: int = 0
    files_processed: int = 0
    error: str | None = None
```

### Full Pipeline Skeleton
```python
# app/ingestion/pipeline.py
import asyncio
import logging
from asyncio import Semaphore
from pathlib import Path

from app.ingestion.walker import walk_repo, EXTENSION_TO_LANGUAGE
from app.ingestion.ast_parser import parse_file
from app.ingestion.graph_builder import build_graph
from app.ingestion.embedder import embed_and_store
from app.ingestion.graph_store import save_graph, delete_nodes_for_files
from app.models.schemas import IndexStatus

logger = logging.getLogger(__name__)

PARSE_CONCURRENCY = 10
_status: dict[str, IndexStatus] = {}


def get_status(repo_path: str) -> IndexStatus | None:
    return _status.get(repo_path)


async def _parse_concurrent(
    files: list[dict],
    repo_path: str,
) -> tuple[list, list]:
    sem = Semaphore(PARSE_CONCURRENCY)

    async def _one(entry: dict) -> tuple:
        async with sem:
            return await asyncio.to_thread(
                parse_file,
                entry["path"],
                repo_path,
                entry["language"],
            )

    results = await asyncio.gather(*[_one(e) for e in files], return_exceptions=True)

    all_nodes, all_edges = [], []
    for r in results:
        if isinstance(r, Exception):
            logger.warning("parse_file failed: %s", r)
            continue
        nodes, edges = r
        all_nodes.extend(nodes)
        all_edges.extend(edges)
    return all_nodes, all_edges


async def run_ingestion(
    repo_path: str,
    languages: list[str],
    changed_files: list[str] | None = None,
) -> IndexStatus:
    _status[repo_path] = IndexStatus(status="running")
    try:
        if changed_files:
            delete_nodes_for_files(changed_files, repo_path)
            ext_map = {ext.lstrip("."): lang for ext, lang in EXTENSION_TO_LANGUAGE.items()}
            files_to_parse = [
                {"path": f, "language": ext_map[suffix], "size_kb": 0}
                for f in changed_files
                if "." in f
                and (suffix := f.rsplit(".", 1)[-1].lower()) in ext_map
                and ext_map[suffix] in languages
            ]
        else:
            files_to_parse = walk_repo(repo_path, languages)

        _status[repo_path] = IndexStatus(status="running", files_processed=len(files_to_parse))

        all_nodes, all_edges = await _parse_concurrent(files_to_parse, repo_path)
        G = build_graph(all_nodes, all_edges)
        await asyncio.to_thread(save_graph, G, repo_path)
        nodes_stored = await asyncio.to_thread(embed_and_store, all_nodes, repo_path)

        result = IndexStatus(
            status="complete",
            nodes_indexed=nodes_stored,
            edges_indexed=G.number_of_edges(),
            files_processed=len(files_to_parse),
        )
    except Exception as exc:
        logger.exception("run_ingestion failed for %s", repo_path)
        result = IndexStatus(status="failed", error=str(exc))

    _status[repo_path] = result
    return result
```

### Test Pattern — Mocking All I/O Stages
```python
# tests/test_pipeline.py
import asyncio
import pytest
from unittest.mock import patch
import networkx as nx

from app.ingestion.pipeline import run_ingestion, get_status
from app.models.schemas import IndexStatus


@pytest.fixture
def mock_pipeline_stages(tmp_path):
    G = nx.DiGraph()
    G.add_node("a.py::func", file_path=str(tmp_path / "a.py"), name="func",
               type="function", line_start=1, line_end=3)
    G.add_edge("a.py::func", "a.py::func")

    with (
        patch("app.ingestion.pipeline.walk_repo", return_value=[
            {"path": str(tmp_path / "a.py"), "language": "python", "size_kb": 1}
        ]),
        patch("app.ingestion.pipeline.parse_file", return_value=([], [])),
        patch("app.ingestion.pipeline.build_graph", return_value=G),
        patch("app.ingestion.pipeline.save_graph"),
        patch("app.ingestion.pipeline.embed_and_store", return_value=1),
    ):
        yield G


def test_run_ingestion_complete(mock_pipeline_stages, tmp_path):
    result = asyncio.run(run_ingestion(str(tmp_path), ["python"]))
    assert result.status == "complete"
    assert result.nodes_indexed == 1
    assert result.edges_indexed == 1
    assert result.files_processed == 1


def test_status_queryable_after_run(mock_pipeline_stages, tmp_path):
    asyncio.run(run_ingestion(str(tmp_path), ["python"]))
    status = get_status(str(tmp_path))
    assert status is not None
    assert status.status == "complete"


def test_run_ingestion_incremental(mock_pipeline_stages, tmp_path):
    changed = [str(tmp_path / "a.py")]
    with patch("app.ingestion.pipeline.delete_nodes_for_files") as mock_del:
        result = asyncio.run(run_ingestion(str(tmp_path), ["python"], changed_files=changed))
    mock_del.assert_called_once_with(changed, str(tmp_path))
    assert result.status == "complete"


def test_run_ingestion_error_returns_failed_status(tmp_path):
    with patch("app.ingestion.pipeline.walk_repo", side_effect=RuntimeError("disk error")):
        result = asyncio.run(run_ingestion(str(tmp_path), ["python"]))
    assert result.status == "failed"
    assert "disk error" in result.error
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `loop.run_in_executor(None, fn, *args)` | `asyncio.to_thread(fn, *args)` | Python 3.9 | Simpler API, same semantics; both work in Python 3.11 |
| `asyncio.coroutine` decorator | `async def` | Removed in Python 3.11 | Already used throughout project — no action needed |
| `asyncio.TaskGroup` for structured concurrency | `asyncio.gather(return_exceptions=True)` | Python 3.11 added TaskGroup | TaskGroup cancels all on first error; gather allows partial success — gather is correct for ingestion |

**Deprecated/outdated:**
- `loop.run_until_complete()`: Not needed when called from within an async context. Never call this inside `run_ingestion()`.
- `asyncio.coroutine`: Removed in 3.11; already using `async def` throughout.

---

## Open Questions

1. **Incremental re-index: merge existing graph or simplified full re-index?**
   - What we know: `delete_nodes_for_files()` removes stale nodes from SQLite. `build_graph()` builds from scratch given nodes+raw_edges. For true incremental behavior, surviving nodes from the existing graph must be included in the `build_graph()` call.
   - What's unclear: Whether V1 planner wants true incremental (load surviving nodes from SQLite, merge with newly parsed, rebuild) or simplified (re-parse ALL files even when `changed_files` is provided, effectively full re-index).
   - Recommendation: Implement true incremental path since `load_graph()` already exists and makes it straightforward. Load graph → get surviving nodes → merge with new nodes → `build_graph()` → `save_graph()`.

2. **Thread safety of tree-sitter Parser singletons**
   - What we know: `ast_parser.py` uses module-level Parser singletons. Concurrent thread invocations share them.
   - What's unclear: Whether tree-sitter's C extension is thread-safe for concurrent `parse()` on different files.
   - Recommendation: During Phase 6 implementation, either (a) move `Parser` construction inside `parse_file()` (keeping `Language` singletons at module level), or (b) add `threading.Lock` per parser. Option (a) is cleaner.

3. **`files_processed` counter — set once or live-updated?**
   - What we know: PIPE-04 says status "reflects current progress."
   - What's unclear: Does progress mean total count (set once before gather) or live increment (updated after each file parse)?
   - Recommendation: Set `files_processed` to total file count before gather begins. True per-file progress updates would require per-coroutine callbacks, which adds complexity not required by the spec for V1.

---

## Sources

### Primary (HIGH confidence)
- Python 3.11 official docs: `asyncio.Semaphore` — https://docs.python.org/3/library/asyncio-sync.html
- Python 3.11 official docs: `asyncio.gather` and `asyncio.to_thread` — https://docs.python.org/3/library/asyncio-task.html
- Python 3.11 official docs: `loop.run_in_executor` — https://docs.python.org/3/library/asyncio-eventloop.html
- Project codebase: `app/ingestion/graph_store.py` — `delete_nodes_for_files()`, `save_graph()`, `load_graph()` signatures verified
- Project codebase: `app/ingestion/embedder.py` — `embed_and_store()` signature and behavior verified
- Project codebase: `app/ingestion/walker.py` — `walk_repo()`, `EXTENSION_TO_LANGUAGE` verified
- Project codebase: `app/ingestion/ast_parser.py` — `parse_file()` signature, module-level Parser singletons verified
- Project codebase: `app/models/schemas.py` — `CodeNode`, `CodeEdge` patterns for `IndexStatus` design
- Project codebase: `backend/requirements.txt` — confirmed no new dependencies needed

### Secondary (MEDIUM confidence)
- WebSearch: asyncio.gather + Semaphore pattern — verified against Python official docs
- WebSearch: `asyncio.to_thread()` as replacement for `run_in_executor` — confirmed by Python 3.9+ docs

### Tertiary (LOW confidence)
- Tree-sitter Parser thread safety: Not verified against official tree-sitter C library docs — flag for validation; defensive approach (per-call Parser) recommended regardless

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries are stdlib or already installed; no new dependencies
- Architecture: HIGH — orchestration pattern is well-understood; all upstream modules are real and inspected
- Pitfalls: MEDIUM — tree-sitter thread safety is unverified (LOW within that pitfall); asyncio patterns are HIGH
- Incremental re-index design: MEDIUM — spec is clear, merge-vs-rebuild trade-off is a planner design decision

**Research date:** 2026-03-18
**Valid until:** 2026-04-18 (asyncio stdlib is stable; Python 3.11 API will not change)
