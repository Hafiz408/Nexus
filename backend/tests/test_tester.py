"""Tests for the Tester Agent (Phase 20, TST-04).

Verifies framework detection heuristics, callee enumeration (mock target count),
test file path derivation, minimum test function count in generated code, and
mock syntax presence — all offline (no live API calls, no database, no network).

Fixtures:
  - tester_graph: 4-node DiGraph (target + 2 CALLS callees + 1 isolated node)
  - mock_settings: MagicMock with no tester-specific fields
  - mock_llm_factory: patches app.core.model_factory.get_llm at source module

Patch target: 'app.core.model_factory.get_llm'
  Reason: tester.py uses a lazy import inside test() body — get_llm is NOT
  a module-level attribute of app.agent.tester. Source-level patching intercepts
  the import before the local scope resolves it.

LLM invocation pattern in test():
  structured_llm = llm.with_structured_output(_LLMTestOutput)
  chain = prompt | structured_llm
  llm_output = chain.invoke(...)
  So mock: llm.with_structured_output returns a mock_structured;
           mock_structured is called as a callable by RunnableSequence.__call__,
           so mock_structured.return_value = _LLMTestOutput(test_code=...) is correct.
  Note: mock_structured.__or__ is NOT used — the pipe operator belongs to the
  ChatPromptTemplate (prompt.__or__), creating a RunnableSequence that invokes
  structured_llm via __call__, not .invoke().
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import networkx as nx
import pytest

from app.agent.tester import (
    TestResult,
    _LLMTestOutput,
    _detect_framework,
    _derive_test_path,
    _get_callees,
    test as run_test,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tester_graph() -> nx.DiGraph:
    """4-node DiGraph: target + 2 CALLS callees + 1 isolated node.

    Topology:
      src.py::process_order -> lib.py::validate_input  (CALLS)
      src.py::process_order -> lib.py::save_to_db      (CALLS)
      utils.py::helper_fn  (isolated — no edges from target)
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
    # helper_fn is intentionally isolated (no CALLS edge from process_order)
    return G


@pytest.fixture
def mock_settings():
    """Minimal settings stub — tester has no settings knobs in Phase 20.

    Passed directly to test() to bypass get_settings(), which requires
    environment variables not present in the test environment.
    """
    settings = MagicMock()
    return settings


@pytest.fixture
def mock_llm_factory():
    """Patch get_llm at source. mock_structured.return_value is called via __call__
    by RunnableSequence (LCEL with_structured_output chain).
    Patch target: 'app.core.model_factory.get_llm' (source-level — lazy import)."""
    fixture_code = (
        "import pytest\n"
        "from unittest.mock import patch\n\n"
        "def test_process_order_happy_path():\n"
        "    with patch('lib.validate_input') as mock_validate, \\\n"
        "         patch('lib.save_to_db') as mock_save:\n"
        "        mock_validate.return_value = True\n"
        "        mock_save.return_value = {'id': 1}\n"
        "        result = process_order({'item': 'x', 'qty': 1})\n"
        "        assert result is not None\n\n"
        "def test_process_order_error_case():\n"
        "    with patch('lib.validate_input', side_effect=ValueError('invalid')):\n"
        "        with pytest.raises(ValueError):\n"
        "            process_order({})\n\n"
        "def test_process_order_edge_case():\n"
        "    with patch('lib.validate_input') as mock_validate, \\\n"
        "         patch('lib.save_to_db') as mock_save:\n"
        "        mock_validate.return_value = False\n"
        "        result = process_order({'item': '', 'qty': 0})\n"
        "        mock_save.assert_not_called()\n"
    )
    fixture_result = _LLMTestOutput(test_code=fixture_code)
    mock_structured = MagicMock()
    mock_structured.return_value = fixture_result
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = mock_structured
    with patch("app.core.model_factory.get_llm", return_value=mock_llm) as mock_factory:
        yield mock_factory


# ---------------------------------------------------------------------------
# Test 1 — Framework detection: pytest (marker file)
# ---------------------------------------------------------------------------

def test_framework_detection_pytest(tmp_path):
    """_detect_framework returns 'pytest' when pytest.ini exists in repo root."""
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    assert _detect_framework(str(tmp_path)) == "pytest"


# ---------------------------------------------------------------------------
# Test 2 — Framework detection: jest (marker file)
# ---------------------------------------------------------------------------

