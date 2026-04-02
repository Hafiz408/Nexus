# Phase 20: tester-agent — Research

**Researched:** 2026-03-22
**Domain:** Graph-aware test code generation with framework detection
**Confidence:** HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| TEST-01 | Tester detects test framework from repo structure (pytest, jest, vitest, junit) | Detection via `os.walk` / `pathlib.Path.rglob` scanning for framework-specific marker files; deterministic heuristics require no LLM call |
| TEST-02 | Tester identifies all CALLS-edge callees of target functions as mock targets | NetworkX `G.successors(target_id)` filtered by `edge["type"] == "CALLS"` — exact same pattern as reviewer.py's callee enumeration |
| TEST-03 | Tester generates runnable test code covering happy path, error cases, and edge cases | Structured LLM prompt listing callee names as mock targets; prompt must mandate ≥3 test functions with distinct coverage categories |
| TEST-04 | Tester derives correct test file path following per-framework conventions (pytest: `tests/test_<name>.py`, jest: `__tests__/<name>.test.ts`, vitest: `<name>.test.ts`) | Pure string derivation from function name + detected framework; no LLM needed |
| TEST-05 | Generated test code uses correct mock/patch syntax for the detected framework | Framework-specific mock syntax embedded in the system prompt; no hand-rolled template engine |
| TST-04 | `test_tester.py` — framework detection; mock targets; file path convention; ≥3 test functions; mock statements present | Test structure mirrors test_reviewer.py: fixture graph (tester_graph) + mock_settings + mock_llm_factory; 10 offline tests |
</phase_requirements>

---

## Summary

Phase 20 implements the Tester agent following the same structural pattern established in Phases 18 (Debugger) and 19 (Reviewer). The algorithm has two deterministic pre-processing steps before the LLM call: (1) framework detection by scanning repo directory structure for framework-specific marker files, and (2) callee enumeration by traversing CALLS-edge successors of the target node in the NetworkX graph. Both steps are fully testable without an LLM.

The LLM's job is scoped and constrained: given the target function's attributes, a list of callee names as mock targets, and framework-specific mock syntax, generate ≥3 test functions covering happy path, error case, and edge case. The result is a `TestResult` Pydantic model containing the generated test code string, the derived file path, and the detected framework name. The agent does not write the file — that is MCP-03's responsibility (Phase 23).

The test suite (TST-04) must follow the identical offline pattern: fixture graph with known callee topology, `mock_settings` stub, source-level patch of `app.core.model_factory.get_llm`, and assertions on framework detection, mock target enumeration, file path convention, minimum 3 test functions in generated code, and presence of framework-appropriate mock syntax strings.

**Primary recommendation:** Model `tester.py` directly on `reviewer.py`. Reuse the lazy-import pattern, Pydantic output schema, `settings=None` injection, and LCEL `with_structured_output` chain. New work is: framework detection helper, callee extraction helper, framework-aware system prompt, and test file path derivation.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| networkx | Already a dep | `G.successors()` filtered by `CALLS` edge type — callee enumeration | Same graph traversal API used by reviewer.py and debugger.py |
| pydantic | v2 (already a dep) | `TestResult` output schema with `test_code`, `test_file_path`, `framework` fields | All V2 agents use BaseModel for structured output |
| langchain-core | Already a dep | `ChatPromptTemplate`, LCEL pipe operator, `with_structured_output` | Same pattern as reviewer.py — prompt | structured_llm; chain.invoke() |
| pathlib | stdlib | `Path.rglob()` for framework marker file detection | No new dep; available everywhere |
| app.core.model_factory | Internal | `get_llm()` lazy import inside `test()` body | Established project pattern — never import at module level |
| app.config | Internal | `get_settings()` lazy import | Same pattern as all prior agents |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest + unittest.mock | Already a dep | `test_tester.py` fixtures, `patch` | All V2 tests use this combination |
| typing (Literal) | stdlib | `framework` field typed as `Literal["pytest","jest","vitest","junit","unknown"]` | Same Literal pattern as reviewer.py severity field |
| os / pathlib | stdlib | Repo root scanning during framework detection | Prefer `pathlib.Path.rglob` for Pythonic glob patterns |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Deterministic framework detection via file scanning | LLM-based detection | File scanning is deterministic, offline, and testable without a mock LLM — use it |
| `with_structured_output(TestResult)` | Plain LLM call + string parsing | `with_structured_output` guarantees schema conformance; the test code goes in a `str` field — no parsing needed |
| Hardcoded framework paths | Template engine (Jinja2) | Hardcoded strings per framework are simpler, testable, and cover the 4 frameworks in scope |

