"""Orchestrator — LangGraph StateGraph wiring all V2 agents.

Exposes:
  - NexusState     TypedDict for graph state
  - build_graph(checkpointer=None) -> CompiledGraph

Critical patterns (from RESEARCH.md):
  - All agent imports are LAZY (inside node function bodies) — prevents ValidationError
    at collection time when API keys are absent (established pattern from all prior agents).
  - G is typed Optional[object] (not nx.DiGraph) — SqliteSaver cannot serialize nx.DiGraph;
    callers MUST supply G on every invoke() call; never rely on checkpoint replay of G.
  - SqliteSaver requires check_same_thread=False — LangGraph writes checkpoints in background
    threads; default SQLite connection raises ProgrammingError otherwise.
  - _explain_node uses chain.invoke() (sync), NOT explore_stream() (async generator) —
    asyncio.run() inside a FastAPI endpoint raises "event loop already running".
  - loop_count incremented in _critic_node on the RETRY path only — specialist nodes have
    no knowledge of whether they are running for the first time or a retry.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any, Dict, List, Optional, TypedDict, Union

from langgraph.graph import END, START, StateGraph
from langgraph.checkpoint.base import BaseCheckpointSaver
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Process-level graph cache — keeps nx.DiGraph out of LangGraph state so
# SqliteSaver never tries to msgpack-serialize it (DiGraph is not serializable).
# Populated by set_graph() in query_router.py before each graph.invoke() call.
# ---------------------------------------------------------------------------

_G_CACHE: Dict[str, Any] = {}


def set_graph(repo_path: str, G: Any) -> None:
    """Store G in the process-level cache keyed by repo_path."""
    _G_CACHE[repo_path] = G


def _get_cached_graph(repo_path: str) -> Any:
    """Retrieve G from cache. Raises RuntimeError if not populated."""
    if repo_path not in _G_CACHE:
        raise RuntimeError(f"Graph not cached for repo_path={repo_path!r}. Call set_graph() first.")
    return _G_CACHE[repo_path]


# ---------------------------------------------------------------------------
# State definition
# ---------------------------------------------------------------------------

class NexusState(TypedDict):
    """Typed state for the LangGraph NexusState graph.

    G is NOT stored in state — nx.DiGraph is not msgpack-serializable so
    SqliteSaver would crash at checkpoint time. Instead, G lives in the
    module-level _G_CACHE dict; nodes retrieve it via _get_cached_graph().
    """
    # Query inputs
    question: str
    repo_path: str
    db_path: str                      # path to .nexus/graph.db — required by graph_rag_retrieve
    intent_hint: Optional[str]        # forwarded to route(); None or "auto" → LLM path

    # Context fields (no G here — see _G_CACHE above)
    target_node_id: Optional[str]     # required by review_node and test_node
    selected_file: Optional[str]      # REVW-03: range-targeted review
    selected_range: Optional[list]    # REVW-03: [line_start, line_end]
    repo_root: Optional[str]          # for tester framework detection

    # Routing output (set by router_node)
    intent: Optional[str]

    # Specialist result (set by whichever specialist ran)
    specialist_result: Optional[object]   # DebugResult | ReviewResult | TestResult | _ExplainResult

    # Critic output (set by critic_node)
    critic_result: Optional[object]       # CriticResult

    # Loop control
    loop_count: int                    # 0 on first attempt; incremented by critic_node on retry


# ---------------------------------------------------------------------------
# Minimal explain result carrier — Pydantic model for MemorySaver compatibility
# ---------------------------------------------------------------------------

class _ExplainResult(BaseModel):
    """Data carrier for the explain path result.

    Pydantic BaseModel (not a plain class) so MemorySaver can serialize/deserialize
    this via msgpack/jsonplus when checkpointing graph state. Plain Python classes
    are not msgpack-serializable and raise TypeError at checkpoint write time.
    """
    answer: str
    nodes: List[Any] = []
    stats: dict = {}


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _derive_target_from_file(
    G: "nx.DiGraph",
    selected_file: str | None,
    selected_range: list[int] | None,
) -> str | None:
    """Attempt to find the most specific graph node at the given file + line range.

    Scans G.nodes for nodes whose 'file_path' ends with selected_file
    (handles both absolute and relative path forms) and whose line_start/
    line_end bracket the midpoint of selected_range (or the start line
    when range is not provided).

    When multiple nodes overlap the target line (e.g. a method inside a class),
    the node with the smallest span (line_end - line_start) is returned so that
    the most specific symbol wins over its containing class/module.

    Returns the node_id string if found, None otherwise.
    """
    if not selected_file:
        return None
    target_line = None
    if selected_range and len(selected_range) >= 2:
        target_line = (selected_range[0] + selected_range[1]) // 2
    elif selected_range and len(selected_range) == 1:
        target_line = selected_range[0]

    best_node_id: str | None = None
    best_span: int = 10_000_000

    for node_id, attrs in G.nodes(data=True):
        node_file = attrs.get("file_path", "")
        # Match on suffix — handles absolute vs relative path forms
        if not (node_file.endswith(selected_file) or selected_file.endswith(node_file)):
            continue
        if target_line is None:
            return node_id   # first node in the file wins if no line given
        line_start = attrs.get("line_start", 0)
        line_end = attrs.get("line_end", 0)
        if line_start <= target_line <= line_end:
            span = line_end - line_start
            if span < best_span:
                best_span = span
                best_node_id = node_id

    return best_node_id


# ---------------------------------------------------------------------------
# Node functions — ALL agent imports are lazy (inside function bodies)
# ---------------------------------------------------------------------------

def _router_node(state: NexusState) -> dict:
    """Classify intent and store in state. Lazy-imports route() to avoid ValidationError."""
    from app.agent.router import route  # noqa: PLC0415

    logger.info("[router] classifying intent: hint=%r question=%r", state.get("intent_hint"), state["question"][:80])
    intent_result = route(state["question"], intent_hint=state.get("intent_hint"))
    logger.info("[router] resolved intent=%r", intent_result.intent)
    return {"intent": intent_result.intent}


def _route_by_intent(state: NexusState) -> str:
    """Conditional edge selector after router_node. Returns the intent string."""
    return state["intent"]  # "explain" | "debug" | "review" | "test"


def _read_raw_lines(file_path: str, selected_range: list[int] | None) -> str | None:
    """Read raw source lines from file_path for the given 1-based line range.

    Returns the extracted text, or None if the file cannot be read.
    Limits output to 200 lines to avoid flooding the LLM context window.
    """
    try:
        with open(file_path, encoding="utf-8", errors="replace") as fh:
            all_lines = fh.readlines()
        if selected_range and len(selected_range) >= 2:
            start = max(0, selected_range[0] - 1)   # 1-based → 0-based
            end = min(len(all_lines), selected_range[1])
            lines = all_lines[start:end]
        elif selected_range and len(selected_range) == 1:
            idx = max(0, selected_range[0] - 1)
            lines = all_lines[idx : idx + 1]
        else:
            lines = all_lines[:200]
        lines = lines[:200]  # hard cap
        return "".join(lines).rstrip()
    except OSError:
        return None


def build_explain_context(
    question: str,
    repo_path: str,
    db_path: str,
    selected_file: str | None,
    selected_range: list | None,
) -> tuple[list, dict, str]:
    """Synchronous context-builder for the explain streaming path.

    Performs graph-RAG retrieval then injects the user's selected node (if any)
    at the front of the context list and anchors the question to that symbol.

    Safe to call from asyncio.to_thread() — contains no async constructs.

    Returns:
        (nodes, stats, anchored_question)
        nodes:             List of CodeNode objects to use as LLM context.
        stats:             Retrieval stats dict from graph_rag_retrieve.
        anchored_question: Original question, rewritten to reference the selected
                           symbol when a selection is provided.
    """
    from app.retrieval.graph_rag import graph_rag_retrieve  # noqa: PLC0415
    from app.models.schemas import CodeNode  # noqa: PLC0415

    G = _get_cached_graph(repo_path)

    nodes: list = []
    stats: dict = {}
    logger.info("[explain] starting retrieval: file=%r range=%r", selected_file, selected_range)
    try:
        nodes, stats = graph_rag_retrieve(question, repo_path, G, db_path)
        logger.info("[explain] graph-rag retrieved %d nodes", len(nodes))
    except Exception as _exc:  # noqa: BLE001
        logger.warning("[explain] graph-rag retrieval failed, falling back to empty context: %s", _exc)

    anchored_question = question
    target_id = _derive_target_from_file(G, selected_file, selected_range)
    if target_id and target_id in G:
        attrs = G.nodes[target_id]
        try:
            selected_node = CodeNode(**{k: v for k, v in attrs.items() if k in CodeNode.model_fields})
            nodes = [selected_node] + [n for n in nodes if n.node_id != target_id]
            logger.info("[explain] injected selected node %r at front of context", target_id)
            anchored_question = (
                f"The user has selected `{selected_node.name}` "
                f"({selected_node.file_path}:{selected_node.line_start}-{selected_node.line_end}). "
                f"{question}"
            )
        except Exception:  # noqa: BLE001
            logger.warning("[explain] could not build CodeNode for target %r, skipping injection", target_id)
    elif selected_file:
        logger.info(
            "[explain] no graph node found for file=%r range=%r — not a indexed symbol (e.g. module-level code); "
            "falling back to raw selected lines",
            selected_file, selected_range,
        )
        raw_lines = _read_raw_lines(selected_file, selected_range)
        import os as _os  # noqa: PLC0415
        fname = _os.path.basename(selected_file)
        line_info = (
            f"lines {selected_range[0]}–{selected_range[1]}"
            if selected_range and len(selected_range) >= 2
            else f"line {selected_range[0]}" if selected_range else "selected lines"
        )
        if raw_lines:
            logger.info("[explain] injected %d raw lines as fallback context", len(raw_lines.splitlines()))
            # Inject raw lines as a synthetic CodeNode so they appear in
            # format_context_block(nodes) — the field the LLM is instructed
            # to answer from. Putting them only in anchored_question caused
            # the LLM to ignore them (system prompt: answer ONLY from context).
            from app.models.schemas import CodeNode  # noqa: PLC0415
            line_start = selected_range[0] if selected_range else 1
            line_end = selected_range[1] if selected_range and len(selected_range) >= 2 else line_start
            synthetic = CodeNode(
                node_id=f"{selected_file}::__module_selection__",
                name=f"selected code ({line_info})",
                type="module",
                file_path=selected_file,
                line_start=line_start,
                line_end=line_end,
                body_preview=raw_lines,
                signature="",
                docstring="Note: this is module-level code not tracked as a graph symbol.",
            )
            nodes = [synthetic] + nodes
            anchored_question = (
                f"The user selected code in `{fname}` ({line_info}). "
                f"It is module-level code (not a named symbol in the graph index). "
                f"{question}"
            )
        else:
            logger.warning("[explain] could not read raw lines for file=%r", selected_file)
            anchored_question = (
                f"Note: The selected code in `{fname}` ({line_info}) is not in the graph index "
                f"(it is likely module-level code or has not been indexed as a symbol) "
                f"and the source file could not be read. "
                f"{question}"
            )

    return nodes, stats, anchored_question


def _explain_node(state: NexusState) -> dict:
    """Explain node — delegates context building to build_explain_context, then
    calls chain.invoke() (sync) to produce the full answer for the LangGraph path.

    The streaming path in query_router.py uses build_explain_context directly
    and pipes the result through explore_stream for token-by-token output.
    """
    from langchain_core.prompts import ChatPromptTemplate  # noqa: PLC0415
    from app.core.model_factory import get_llm  # noqa: PLC0415
    from app.agent.prompts import SYSTEM_PROMPT  # noqa: PLC0415
    from app.agent.explorer import format_context_block  # noqa: PLC0415

    nodes, stats, anchored_question = build_explain_context(
        state["question"],
        state["repo_path"],
        state["db_path"],
        state.get("selected_file"),
        state.get("selected_range"),
    )

    llm = get_llm()
    prompt = ChatPromptTemplate.from_messages([
        ("system", "{system_prompt}"),
        ("human", "Context:\n{context}\n\nQuestion: {question}"),
    ])
    chain = prompt | llm
    logger.info("[explain] invoking LLM with %d context nodes", len(nodes))
    response = chain.invoke({
        "system_prompt": SYSTEM_PROMPT,
        "context": format_context_block(nodes),
        "question": anchored_question,
    })
    answer = response.content if hasattr(response, "content") else str(response)
    logger.info("[explain] done, answer length=%d chars", len(answer))
    return {"specialist_result": _ExplainResult(answer=answer, nodes=nodes, stats=stats)}


def _debug_node(state: NexusState) -> dict:
    """Invoke the Debugger agent. Lazy-imports debug() to avoid ValidationError."""
    from app.agent.debugger import debug  # noqa: PLC0415

    logger.info("[debug] starting debugger agent")
    G = _get_cached_graph(state["repo_path"])
    result = debug(state["question"], G)
    logger.info("[debug] done")
    return {"specialist_result": result}


def _review_node(state: NexusState) -> dict:
    """Invoke the Reviewer agent. Lazy-imports review() to avoid ValidationError."""
    from app.agent.reviewer import review, ReviewResult  # noqa: PLC0415

    logger.info("[review] starting reviewer agent: target=%r file=%r range=%r",
                state.get("target_node_id"), state.get("selected_file"), state.get("selected_range"))
    G = _get_cached_graph(state["repo_path"])
    target_id = state["target_node_id"]

    # Fallback: derive target from active editor context when not provided
    if not target_id:
        target_id = _derive_target_from_file(
            G,
            state.get("selected_file"),
            state.get("selected_range"),
        )
        logger.info("[review] derived target from selection: %r", target_id)

    if not target_id:
        # No usable target — return empty ReviewResult with explanation
        return {
            "specialist_result": ReviewResult(
                findings=[],
                retrieved_nodes=[],
                summary="No target node identified. Open a file and select a function, then try again.",
            )
        }

    result = review(
        state["question"],
        G,
        target_id,
        selected_file=state.get("selected_file"),
        selected_range=state.get("selected_range"),
    )
    logger.info("[review] done: findings=%d", len(getattr(result, "findings", [])))
    return {"specialist_result": result}


def _test_node(state: NexusState) -> dict:
    """Invoke the Tester agent. Lazy-imports test() to avoid ValidationError."""
    from app.agent.tester import test as run_test, TestResult  # noqa: PLC0415

    logger.info("[test] starting tester agent: target=%r file=%r range=%r",
                state.get("target_node_id"), state.get("selected_file"), state.get("selected_range"))
    G = _get_cached_graph(state["repo_path"])
    target_id = state["target_node_id"]

    # Fallback: derive target from active editor context when not provided
    if not target_id:
        target_id = _derive_target_from_file(
            G,
            state.get("selected_file"),
            state.get("selected_range"),
        )
        logger.info("[test] derived target from selection: %r", target_id)

    if not target_id:
        logger.warning("[test] no target node found, returning empty result")
        return {
            "specialist_result": TestResult(
                test_code="# No target node identified. Open a file and select a function, then try again.",
                test_file_path="tests/test_unknown.py",
                framework="pytest",
            )
        }

    result = run_test(
        state["question"],
        G,
        target_id,
        repo_root=state.get("repo_root"),
    )
    logger.info("[test] done")
    return {"specialist_result": result}


def _critic_node(state: NexusState) -> dict:
    """Apply deterministic quality gate. Increments loop_count on the RETRY path.

    The specialist node that ran is unaware of whether it is a first attempt or
    a retry. Only critic_node knows the loop semantics and increments here.

    loop_count semantics (verified against critic.py hard-cap logic):
      loop_count=0: first specialist run; cap fires at >=2, so retry is allowed
      loop_count=1: first retry; still below cap, retry still allowed
      loop_count=2: second retry; cap fires, passed=True unconditionally
    """
    from app.agent.critic import critique  # noqa: PLC0415

    current_loop = state["loop_count"]
    logger.info("[critic] evaluating result: loop_count=%d intent=%r", current_loop, state.get("intent"))
    result = critique(state["specialist_result"], loop_count=current_loop)

    # Only increment when routing back — on the pass path, loop_count is irrelevant
    new_loop_count = current_loop + 1 if not result.passed else current_loop
    if result.passed:
        logger.info("[critic] passed — routing to done")
    else:
        logger.info("[critic] retry — routing back to %r (loop_count now %d)", state.get("intent"), new_loop_count)
    return {"critic_result": result, "loop_count": new_loop_count}


def _route_after_critic(state: NexusState) -> str:
    """Conditional edge selector after critic_node.

    Returns "done" (routes to END) when the critic passed.
    Returns the current intent (routes back to the same specialist) when retrying.
    """
    if state["critic_result"].passed:  # type: ignore[union-attr]
        return "done"
    return state["intent"]  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Graph factory
# ---------------------------------------------------------------------------

def build_graph(checkpointer: BaseCheckpointSaver | None = None):
    """Compile and return the NexusState graph.

    Args:
        checkpointer: Pass MemorySaver() for tests (no sqlite thread issues).
                      Pass SqliteSaver(conn) for production. If None, graph
                      runs without checkpointing (state not persisted).

    Returns:
        A compiled LangGraph application ready for graph.invoke().

    Production usage:
        import sqlite3
        from langgraph.checkpoint.sqlite import SqliteSaver
        conn = sqlite3.connect("data/checkpoints.db", check_same_thread=False)
        graph = build_graph(checkpointer=SqliteSaver(conn))
        result = graph.invoke(initial_state,
                              config={"configurable": {"thread_id": "session-xyz"}})

    Test usage:
        from langgraph.checkpoint.memory import MemorySaver
        graph = build_graph(checkpointer=MemorySaver())
    """
    g = StateGraph(NexusState)

    # Register nodes
    g.add_node("router_node", _router_node)
    g.add_node("explain_node", _explain_node)
    g.add_node("debug_node", _debug_node)
    g.add_node("review_node", _review_node)
    g.add_node("test_node", _test_node)
    g.add_node("critic_node", _critic_node)

    # Entry: always start at router
    g.add_edge(START, "router_node")

    # Router → specialist (conditional on intent)
    g.add_conditional_edges(
        "router_node",
        _route_by_intent,
        {
            "explain": "explain_node",
            "debug":   "debug_node",
            "review":  "review_node",
            "test":    "test_node",
        },
    )

    # Every specialist feeds into the critic
    for specialist in ("explain_node", "debug_node", "review_node", "test_node"):
        g.add_edge(specialist, "critic_node")

    # Critic → done (END) or back to the same specialist (retry loop)
    g.add_conditional_edges(
        "critic_node",
        _route_after_critic,
        {
            "explain": "explain_node",
            "debug":   "debug_node",
            "review":  "review_node",
            "test":    "test_node",
            "done":    END,
        },
    )

    return g.compile(checkpointer=checkpointer)
