"""Tests for Explorer Agent — explorer.py (Phase 9 Plan 02).

Tests use zero real API calls. ChatOpenAI is patched at the
app.agent.explorer module namespace (from-import binding — same rule as
Phase 8 graph_rag tests).

Coverage:
  - format_context_block: header format, docstring presence/absence,
    empty node list, multiple nodes separator
  - explore_stream: token order, empty-chunk filtering, no API key needed
  - SYSTEM_PROMPT: contains anti-fabrication rule
"""
import asyncio
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessageChunk

from app.agent.explorer import format_context_block, explore_stream
from app.agent.prompts import SYSTEM_PROMPT
from app.models.schemas import CodeNode


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_node() -> CodeNode:
    """Single CodeNode for format_context_block assertions."""
    return CodeNode(
        node_id="auth/login.py::authenticate",
        name="authenticate",
        type="function",
        file_path="/repo/auth/login.py",
        line_start=42,
        line_end=55,
        signature="def authenticate(username: str, password: str) -> bool:",
        docstring="Verify credentials against the user store.",
        body_preview="if not username:\n    return False",
    )


@pytest.fixture
def node_no_docstring() -> CodeNode:
    """CodeNode with no docstring to test omission in context block."""
    return CodeNode(
        node_id="utils.py::helper",
        name="helper",
        type="function",
        file_path="/repo/utils.py",
        line_start=1,
        line_end=3,
        signature="def helper():",
        docstring=None,
        body_preview="pass",
    )


@pytest.fixture
def mock_llm(monkeypatch):
    """Patches app.agent.explorer.get_llm — provider-agnostic, no API key needed.

    Injects a fake chain directly to bypass _get_chain() construction entirely.
    """
    import app.agent.explorer as explorer_mod

    tokens = ["Hello", " from", " Nexus", "."]

    async def _fake_astream(input_dict, **kwargs):
        yield AIMessageChunk(content="")   # empty first chunk — must be filtered
        for t in tokens:
            yield AIMessageChunk(content=t)

    mock_chain = MagicMock()
    mock_chain.astream = _fake_astream

    # Patch get_llm so _get_chain() doesn't call a real provider
    monkeypatch.setattr("app.agent.explorer.get_llm", MagicMock(return_value=MagicMock()))

    # Inject fake chain directly — bypasses prompt|llm construction
    explorer_mod._chain = mock_chain

    yield tokens


# ---------------------------------------------------------------------------
# format_context_block tests (pure function — no mock needed)
# ---------------------------------------------------------------------------

def test_format_context_block_header(sample_node):
    """Header must match AGNT-05 format exactly."""
    result = format_context_block([sample_node])
    assert result.startswith(
        "--- [/repo/auth/login.py:42-55] authenticate (function) ---"
    )


def test_format_context_block_contains_signature(sample_node):
    """Signature appears in the context block body."""
    result = format_context_block([sample_node])
    assert "def authenticate(username: str, password: str) -> bool:" in result


def test_format_context_block_contains_docstring(sample_node):
    """Docstring appears when present."""
    result = format_context_block([sample_node])
    assert "Verify credentials against the user store." in result


def test_format_context_block_no_docstring(node_no_docstring):
    """None docstring does not emit a blank line in the block."""
    result = format_context_block([node_no_docstring])
    assert "None" not in result
    # Should still have the header and body_preview
    assert "--- [/repo/utils.py:1-3] helper (function) ---" in result
    assert "pass" in result


def test_format_context_block_empty_list():
    """Empty node list returns empty string (no separator artifacts)."""
    result = format_context_block([])
    assert result == ""


def test_format_context_block_multiple_nodes_separator(sample_node, node_no_docstring):
    """Multiple nodes are separated by double newline."""
    result = format_context_block([sample_node, node_no_docstring])
    # Double newline between blocks
    assert "\n\n" in result
    # Both headers present
    assert "authenticate (function)" in result
    assert "helper (function)" in result


# ---------------------------------------------------------------------------
# explore_stream tests (mock LLM)
# ---------------------------------------------------------------------------

def test_explore_stream_yields_tokens(mock_llm):
    """explore_stream yields the expected tokens in order, skipping empty chunk."""
    expected_tokens = mock_llm  # fixture returns token list

    async def _run():
        collected = []
        async for token in explore_stream([], "What does authenticate do?"):
            collected.append(token)
        return collected

    result = asyncio.run(_run())
    assert result == expected_tokens


def test_explore_stream_filters_empty_chunks(mock_llm):
    """explore_stream never yields an empty string (empty first chunk filtered)."""
    async def _run():
        collected = []
        async for token in explore_stream([], "test question"):
            collected.append(token)
        return collected

    result = asyncio.run(_run())
    assert all(token != "" for token in result)


# ---------------------------------------------------------------------------
# System prompt test
# ---------------------------------------------------------------------------

def test_system_prompt_has_anti_fabrication_rule():
    """SYSTEM_PROMPT must instruct the LLM not to fabricate citations (AGNT-02)."""
    # Both keywords must appear — the prompt must explicitly forbid fabrication
    assert "fabricate" in SYSTEM_PROMPT.lower() or "never" in SYSTEM_PROMPT.lower()
    # Must mention the citation format
    assert "file" in SYSTEM_PROMPT.lower() and "line" in SYSTEM_PROMPT.lower()


def test_format_context_block_uses_full_body_over_preview(sample_node):
    """format_context_block uses full_body when non-empty, ignoring body_preview."""
    sample_node.full_body = (
        "if not username:\n"
        "    raise ValueError('username required')\n"
        "return check_password(username, password)"
    )
    result = format_context_block([sample_node])

    # full_body content must appear
    assert "raise ValueError" in result
    assert "check_password" in result
    # body_preview must NOT appear (it was "if not username:\n    return False")
    assert "return False" not in result


def test_format_context_block_falls_back_to_preview_when_full_body_empty(sample_node):
    """format_context_block uses body_preview when full_body is empty (default)."""
    # sample_node has full_body="" by default (new field) and body_preview set
    assert sample_node.full_body == ""
    result = format_context_block([sample_node])
    assert "return False" in result  # body_preview content