**Installation:** No new packages. All dependencies already present.

---

## Architecture Patterns

### Recommended Project Structure

```
backend/app/agent/
├── explorer.py        # V1 — DO NOT TOUCH
├── router.py          # Phase 17 — complete
├── debugger.py        # Phase 18 — complete
├── reviewer.py        # Phase 19 — complete (reference implementation)
└── tester.py          # Phase 20 — NEW

backend/tests/
├── test_debugger.py   # Phase 18 reference test
├── test_reviewer.py   # Phase 19 reference test
└── test_tester.py     # Phase 20 — NEW
```

### Pattern 1: Lazy Import Guards (mandatory project standard)

**What:** `get_llm()` and `get_settings()` are imported INSIDE the public function body, never at module level.

**Why:** Prevents `ValidationError` during pytest collection when `POSTGRES_*` env vars are absent. Every prior agent follows this pattern without exception.

**Example (from reviewer.py — copy this pattern exactly):**
```python
def test(question: str, G: nx.DiGraph, target_node_id: str,
         repo_root: str | None = None, settings=None) -> TestResult:
    # Step 1: Settings (lazy import)
    if settings is None:
        from app.config import get_settings  # noqa: PLC0415
        settings = get_settings()

    # Step 2: LLM (lazy import — CRITICAL: inside function body)
    from app.core.model_factory import get_llm  # noqa: PLC0415
    ...
```

### Pattern 2: Framework Detection via File System Heuristics

**What:** Scan for framework-specific marker files to determine the test framework without an LLM call.

**When to use:** Always — deterministic, testable, no token cost.

**Detection order (priority — first match wins):**

| Framework | Marker Files | Convention |
|-----------|-------------|------------|
| pytest | `pytest.ini`, `pyproject.toml` (contains `[tool.pytest`), `setup.cfg`, any `test_*.py` or `*_test.py` file, `conftest.py` | `tests/test_<name>.py` |
| jest | `jest.config.js`, `jest.config.ts`, `jest.config.json`, `package.json` (contains `"jest"`) | `__tests__/<name>.test.ts` |
| vitest | `vitest.config.ts`, `vitest.config.js` | `<name>.test.ts` |
| junit | `pom.xml`, `build.gradle` | `src/test/java/<Name>Test.java` |
| unknown | None matched | `tests/test_<name>.py` (safe default) |

**Implementation note:** The detection helper `_detect_framework(repo_root: str) -> str` should use `pathlib.Path(repo_root).rglob("*.ini")` etc., or `Path.exists()` for single known filenames. When `repo_root` is `None`, default to `"pytest"` — the project is Python-first.

**Test design:** The `tester_graph` fixture does not need a real repo. The `test_framework_detection_*` tests pass a `tmp_path` directory seeded with marker files directly to `_detect_framework()`.

### Pattern 3: Callee Enumeration (mock target extraction)

**What:** Collect all CALLS-edge successors of the target node to build the mock target list.

