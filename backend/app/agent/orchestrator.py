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

import sqlite3
from typing import Any, List, Optional, TypedDict, Union

from langgraph.graph import END, START, StateGraph
from langgraph.checkpoint.base import BaseCheckpointSaver
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# State definition
# ---------------------------------------------------------------------------

class NexusState(TypedDict):
    """Typed state for the LangGraph NexusState graph.

    G is Optional[object] (not nx.DiGraph) so SqliteSaver does not attempt
    JSON serialization of a NetworkX graph. Callers must supply G on every
    graph.invoke() call — it cannot be recovered from a checkpoint.
    """
    # Query inputs
    question: str
    repo_path: str
    intent_hint: Optional[str]        # forwarded to route(); None or "auto" → LLM path

    # Graph input — NOT checkpointed (nx.DiGraph is not JSON-serializable)
    G: Optional[object]               # nx.DiGraph passed through; typed as object for LangGraph compat
    target_node_id: Optional[str]     # required by review_node and test_node
    selected_file: Optional[str]      # REVW-03: range-targeted review
    selected_range: Optional[tuple]   # REVW-03: (line_start, line_end)
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
    """Attempt to find the graph node at the given file + line range.

    Scans G.nodes for a node whose 'file_path' ends with selected_file
    (handles both absolute and relative path forms) and whose line_start/
    line_end bracket the midpoint of selected_range (or the start line
    when range is not provided).

    Returns the node_id string if found, None otherwise.
    """
    if not selected_file:
        return None
    import networkx as nx  # noqa: PLC0415 — already a lazy-import module
    target_line = None
    if selected_range and len(selected_range) >= 2:
        target_line = (selected_range[0] + selected_range[1]) // 2
    elif selected_range and len(selected_range) == 1:
        target_line = selected_range[0]

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
            return node_id
    return None


# ---------------------------------------------------------------------------
# Node functions — ALL agent imports are lazy (inside function bodies)
# ---------------------------------------------------------------------------

def _router_node(state: NexusState) -> dict:
    """Classify intent and store in state. Lazy-imports route() to avoid ValidationError."""
    from app.agent.router import route  # noqa: PLC0415

    intent_result = route(state["question"], intent_hint=state.get("intent_hint"))
    return {"intent": intent_result.intent}


def _route_by_intent(state: NexusState) -> str:
    """Conditional edge selector after router_node. Returns the intent string."""
    return state["intent"]  # "explain" | "debug" | "review" | "test"


def _explain_node(state: NexusState) -> dict:
    """V1 compatibility path: graph_rag_retrieve + chain.invoke() (sync, not streaming).

    Does NOT call explore_stream() — that is an async generator which cannot be
    awaited with asyncio.run() inside a FastAPI async endpoint (raises RuntimeError:
    'This event loop is already running'). chain.invoke() produces identical answer
    quality using the same prompt and LLM.

    Lazy-imports get_llm and the SYSTEM_PROMPT to avoid ValidationError at import time.
    Does NOT import _get_chain() from explorer.py — that function calls get_llm() and
    get_settings() at call time without the lazy-import guard that this node requires
    (the guard is the lazy import pattern itself, which is already applied here).
    """
    import networkx as nx  # noqa: PLC0415
    from langchain_core.prompts import ChatPromptTemplate  # noqa: PLC0415
    from app.core.model_factory import get_llm  # noqa: PLC0415
    from app.agent.prompts import SYSTEM_PROMPT  # noqa: PLC0415
    from app.agent.explorer import format_context_block  # noqa: PLC0415

    G: nx.DiGraph = state["G"]  # type: ignore[assignment]
    question = state["question"]
    repo_path = state["repo_path"]

    # Attempt graph-RAG retrieval. Falls back to empty node list if postgres is
    # unavailable (e.g. in tests where G is provided directly).
    nodes: list = []
    stats: dict = {}
    try:
        from app.retrieval.graph_rag import graph_rag_retrieve  # noqa: PLC0415
        nodes, stats = graph_rag_retrieve(question, repo_path, G)
    except Exception:  # noqa: BLE001
        # In offline tests / environments without postgres, retrieval is skipped.
        # The LLM will receive an empty context block and still produce an answer.
        pass

    # Build chain inline — same prompt structure as explorer._get_chain()
    llm = get_llm()
    prompt = ChatPromptTemplate.from_messages([
        ("system", "{system_prompt}"),
        ("human", "Context:\n{context}\n\nQuestion: {question}"),
    ])
    chain = prompt | llm
    response = chain.invoke({
        "system_prompt": SYSTEM_PROMPT,
        "context": format_context_block(nodes),
        "question": question,
    })
    answer = response.content if hasattr(response, "content") else str(response)
    return {"specialist_result": _ExplainResult(answer=answer, nodes=nodes, stats=stats)}


def _debug_node(state: NexusState) -> dict:
    """Invoke the Debugger agent. Lazy-imports debug() to avoid ValidationError."""
    import networkx as nx  # noqa: PLC0415
    from app.agent.debugger import debug  # noqa: PLC0415

    G: nx.DiGraph = state["G"]  # type: ignore[assignment]
    result = debug(state["question"], G)
    return {"specialist_result": result}


def _review_node(state: NexusState) -> dict:
    """Invoke the Reviewer agent. Lazy-imports review() to avoid ValidationError."""
    import networkx as nx  # noqa: PLC0415
    from app.agent.reviewer import review, ReviewResult  # noqa: PLC0415

    G: nx.DiGraph = state["G"]  # type: ignore[assignment]
    target_id = state["target_node_id"]

    # Fallback: derive target from active editor context when not provided
    if not target_id:
        target_id = _derive_target_from_file(
            G,
            state.get("selected_file"),
            state.get("selected_range"),
        )

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
    return {"specialist_result": result}


def _test_node(state: NexusState) -> dict:
    """Invoke the Tester agent. Lazy-imports test() to avoid ValidationError."""
    import networkx as nx  # noqa: PLC0415
    from app.agent.tester import test as run_test, TestResult  # noqa: PLC0415

    G: nx.DiGraph = state["G"]  # type: ignore[assignment]
    target_id = state["target_node_id"]

    # Fallback: derive target from active editor context when not provided
    if not target_id:
        target_id = _derive_target_from_file(
            G,
            state.get("selected_file"),
            state.get("selected_range"),
        )

    if not target_id:
        # No usable target — return empty TestResult with explanation
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
    result = critique(state["specialist_result"], loop_count=current_loop)

    # Only increment when routing back — on the pass path, loop_count is irrelevant
    new_loop_count = current_loop + 1 if not result.passed else current_loop
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
