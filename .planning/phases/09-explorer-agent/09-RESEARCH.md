# Phase 9: Explorer Agent - Research

**Researched:** 2026-03-19
**Domain:** LangChain LCEL streaming agent, LangSmith tracing, system prompt design
**Confidence:** HIGH

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| AGNT-01 | `explorer.py` implements LangChain runnable (not LangGraph) that takes retrieved context + question, generates grounded answer | LCEL chain pattern: `ChatPromptTemplate.from_messages() | ChatOpenAI` is the correct runnable; verified from langchain-core + langchain-openai docs |
| AGNT-02 | System prompt in `prompts.py` instructs agent to cite only file:line present in retrieved nodes; never fabricate | Prompt engineering pattern documented; system message must list allowed citation format and explicitly forbid fabrication |
| AGNT-03 | Uses `llm.astream()` and yields SSE-formatted tokens | `async for chunk in chain.astream(input)` yields `AIMessageChunk` objects; `chunk.content` is the text string; verified from official docs |
| AGNT-04 | All LLM calls traced in LangSmith via `LANGCHAIN_TRACING_V2=true` and `tracing_v2_enabled` context manager | `tracing_v2_enabled` context manager confirmed present in `langchain_core.tracers.context`; `LANGCHAIN_TRACING_V2=true` env var activates it automatically without code changes |
| AGNT-05 | Context blocks formatted as `--- [file_path:line_start-line_end] name (type) ---\n{signature}\n{docstring}\n{body_preview}` | Pure string formatting; pattern is deterministic — read CodeNode fields directly |
</phase_requirements>

---

## Summary

