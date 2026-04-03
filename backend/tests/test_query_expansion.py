import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_returns_llm_content():
    from app.retrieval.query_expansion import hyde_expand

    mock_response = MagicMock()
    mock_response.content = "def validate_path(item_id: int): ..."
    mock_llm = AsyncMock()
    mock_llm.ainvoke.return_value = mock_response

    with patch("app.retrieval.query_expansion.get_llm", return_value=mock_llm):
        result = await hyde_expand("How does FastAPI validate path parameters?")

    assert result == "def validate_path(item_id: int): ..."
    assert mock_llm.ainvoke.called


@pytest.mark.asyncio
async def test_returns_empty_string_on_llm_error():
    from app.retrieval.query_expansion import hyde_expand

    mock_llm = AsyncMock()
    mock_llm.ainvoke.side_effect = RuntimeError("LLM unavailable")

    with patch("app.retrieval.query_expansion.get_llm", return_value=mock_llm):
        result = await hyde_expand("any query")

    assert result == ""


@pytest.mark.asyncio
async def test_strips_surrounding_whitespace():
    from app.retrieval.query_expansion import hyde_expand

    mock_response = MagicMock()
    mock_response.content = "  \ndef foo(): pass\n  "
    mock_llm = AsyncMock()
    mock_llm.ainvoke.return_value = mock_response

    with patch("app.retrieval.query_expansion.get_llm", return_value=mock_llm):
        result = await hyde_expand("any query")

    assert result == "def foo(): pass"


@pytest.mark.asyncio
async def test_query_appears_in_prompt():
    from app.retrieval.query_expansion import hyde_expand

    mock_response = MagicMock()
    mock_response.content = "code"
    mock_llm = AsyncMock()
    mock_llm.ainvoke.return_value = mock_response

    query = "How does dependency injection resolve yield dependencies?"
    with patch("app.retrieval.query_expansion.get_llm", return_value=mock_llm):
        await hyde_expand(query)

    call_args = mock_llm.ainvoke.call_args[0][0]
    assert any(query in str(msg) for msg in call_args)