**Implementation (identical to reviewer.py's callee assembly):**
```python
def _get_callees(G: nx.DiGraph, target_id: str) -> list[str]:
    """Return names of all CALLS-edge successors of target_id."""
    if target_id not in G:
        raise ValueError(f"target_node_id {target_id!r} not found in graph")
    return [
        G.nodes[succ].get("name", succ)
        for succ in G.successors(target_id)
        if G.edges[target_id, succ].get("type") == "CALLS"
    ]
```

**Mock target format in prompt:** Pass as a comma-separated list: `mock_targets = ", ".join(callees)`. This feeds directly into the system prompt so the LLM knows what to mock.

### Pattern 4: Test File Path Derivation

**What:** Given a function name and detected framework, produce the conventional test file path string.

**No LLM needed** — pure string derivation:

```python
def _derive_test_path(func_name: str, framework: str) -> str:
    name = func_name.replace(".", "_").replace("::", "_")
    if framework == "pytest":
        return f"tests/test_{name}.py"
    if framework == "jest":
        return f"__tests__/{name}.test.ts"
    if framework == "vitest":
        return f"{name}.test.ts"
    if framework == "junit":
        return f"src/test/java/{name.capitalize()}Test.java"
    return f"tests/test_{name}.py"  # unknown fallback
```

**Success criterion 4 says:** "tests/test_name.py for pytest" — this is the exact output format to target.

### Pattern 5: LCEL Structured Output (with_structured_output)

**What:** The LLM call uses `with_structured_output(TestResult)` — same as reviewer.py, NOT the plain `chain | llm` pattern from debugger.py.

**Why:** `TestResult` is a Pydantic model and structured output guarantees the `test_code` field is a string (no `.content` attribute needed). This simplifies mock setup in tests.

**LLM invocation:**
```python
structured_llm = llm.with_structured_output(TestResult)
prompt = TESTER_PROMPT.partial(...)
chain = prompt | structured_llm
result: TestResult = chain.invoke({...})
```

**Mock pattern in tests (from test_reviewer.py — copy exactly):**
```python
mock_structured = MagicMock()
mock_structured.return_value = fixture_result  # called via __call__ by RunnableSequence
mock_llm = MagicMock()
mock_llm.with_structured_output.return_value = mock_structured
mock_factory.return_value = mock_llm
```

### Pattern 6: Pydantic Output Schema

**What:** `TestResult` Pydantic model with 3 fields.

```python
class TestResult(BaseModel):
    """Complete test generation result."""
    test_code: str            # runnable test file content
    test_file_path: str       # derived file path following framework convention
    framework: str            # detected framework name
```

**Note:** `test_file_path` is set by the agent AFTER the LLM call (derived deterministically), not by the LLM. The LLM only generates `test_code`. The `framework` is also pre-computed. So the Pydantic model fields can be assembled after the LLM returns the code string. Alternatively, let the LLM fill all three and post-override `test_file_path` + `framework` from the deterministic computations — same groundedness approach reviewer.py uses for post-filtering.

**Recommended approach:** Let LLM generate `test_code` only (plain string response or single-field schema), then assemble `TestResult` manually with deterministic `test_file_path` and `framework`. This avoids LLM hallucinating the file path. However, `with_structured_output` requires a full schema — use a two-model approach:

```python
class _LLMTestOutput(BaseModel):
    test_code: str  # only field the LLM fills

class TestResult(BaseModel):
    test_code: str
    test_file_path: str
    framework: str
```

Call `with_structured_output(_LLMTestOutput)`, then construct `TestResult(test_code=..., test_file_path=..., framework=...)` deterministically. This is cleaner and fully testable.

### Anti-Patterns to Avoid

- **Importing get_llm at module level:** Causes ValidationError during pytest collection. Every agent uses lazy imports.
- **Letting LLM derive test_file_path:** Non-deterministic; breaks TEST-04 assertions. Always derive it from func name + framework.
- **Skipping callee enumeration when target has no callees:** Return an empty mock target list — do not raise. The prompt handles zero callees gracefully.
- **Using G.nodes[succ]["name"] without `.get()`:** Node may lack a "name" attribute; use `.get("name", succ)` for safety.
- **Framework detection at module level:** Must be callable per-request so tests can inject `tmp_path` directories.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Structured LLM output parsing | JSON string parsing from raw LLM response | `with_structured_output(_LLMTestOutput)` | Handles schema validation, retries, and provider differences |
| Mock framework detection | In-memory framework registry | `pathlib.Path.rglob` + `Path.exists()` file checks | Filesystem state is source of truth; no maintenance overhead |
| Test code template engine | Jinja2 or string.Template | LLM with constrained system prompt | LLM generates context-aware test bodies; templates can't adapt to function signatures |

**Key insight:** Framework detection and path derivation are deterministic (no LLM). Test body generation is the one LLM-appropriate task. Keep them strictly separated.

---

## Common Pitfalls

### Pitfall 1: Source-Level Patch Target

**What goes wrong:** Test patches `app.agent.tester.get_llm` instead of `app.core.model_factory.get_llm` and the patch has no effect.

**Why it happens:** `tester.py` imports `get_llm` lazily inside `test()` body. At patch time the name does not exist in `app.agent.tester.__dict__`. The patch must intercept at the source module.

**How to avoid:** Always patch `"app.core.model_factory.get_llm"` — this is documented in test_debugger.py and test_reviewer.py comments.

**Warning signs:** Mock assertions pass but LLM mock is never called — the real `get_llm` is being invoked.

### Pitfall 2: LLM-Derived File Path Flakiness

**What goes wrong:** The LLM hallucinate a file path like `test_my_function.py` or `tests/my_function_test.py` that doesn't match the framework convention exactly.

**Why it happens:** LLMs don't reliably follow path conventions without strong constraints.

**How to avoid:** Never let the LLM output `test_file_path`. Derive it deterministically in `_derive_test_path()` after the LLM call. Override whatever the LLM might have returned.

### Pitfall 3: Fewer Than 3 Test Functions

**What goes wrong:** Generated `test_code` contains only 1–2 test functions; SUCCESS CRITERION 3 fails.

**Why it happens:** Generic prompts don't mandate coverage categories; the LLM defaults to one happy-path test.

**How to avoid:** System prompt must explicitly state: "Generate EXACTLY three or more test functions: one for the happy path, one for error/exception cases, and one for edge cases (empty input, boundary values, etc.)." Use UPPERCASE emphasis in the prompt.

### Pitfall 4: Wrong Mock Syntax for Framework

**What goes wrong:** For a pytest target, the LLM generates `jest.mock(...)` syntax or vice versa.

**Why it happens:** Ambiguous prompt without framework specification.

**How to avoid:** Inject the framework name AND example mock syntax into the system prompt. For pytest: `unittest.mock.patch("module.callee")`. For jest: `jest.mock("./module")`. For vitest: `vi.mock("./module")`.

### Pitfall 5: Callee Names vs. Node IDs in Mock Targets

**What goes wrong:** Mock targets are listed as node IDs (`lib.py::callee_func`) rather than importable names (`lib.callee_func`).

**Why it happens:** `G.nodes[succ]["name"]` gives the bare function name but not the module path needed for `unittest.mock.patch`.

**How to avoid:** For mock target strings in the prompt, pass both the `name` and `file_path` attributes so the LLM can construct the patch path. The success criterion (TEST-02) checks that callees "appear as mock/patch targets" — exact import path accuracy is a prompt quality concern, not a hard validation. Include `file_path` in the callee description.

---

## Code Examples

### Framework Detection Helper

```python
# Source: pathlib stdlib docs + project pattern
from pathlib import Path

_FRAMEWORK_MARKERS = {
    "pytest": ["pytest.ini", "conftest.py", "setup.cfg"],
    "jest":   ["jest.config.js", "jest.config.ts", "jest.config.json"],
    "vitest": ["vitest.config.ts", "vitest.config.js"],
    "junit":  ["pom.xml", "build.gradle"],
}

def _detect_framework(repo_root: str) -> str:
    """Detect test framework from repo file structure. Returns framework name."""
    root = Path(repo_root)
    for framework, markers in _FRAMEWORK_MARKERS.items():
        for marker in markers:
            if (root / marker).exists():
                return framework
    # Fallback: look for any test_*.py file (pytest convention)
    if any(root.rglob("test_*.py")):
        return "pytest"
    return "unknown"
```

### Mock Syntax Lookup

```python
# Source: pytest docs (unittest.mock.patch), jest docs (jest.mock), vitest docs (vi.mock)
_MOCK_SYNTAX_EXAMPLE = {
    "pytest":  "from unittest.mock import patch\n@patch('module.callee')",
    "jest":    "jest.mock('./module');",
    "vitest":  "vi.mock('./module');",
    "junit":   "@Mock\nprivate CalleeClass callee;",
    "unknown": "from unittest.mock import patch\n@patch('module.callee')",
}
```

### Public API Signature

```python
def test(
    question: str,
    G: nx.DiGraph,
    target_node_id: str,
    repo_root: str | None = None,
    settings=None,
) -> TestResult:
    """Generate runnable test code for target_node_id.

    Args:
        question: Natural-language test request.
        G: Project call graph (NetworkX DiGraph with CALLS-typed edges).
        target_node_id: The function to test (must exist in G).
        repo_root: Optional repo root path for framework detection; defaults to "." if None.
        settings: Optional Settings instance; lazy-loaded from app.config if None.

    Returns:
        TestResult with test_code, test_file_path, and framework.
    """
```

### System Prompt (TESTER_SYSTEM)

```python
TESTER_SYSTEM = """You are a test code generation assistant. Given a target function and \
its callees (dependencies), generate runnable test code.

Framework: {framework}
Mock syntax for this framework:
{mock_syntax}

REQUIREMENTS:
1. Generate EXACTLY three or more test functions: happy path, error/exception case, edge case.
2. Every callee listed in "Mock targets" must appear as a mock/patch in the test setup.
3. Use correct {framework} syntax — import statements, test runner decorators, assertions.
4. Return only valid, runnable code. No markdown fences. No explanatory text.

Mock targets (callees of the target function):
{mock_targets}"""
```

### TestResult Pydantic Model

```python
class _LLMTestOutput(BaseModel):
    """Schema for the LLM structured output call — test code only."""
    test_code: str

class TestResult(BaseModel):
    """Complete test generation result returned by test()."""
    test_code: str
    test_file_path: str   # derived deterministically, not by LLM
    framework: str        # detected deterministically, not by LLM
```

### Test Fixture (tester_graph)

```python
@pytest.fixture
def tester_graph() -> nx.DiGraph:
    """4-node DiGraph: target + 2 callees + 1 isolated node.

    Topology (all CALLS edges):
      src.py::process_order -> lib.py::validate_input (CALLS)
      src.py::process_order -> lib.py::save_to_db     (CALLS)
      utils.py::helper_fn  (isolated — no CALLS edges from target)

    This topology lets tests verify:
      - callee enumeration finds exactly 2 mock targets
      - isolated nodes are NOT included in mock targets
    """
    G = nx.DiGraph()
    nodes = [
        {"node_id": "src.py::process_order", "name": "process_order",
         "file_path": "src.py", "line_start": 10, "line_end": 30},
        {"node_id": "lib.py::validate_input", "name": "validate_input",
         "file_path": "lib.py", "line_start": 1, "line_end": 10},
        {"node_id": "lib.py::save_to_db", "name": "save_to_db",
         "file_path": "lib.py", "line_start": 12, "line_end": 20},
        {"node_id": "utils.py::helper_fn", "name": "helper_fn",
         "file_path": "utils.py", "line_start": 1, "line_end": 5},
    ]
    for n in nodes:
        G.add_node(n["node_id"], **n)
    G.add_edge("src.py::process_order", "lib.py::validate_input", type="CALLS")
    G.add_edge("src.py::process_order", "lib.py::save_to_db", type="CALLS")
    return G
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Template-based test generation | LLM with constrained prompt | 2023+ | Context-aware, adapts to function signatures |
| Manual mock setup | `with_structured_output` schema | LangChain 0.1+ | Schema-validated output eliminates parsing bugs |
| Import-time LLM instantiation | Lazy import inside function body | Phase 17 (project convention) | Tests run offline without API keys |

**Deprecated/outdated in this codebase:**
- Module-level `get_llm()` calls: All three completed agents (router, debugger, reviewer) use lazy imports. Do not revert.
- `chain.invoke()` returning `.content`: Debugger uses this for plain LLM calls. Tester should use `with_structured_output` like reviewer (structured output guarantees `test_code` is a string field).

---

## Open Questions

1. **Target node with zero callees**
   - What we know: `G.successors(target_id)` returns an empty iterator when no callees exist.
   - What's unclear: Should the prompt still mandate mock setup, or skip the mock targets section?
   - Recommendation: Pass `mock_targets = "(none — target has no external dependencies)"` to the prompt. The LLM will generate test functions without mocks. Tests must handle this case with a separate fixture.

2. **`repo_root` not provided by caller**
   - What we know: The Phase 22 orchestrator (not yet built) will provide repo context. Phase 20 is standalone.
   - What's unclear: How the orchestrator surfaces `repo_root` in the graph state.
   - Recommendation: Default `repo_root` to `"."` when `None`. Document that detection falls back to `"pytest"` if no markers found in `.`. This is safe — the project is Python-first.

3. **junit file path convention for non-Java targets**
   - What we know: TST-04 requirements focus on pytest, jest, vitest. junit is listed in TEST-01 but no success criterion targets it.
   - What's unclear: Whether `test_tester.py` must test junit path derivation.
   - Recommendation: Implement junit detection + path derivation for completeness (TEST-01 scope), but the TST-04 test suite can focus assertions on pytest/jest/vitest as the success criteria specify.

---

## Sources

### Primary (HIGH confidence)
- `backend/app/agent/reviewer.py` — Reference implementation for the lazy-import pattern, `with_structured_output` chain, Pydantic output model, groundedness post-filter
- `backend/app/agent/debugger.py` — Reference implementation for BFS callee traversal, CALLS-edge filtering (`G.out_edges(node_id, data=True)` / `edge_data.get("type") == "CALLS"`)
- `backend/tests/test_reviewer.py` — Reference test file: source-level patch target, `mock_structured.return_value` pattern, fixture graph design
- `backend/tests/test_debugger.py` — Reference test file: `mock_llm.__or__` vs `mock_structured.__call__` difference; settings stub pattern
- `backend/app/config.py` — Confirms no tester-specific settings exist yet; `Settings` fields all optional with defaults
- `.planning/REQUIREMENTS.md` — Source of truth for TEST-01 through TEST-05 and TST-04 specifications
- `.planning/STATE.md` — Accumulated decisions: lazy import pattern mandatory, mock LLM + mock graph in all V2 tests, source-level patch at `app.core.model_factory.get_llm`

### Secondary (MEDIUM confidence)
- Python stdlib `pathlib` docs — `Path.rglob()`, `Path.exists()` for framework marker detection
- pytest framework marker files: `pytest.ini`, `conftest.py`, `setup.cfg`, `pyproject.toml` — standard across ecosystem
- jest config file names: `jest.config.js/ts/json` — documented in jest official docs
- vitest config file names: `vitest.config.ts/js` — documented in vitest official docs

### Tertiary (LOW confidence)
- None — all findings verified against project source code or stdlib docs.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all dependencies already present; confirmed in imports of reviewer.py and debugger.py
- Architecture: HIGH — reviewer.py is the direct reference implementation; pattern is fully established
- Framework detection: HIGH — file marker approach is standard across all four frameworks
- Pitfalls: HIGH — documented by reading actual test files and understanding the lazy-import failure mode from Phase 17 decisions in STATE.md
- Test design: HIGH — test_reviewer.py provides exact fixture and mock patterns to replicate

**Research date:** 2026-03-22
**Valid until:** 2026-06-22 (stable — no fast-moving dependencies; all libs already pinned in project)