Phase 9 builds `explorer.py` — a LangChain LCEL runnable that receives a list of `CodeNode` objects (from Phase 8's `graph_rag_retrieve`) plus a question, formats a context block, runs a grounded-answer prompt through `ChatOpenAI`, and yields SSE-formatted tokens via `astream()`. The module is not an agent in the tool-calling sense; it is a streaming LLM chain with a carefully designed system prompt that enforces citation discipline.

The implementation requires two new files: `backend/app/agent/prompts.py` (system prompt as a string constant) and `backend/app/agent/explorer.py` (the `ExplorerChain` or `explore_stream()` async generator). Phase 10 will wrap this in the `POST /query` FastAPI endpoint, so Phase 9 only needs to expose a clean async generator interface — no FastAPI code belongs here.

The only new dependencies are `langchain-openai>=0.3.0` and `langchain-core>=0.3.0` (which are installed together as `langchain-openai` pulls `langchain-core` automatically), plus `langsmith>=0.7.0` for the tracing context manager import. The `.env.example` already documents `LANGCHAIN_TRACING_V2` and `LANGCHAIN_API_KEY`, confirming tracing is expected.

**Primary recommendation:** Implement `explore_stream(nodes, question)` as an async generator using `chain.astream()` where `chain = prompt | llm`. Use `tracing_v2_enabled` as a context manager wrapping the `astream` call. Format the context block in a separate pure function `format_context_block(nodes)` that is trivially testable without any LLM.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| langchain-openai | >=0.3.0 (latest: 1.1.11 as of 2026-03-09) | `ChatOpenAI` LLM class with `astream()` | The official LangChain OpenAI integration; pulls `langchain-core` as dependency |
| langchain-core | >=0.3.0 (latest: 1.2.19) | `ChatPromptTemplate`, `AIMessageChunk`, `tracing_v2_enabled` | Core abstractions for LCEL chains; ships with langchain-openai |
| langsmith | >=0.7.0 (latest: 0.7.20 as of 2026-03-18) | `tracing_v2_enabled` context manager | Tracing SDK; AGNT-04 requirement |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| openai | >=1.0.0 (already in requirements.txt) | Underlying OpenAI API client | Already installed; `langchain-openai` wraps it |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| langchain-openai | openai directly | Would lose LCEL pipe operator, `astream()` chunking, and LangSmith auto-tracing |
| tracing_v2_enabled | LANGSMITH_TRACING env var only | Env var is fine for global tracing; context manager gives per-call scoping; AGNT-04 requires both |

**Installation:**
```bash
pip install langchain-openai>=0.3.0 langsmith>=0.7.0
```

Add to `backend/requirements.txt`:
```
langchain-openai>=0.3.0
langsmith>=0.7.0
```

---

## Architecture Patterns

### Recommended Project Structure

```
backend/app/
├── agent/
│   ├── __init__.py
│   ├── prompts.py       # SYSTEM_PROMPT constant (AGNT-02)
│   └── explorer.py      # explore_stream() async generator (AGNT-01, AGNT-03, AGNT-04, AGNT-05)
├── api/
│   └── index_router.py  # existing — Phase 10 adds query_router.py here
├── retrieval/
│   └── graph_rag.py     # Phase 8 output — imported by explorer.py
└── models/
    └── schemas.py       # CodeNode — already defined
```

### Pattern 1: LCEL Chain with astream()

**What:** A `ChatPromptTemplate | ChatOpenAI` pipe forms a `RunnableSequence`. Call `chain.astream(input_dict)` to get an async iterator of `AIMessageChunk` objects. Each chunk's `.content` attribute holds the incremental text (a `str`; may be empty string on the first chunk).

**When to use:** Any time you need token-by-token streaming from a fixed prompt template. No tool calling, no branching — just prompt → LLM → stream.

**Example:**
```python
# Source: langchain-openai official docs + verified astream() pattern
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

prompt = ChatPromptTemplate.from_messages([
    ("system", "{system_prompt}"),
    ("human", "{context}\n\nQuestion: {question}"),
])
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
chain = prompt | llm

async def explore_stream(nodes, question):
    input_dict = {
        "system_prompt": SYSTEM_PROMPT,
        "context": format_context_block(nodes),
        "question": question,
    }
    async for chunk in chain.astream(input_dict):
        if chunk.content:   # first chunk is always empty string — skip it
            yield chunk.content
```

### Pattern 2: LangSmith Tracing with tracing_v2_enabled

**What:** `tracing_v2_enabled` is a `@contextmanager` in `langchain_core.tracers.context` that wraps a code block and registers a `LangChainTracer` callback. Every LCEL chain invocation inside the `with` block is automatically recorded in LangSmith. Setting `LANGCHAIN_TRACING_V2=true` in the environment achieves the same effect globally without code changes.

**When to use:** Wrap the `chain.astream()` call with `tracing_v2_enabled` so each streaming invocation appears as a trace. This satisfies AGNT-04 without requiring a LangSmith API key in tests (key is optional; tracing silently no-ops if `LANGCHAIN_API_KEY` is unset).

**Example:**
```python
# Source: langchain_core.tracers.context — verified from GitHub master branch
from langchain_core.tracers.context import tracing_v2_enabled

async def explore_stream(nodes, question, project_name="nexus-v1"):
    input_dict = {
        "system_prompt": SYSTEM_PROMPT,
        "context": format_context_block(nodes),
        "question": question,
    }
    with tracing_v2_enabled(project_name=project_name):
        async for chunk in chain.astream(input_dict):
            if chunk.content:
                yield chunk.content
```

**Signature of tracing_v2_enabled (verified from langchain-ai/langchain master):**
```python
@contextmanager
def tracing_v2_enabled(
    project_name: str | None = None,
    *,
    example_id: str | UUID | None = None,
    tags: list[str] | None = None,
    client: LangSmithClient | None = None,
) -> Generator[LangChainTracer, None, None]: ...
```

### Pattern 3: Context Block Formatting (AGNT-05)

**What:** A pure function that converts a list of `CodeNode` objects into the PRD-specified string format.

**When to use:** Always — called once before chain invocation. No LLM involvement. Trivially unit-testable.

**Example:**
```python
# Source: AGNT-05 format from REQUIREMENTS.md
from app.models.schemas import CodeNode

def format_context_block(nodes: list[CodeNode]) -> str:
    blocks = []
    for node in nodes:
        header = f"--- [{node.file_path}:{node.line_start}-{node.line_end}] {node.name} ({node.type}) ---"
        docstring_line = node.docstring or ""
        body = "\n".join([node.signature, docstring_line, node.body_preview]).strip()
        blocks.append(f"{header}\n{body}")
    return "\n\n".join(blocks)
```

### Pattern 4: Citation-Grounding System Prompt (AGNT-02)

**What:** A string constant in `prompts.py` that:
1. Tells the LLM its role (code Q&A assistant)
2. Explains the context block format it will receive
3. Mandates citation format: `file_path:line_start-line_end`
4. Explicitly forbids fabricating citations not present in the context
5. Provides a fallback instruction: say "I'm not sure" if the context doesn't support an answer

**When to use:** This is injected as the system message on every chain call.

**Example skeleton:**
```python
# Source: prompts.py — to be created
SYSTEM_PROMPT = """You are an expert code assistant. You answer questions about a codebase using ONLY the code context provided below.

Rules:
1. Cite code by referencing the exact file path and line range shown in the context headers, e.g. `auth/login.py:42-55`.
2. Never fabricate a citation. If a piece of code is not in the provided context, do not reference it.
3. If the context does not contain enough information to answer the question, say: "I'm not certain based on the retrieved context."
4. Keep answers concise and grounded in the provided code snippets.
"""
```

### Anti-Patterns to Avoid

- **Lazy chain construction:** Do not build `chain = prompt | llm` inside the generator function — the chain is stateless and safe to build once at module level; rebuilding on every call wastes memory.
- **Checking `chunk.text` instead of `chunk.content`:** `AIMessageChunk.content` is the correct attribute for the streamed text string. `.text` is a property that calls `.content` internally, but `.content` is the canonical field.
- **Skipping the empty-string guard:** The first chunk from `astream()` always has `content=''`. Downstream SSE consumers that emit `data: \n\n` for empty strings create malformed events. Always guard with `if chunk.content:`.
- **Using `asyncio.run()` inside the generator:** The generator itself is `async`; callers (Phase 10 FastAPI) will iterate it in an already-running event loop. Never call `asyncio.run()` inside an async generator.
- **Putting the `tracing_v2_enabled` context manager outside the async for loop but inside a sync function:** The context manager is sync-compatible but must wrap the `astream()` call. For async generators, place the `with` block inside the `async def` before the `async for`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Token streaming from OpenAI | Custom `openai.chat.completions.create(stream=True)` loop | `ChatOpenAI.astream()` | LangChain handles retry, timeout, chunk reassembly, AIMessageChunk typing, and LangSmith callbacks automatically |
| LangSmith tracing | Manual `requests.post` to LangSmith API | `tracing_v2_enabled` context manager | Auto-captures nested spans, run IDs, latency, token counts; hand-rolled logging misses all of this |
| Prompt assembly | f-string interpolation in the caller | `ChatPromptTemplate.from_messages()` | Template validates input variables at construction time; prevents missing-variable bugs silently swallowed by f-strings |

**Key insight:** The LCEL pipe operator (`|`) composes runnables so that `astream()` propagates through the full chain — prompt formatting + LLM call — in one call. There is no benefit to splitting these into separate async calls.

---

## Common Pitfalls

### Pitfall 1: `tracing_v2_enabled` inside `async for` causes only first chunk to be traced

**What goes wrong:** Placing the `with tracing_v2_enabled():` block *inside* the `async for chunk in chain.astream(...)` loop registers a new tracer per token rather than per invocation. LangSmith sees thousands of one-token runs.

**Why it happens:** Misreading where the context manager boundary belongs.

**How to avoid:** Wrap the entire `astream()` call, not individual `yield` statements.

**Warning signs:** LangSmith dashboard shows hundreds of runs per question each with a single token.

### Pitfall 2: `langchain-openai` not in requirements.txt — import fails at startup

**What goes wrong:** `from langchain_openai import ChatOpenAI` raises `ModuleNotFoundError` despite `openai` being installed. The `openai` package and `langchain-openai` are separate packages.

**Why it happens:** `langchain-openai` is not included in the existing `requirements.txt` (verified: it only lists `openai>=1.0.0`).

**How to avoid:** Add `langchain-openai>=0.3.0` and `langsmith>=0.7.0` to `backend/requirements.txt`.

**Warning signs:** `ModuleNotFoundError: No module named 'langchain_openai'` on container startup.

### Pitfall 3: Lazy client init pattern must be preserved

**What goes wrong:** Constructing `ChatOpenAI(api_key=...)` at module level causes `ValidationError` when `OPENAI_API_KEY` is absent (e.g., in unit tests that mock the LLM).

**Why it happens:** Pydantic validates the API key at instantiation time, not at call time.

**How to avoid:** Construct the `ChatOpenAI` instance lazily inside the function or use the factory pattern: `ChatOpenAI(api_key=get_settings().openai_api_key)`. The chain object (`prompt | llm`) can be module-level only if the `llm` is constructed lazily or if `api_key` is passed from settings at import time (safe if settings are always loaded from env). Given the project pattern (lazy init in embedder, graph_rag), construct lazily.

**Warning signs:** Tests fail with `ValidationError: openai_api_key field required` when no env var set, during module import.

### Pitfall 4: Patching `langchain_openai.ChatOpenAI` in tests vs. module namespace

**What goes wrong:** `monkeypatch.setattr("langchain_openai.ChatOpenAI", mock_cls)` does not affect the already-imported binding in `app.agent.explorer` if the module uses `from langchain_openai import ChatOpenAI`.

**Why it happens:** Python's `from ... import` binds the name at import time; patching the source module after import has no effect.

**How to avoid:** Patch at the target module namespace: `monkeypatch.setattr("app.agent.explorer.ChatOpenAI", mock_cls)`. This is the same pattern used in `conftest.py` for `app.retrieval.graph_rag.OpenAI`.

**Warning signs:** Mock has no effect; real API calls fire in tests even after `monkeypatch.setattr`.

### Pitfall 5: `file_path` in CodeNode is an absolute path

**What goes wrong:** The context block emits absolute paths like `/Users/user/repos/myproject/src/auth.py:10-20`. The VS Code extension (Phase 12) expects relative paths for citation linking.

**Why it happens:** `CodeNode.file_path` stores the absolute path as populated by the AST parser.

**How to avoid:** For Phase 9, output the absolute path verbatim as stored in CodeNode — this matches what the graph RAG returns and what the citation format requires. The Phase 10/12 layer is responsible for path normalization if needed. Do not add path-manipulation logic to `explorer.py`.

**Warning signs:** None in Phase 9 — this is a concern for Phase 12 but worth noting.

### Pitfall 6: LANGCHAIN_TRACING_V2 vs LANGSMITH_TRACING naming

**What goes wrong:** The LangSmith docs (as of 2026) refer to `LANGSMITH_TRACING=true` as the current env var, while the project's `.env.example` uses `LANGCHAIN_TRACING_V2=false`.

**Why it happens:** LangSmith renamed the env var; `LANGCHAIN_TRACING_V2` is the backward-compatible alias that is still supported and still works.

**How to avoid:** Use `LANGCHAIN_TRACING_V2=true` as documented in `.env.example` — it remains supported. Do not change the env var name in the project. The `tracing_v2_enabled` context manager responds to both.

**Warning signs:** None — both names activate tracing. Changing `.env.example` is unnecessary.

---

## Code Examples

Verified patterns from official sources:

### Complete explore_stream() Implementation

```python
# Source: langchain-core astream() + tracing_v2_enabled from langchain-ai/langchain master
from __future__ import annotations

from typing import AsyncGenerator

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tracers.context import tracing_v2_enabled
from langchain_openai import ChatOpenAI

from app.agent.prompts import SYSTEM_PROMPT
from app.config import get_settings
from app.models.schemas import CodeNode


def _build_chain():
    """Construct LCEL chain lazily to avoid ValidationError on import with no API key."""
    settings = get_settings()
    llm = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0,
        api_key=settings.openai_api_key,
    )
    prompt = ChatPromptTemplate.from_messages([
        ("system", "{system_prompt}"),
        ("human", "Context:\n{context}\n\nQuestion: {question}"),
    ])
    return prompt | llm


def format_context_block(nodes: list[CodeNode]) -> str:
    """Format CodeNodes per AGNT-05 spec."""
    blocks = []
    for node in nodes:
        header = (
            f"--- [{node.file_path}:{node.line_start}-{node.line_end}]"
            f" {node.name} ({node.type}) ---"
        )
        docstring_line = node.docstring or ""
        body = "\n".join(filter(None, [node.signature, docstring_line, node.body_preview]))
        blocks.append(f"{header}\n{body}")
    return "\n\n".join(blocks)


async def explore_stream(
    nodes: list[CodeNode],
    question: str,
    project_name: str = "nexus-v1",
) -> AsyncGenerator[str, None]:
    """Stream answer tokens grounded in retrieved CodeNode context.

    Yields:
        str: Individual token strings as they arrive from the LLM.
    """
    chain = _build_chain()
    input_dict = {
        "system_prompt": SYSTEM_PROMPT,
        "context": format_context_block(nodes),
        "question": question,
    }
    with tracing_v2_enabled(project_name=project_name):
        async for chunk in chain.astream(input_dict):
            if chunk.content:
                yield chunk.content
```

### AIMessageChunk Access Pattern

```python
# Source: verified — chunk.content is the text string per AIMessageChunk docs
async for chunk in chain.astream(input_dict):
    # chunk is AIMessageChunk
    # chunk.content: str  — may be "" on first chunk
    # chunk.id: str       — run ID
    if chunk.content:     # skip empty first chunk
        yield chunk.content
```

### Test Pattern (No API Key Needed)

```python
# Source: adapted from conftest.py Phase 8 pattern
from unittest.mock import AsyncMock, MagicMock
from langchain_core.messages import AIMessageChunk

def mock_llm_fixture(monkeypatch):
    """Mock ChatOpenAI astream to yield test tokens without API key."""
    async def _fake_astream(input_dict, **kwargs):
        for token in ["Hello", " world", "."]:
            yield AIMessageChunk(content=token)

    mock_llm = MagicMock()
    mock_llm.astream = _fake_astream
    # Patch at module namespace (from-import binding rule)
    monkeypatch.setattr("app.agent.explorer.ChatOpenAI", MagicMock(return_value=mock_llm))
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `langchain.chat_models.ChatOpenAI` | `langchain_openai.ChatOpenAI` | langchain ~0.1.0 (2024) | Must install `langchain-openai` separately; do not import from `langchain` directly |
| `tracing_enabled()` context manager | `tracing_v2_enabled()` | langchain ~0.1.x | `tracing_enabled` is deprecated; `tracing_v2_enabled` is current |
| `LANGCHAIN_TRACING_V2` env var | `LANGSMITH_TRACING` env var | langsmith SDK rename | Both still work; project uses `LANGCHAIN_TRACING_V2` — keep it |
| `chain.run()` synchronous call | `chain.astream()` async generator | LCEL introduction 2023 | Async streaming is now the canonical pattern |

**Deprecated/outdated:**
- `from langchain.chat_models import ChatOpenAI`: removed from `langchain` package; must use `langchain_openai`
- `tracing_enabled()`: use `tracing_v2_enabled()` instead
- `streaming=True` constructor flag: still supported but `astream()` is the preferred API in LCEL

---

## Open Questions

1. **Should `_build_chain()` be called once at module level or per-call?**
   - What we know: The `ChatOpenAI` object is stateless once constructed; building it per-call wastes a settings lookup each time.
   - What's unclear: Whether building at module level causes issues when `OPENAI_API_KEY` is absent during test collection.
   - Recommendation: Use a module-level `_chain: RunnableSequence | None = None` sentinel with a lazy initializer function `_get_chain()` — same pattern as Phase 5/8 lazy client init. This avoids repeated construction and avoids import-time failures.

2. **Does `explore_stream()` receive the graph `G` (DiGraph) or pre-retrieved `nodes` (list[CodeNode])?**
   - What we know: Phase 8's `graph_rag_retrieve` returns `(list[CodeNode], stats_dict)`. The Phase 10 endpoint will call retrieval first, then pass `nodes` to `explore_stream`.
   - What's unclear: Whether the agent should call `graph_rag_retrieve` internally or receive pre-retrieved nodes.
   - Recommendation: `explore_stream(nodes, question)` — receive pre-retrieved nodes. This keeps the agent focused on generation, not retrieval. Separating concerns makes each layer independently testable.

3. **What model string should be used for the ChatOpenAI instance?**
   - What we know: Phase 8 uses `text-embedding-3-small` for embeddings. The project uses `gpt-4o-mini` or `gpt-4o` for generation (implied by `.env.example` `OPENAI_API_KEY`).
   - What's unclear: Whether the model name should be hardcoded or come from `settings`.
   - Recommendation: Add `model_name: str = "gpt-4o-mini"` to `Settings` in `config.py` so it can be overridden via `.env`. Default to `gpt-4o-mini` for cost efficiency.

---

## Sources

### Primary (HIGH confidence)
- `langchain-ai/langchain` GitHub master branch `libs/core/langchain_core/tracers/context.py` — `tracing_v2_enabled` signature and implementation verified
- PyPI `langchain-openai` — version 1.1.11 confirmed current (published 2026-03-09)
- PyPI `langsmith` — version 0.7.20 confirmed current (published 2026-03-18)
- `reference.langchain.com/python/integrations/langchain_openai/ChatOpenAI/` — ChatOpenAI parameters and `astream()` usage

### Secondary (MEDIUM confidence)
- `docs.langchain.com/langsmith/trace-with-langchain` — LangSmith tracing env vars; `LANGSMITH_TRACING` vs `LANGCHAIN_TRACING_V2` backward compatibility confirmed via multiple sources
- `aurelio.ai/learn/langchain-streaming` — `AIMessageChunk.content` attribute access pattern and empty-first-chunk behavior verified
- `reference.langchain.com/python/langchain-core/prompts/chat/ChatPromptTemplate` — `from_messages()` tuple format confirmed

### Tertiary (LOW confidence)
- Community examples of FastAPI + LangChain SSE streaming — patterns consistent with official docs but not from official source

---

## Metadata

**Confidence breakdown:**
- Standard stack (langchain-openai versions): HIGH — verified from PyPI directly
- Architecture (explore_stream pattern): HIGH — derived from verified `astream()` and `tracing_v2_enabled` docs
- Context formatting (AGNT-05): HIGH — pure string formatting from known CodeNode schema
- System prompt design (AGNT-02): MEDIUM — prompt engineering is qualitative; citation enforcement relies on LLM compliance
- Pitfalls: HIGH for import/patching issues (same class of problem already encountered in Phase 5/8); MEDIUM for tracing context manager placement

**Research date:** 2026-03-19
**Valid until:** 2026-04-18 (stable ecosystem; LangChain API changes infrequently at patch level)