def test_framework_detection_jest(tmp_path):
    """_detect_framework returns 'jest' when jest.config.js exists in repo root."""
    (tmp_path / "jest.config.js").write_text("module.exports = {};\n")
    assert _detect_framework(str(tmp_path)) == "jest"


# ---------------------------------------------------------------------------
# Test 3 — Framework detection: vitest (marker file)
# ---------------------------------------------------------------------------

def test_framework_detection_vitest(tmp_path):
    """_detect_framework returns 'vitest' when vitest.config.ts exists in repo root."""
    (tmp_path / "vitest.config.ts").write_text("export default {};\n")
    assert _detect_framework(str(tmp_path)) == "vitest"


# ---------------------------------------------------------------------------
# Test 4 — Framework detection: fallback rglob for test_*.py
# ---------------------------------------------------------------------------

def test_framework_detection_fallback_test_file(tmp_path):
    """_detect_framework returns 'pytest' via rglob fallback when test_*.py found."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_foo.py").write_text("def test_something(): pass\n")
    # No marker files in root — should fall through to rglob
    assert _detect_framework(str(tmp_path)) == "pytest"


# ---------------------------------------------------------------------------
# Test 5 — Framework detection: unknown (empty directory)
# ---------------------------------------------------------------------------

def test_framework_detection_unknown(tmp_path):
    """_detect_framework returns 'unknown' when no markers or test files found."""
    assert _detect_framework(str(tmp_path)) == "unknown"


# ---------------------------------------------------------------------------
# Test 6 — _get_callees returns exactly 2 CALLS-edge targets (not 3)
# ---------------------------------------------------------------------------

def test_get_callees_returns_two_targets(tester_graph):
    """_get_callees must return exactly 2 entries for the tester_graph target.

    The 4-node graph has: 2 CALLS-edge callees + 1 isolated node.
    Isolated node (helper_fn) must NOT appear in results.
    """
    callees = _get_callees(tester_graph, "src.py::process_order")
    assert len(callees) == 2
    names = {c["name"] for c in callees}
    assert names == {"validate_input", "save_to_db"}


# ---------------------------------------------------------------------------
# Test 7 — _get_callees excludes isolated node
# ---------------------------------------------------------------------------

def test_get_callees_excludes_isolated_node(tester_graph):
    """helper_fn has no CALLS edge from process_order — must not appear in callees."""
    callees = _get_callees(tester_graph, "src.py::process_order")
    names = {c["name"] for c in callees}
    assert "helper_fn" not in names


# ---------------------------------------------------------------------------
# Test 8 — _derive_test_path conventions for multiple frameworks
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("framework,expected", [
    ("pytest",  "tests/test_process_order.py"),
    ("jest",    "__tests__/process_order.test.ts"),
    ("vitest",  "process_order.test.ts"),
    ("junit",   "src/test/java/Process_orderTest.java"),
    ("unknown", "tests/test_process_order.py"),
])
def test_derive_test_path_conventions(framework, expected):
    """_derive_test_path must return the exact conventional path for each framework."""
    assert _derive_test_path("process_order", framework) == expected


# ---------------------------------------------------------------------------
# Test 9 — Full test() call returns well-formed TestResult
# ---------------------------------------------------------------------------

def test_full_test_call_returns_result(tester_graph, mock_settings, mock_llm_factory, tmp_path):
    """test() must return a TestResult with correct framework, file path, and test code."""
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    result = run_test(
        "write tests for process_order",
        tester_graph,
        "src.py::process_order",
        repo_root=str(tmp_path),
        settings=mock_settings,
    )
    assert isinstance(result, TestResult)
    assert result.framework == "pytest"
    assert result.test_file_path == "tests/test_process_order.py"
    assert "def test_" in result.test_code
    # mock_syntax presence check (TST-04 / TEST-05 coverage within this test)
    assert "patch" in result.test_code or "mock" in result.test_code.lower()


# ---------------------------------------------------------------------------
# Test 10 — Generated test_code contains at least 3 test function definitions
# ---------------------------------------------------------------------------

def test_minimum_three_test_functions(tester_graph, mock_settings, mock_llm_factory, tmp_path):
    """test_code must contain at least 3 'def test_' function definitions."""
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    result = run_test(
        "write tests for process_order",
        tester_graph,
        "src.py::process_order",
        repo_root=str(tmp_path),
        settings=mock_settings,
    )
    count = result.test_code.count("def test_")
    assert count >= 3, (
        f"Expected at least 3 test function definitions, found {count}.\n"
        f"test_code:\n{result.test_code}"
    )
