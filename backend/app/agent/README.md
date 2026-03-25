# Multi-Agent System (V2)

The multi-agent system routes queries to specialized agents (Debug, Review, Test, or Explain) based on intent, each producing structured output grounded in the code graph. A deterministic Critic evaluates quality and may trigger retries (hard cap: 2 loops).

## Architecture Overview

```
Query with intent_hint
    ↓
Router Agent
    • Classification: explicit hint or LLM-based intent detection
    • Returns: IntentResult(intent, confidence, reasoning)
    ↓
Specialist Agent (conditional routing)
    ├─ Explain → Explorer (semantic search + token streaming)
    ├─ Debug → Debugger (BFS anomaly scoring + diagnosis)
    ├─ Review → Reviewer (1-hop context + structured findings)
    └─ Test → Tester (framework detection + code generation)
    ↓
Specialist Result (DebugResult | ReviewResult | TestResult | ExplainResult)
    ↓
Critic Agent
    • Deterministic quality gate: score = 0.4*G + 0.35*R + 0.25*A
    • CriticResult(score, passed, feedback, loop_count)
    ↓
Decision
    ├─ passed=True → return result
    └─ passed=False AND loop_count < max_loops → retry specialist
    ↓
MCP Tools (optional)
    • Test: write_test_file (filesystem)
    • Review: post_review_comments (GitHub API)
    ↓
Final Result to Extension
```

## LangGraph StateGraph

**State Definition (`NexusState`):**

```python
class NexusState(TypedDict):
    # Inputs
    question: str
    repo_path: str
    intent_hint: str | None          # "debug" | "review" | "test" | "explain" | None | "auto"
    G: object | None                 # nx.DiGraph (NOT checkpointed)
    target_node_id: str | None       # Required for review/test
    selected_file: str | None        # For range-targeted review (REVW-03)
    selected_range: tuple | None     # (line_start, line_end)
    repo_root: str | None            # For framework detection (tester)

    # Routing
    intent: str | None               # Set by router_node

    # Results
    specialist_result: object | None
    critic_result: object | None

    # Loop control
    loop_count: int                  # 0 on first attempt, incremented on retry
```

**Graph Topology:**

```
START
  ↓
router_node
  ↓
[conditional] _route_by_intent → {explain, debug, review, test}
  ├─→ explain_node ─┐
  ├─→ debug_node   ─┤
  ├─→ review_node  ─┼→ critic_node
  └─→ test_node   ─┘
       ↓
[conditional] _route_after_critic
  ├─→ done (END)
  └─→ explain_node (retry loop)
      debug_node
      review_node
      test_node
```

**Node Functions:**

```python
def _router_node(state: NexusState) -> dict:
    """Route intent. Lazy-import route() to avoid API key validation."""
    from app.agent.router import route
    intent_result = route(state["question"], intent_hint=state.get("intent_hint"))
    return {"intent": intent_result.intent}

def _explain_node(state: NexusState) -> dict:
    """V1 compatibility: graph_rag + chain.invoke (sync, not streaming)."""
    # Call graph_rag_retrieve, build prompt, invoke LLM
    # Return _ExplainResult(answer, nodes, stats)

def _debug_node(state: NexusState) -> dict:
    """Call Debugger agent."""
    result = debug(state["question"], state["G"])
    return {"specialist_result": result}

def _review_node(state: NexusState) -> dict:
    """Call Reviewer agent."""
    result = review(state["question"], state["G"], state["target_node_id"], ...)
    return {"specialist_result": result}

def _test_node(state: NexusState) -> dict:
    """Call Tester agent."""
    result = test(state["question"], state["G"], state["target_node_id"], ...)
    return {"specialist_result": result}

def _critic_node(state: NexusState) -> dict:
    """Evaluate result quality and set loop_count for retry logic."""
    result = critique(state["specialist_result"], loop_count=state["loop_count"])
    new_loop_count = state["loop_count"] + 1 if not result.passed else state["loop_count"]
    return {"critic_result": result, "loop_count": new_loop_count}

def _route_after_critic(state: NexusState) -> str:
    """Route based on critic's passed decision."""
    if state["critic_result"].passed:
        return "done"
    return state["intent"]  # route back to specialist for retry
```

---

## Intent Routing Table

| Hint Value | Router Behavior | LLM Call? |
|-----------|-----------------|-----------|
| `"explain"` | Skip LLM, return intent="explain", confidence=1.0 | No |
| `"debug"` | Skip LLM, return intent="debug", confidence=1.0 | No |
| `"review"` | Skip LLM, return intent="review", confidence=1.0 | No |
| `"test"` | Skip LLM, return intent="test", confidence=1.0 | No |
| `None` | Use LLM classification | Yes |
| `"auto"` | Use LLM classification | Yes |
| (empty string) | Use LLM classification | Yes |
| invalid | Use LLM classification | Yes |

**Router Confidence Thresholds:**
- If `confidence >= 0.6`: Return LLM's intent as-is
- If `confidence < 0.6`: Override to "explain" (safe fallback)

---

## Specialist Agents

### Router (`router.py`)

**Purpose:** Classify developer intent from a free-text question.

**Output:**
```python
class IntentResult(BaseModel):
    intent: Literal["explain", "debug", "review", "test"]
    confidence: float  # [0.0, 1.0]
    reasoning: str     # one sentence
```

**Prompt:**
```
SYSTEM: You are an intent classifier. Classify the developer query into:
- explain: understanding code, architecture, concepts
- debug: finding bugs, errors, crashes
- review: code quality, security, style, best practice
- test: generating test cases or test code

Return only: intent, confidence (0.0–1.0), reasoning.
```

---

### Debugger (`debugger.py`)

**Purpose:** Localize bugs by traversing the call graph and anomaly-scoring nodes.

**Algorithm:**

1. **Entry detection:** Find nodes whose name appears in the question (case-insensitive)
2. **BFS traversal:** Forward-only (CALLS edges) from entry nodes, up to max_hops (default 4)
3. **Anomaly scoring:** 5-factor formula per visited node:
   ```
   anomaly_score = 0.30 * complexity
                 + 0.25 * missing_error_handling
                 + 0.20 * bug_keyword_match
                 + 0.15 * out_degree
                 + 0.10 * (1 - pagerank)
   ```
   where:
   - **complexity:** cyclomatic complexity proxy (keyword count)
   - **missing_error_handling:** absence of try/except/raise in code
   - **bug_keyword_match:** fraction of error/exception keywords in question matching code
   - **out_degree:** normalized fan-out (calls many other functions)
   - **inverted PageRank:** isolated code is more suspicious than central code

4. **Suspect extraction:** Top-5 by anomaly score
5. **Impact radius:** Direct callers of the top suspect
6. **LLM diagnosis:** Generates a grounded narrative (CRITICAL: only mentions node names from traversal)

**Output:**
```python
class SuspectNode(BaseModel):
    node_id: str
    file_path: str
    line_start: int
    anomaly_score: float  # [0.0, 1.0]
    reasoning: str

class DebugResult(BaseModel):
    suspects: list[SuspectNode]       # ranked by anomaly_score desc, max 5
    traversal_path: list[str]         # all visited node_ids
    impact_radius: list[str]          # direct callers of top suspect
    diagnosis: str                    # LLM narrative
```

**Constraints:**
- LLM prompt includes traversal_path with node names so it can only cite real names
- If traversal_path is empty, LLM still produces a reasonable guess (no hallucination penalty)

---

### Reviewer (`reviewer.py`)

**Purpose:** Generate structured code review findings for a target node.

**Algorithm:**

1. **Context assembly:** target node + 1-hop CALLS predecessors (callers) + 1-hop CALLS successors (callees)
2. **Prompt:** Pass context + question to LLM with structured output schema
3. **Post-filter:** Drop any Finding whose file_path is not in retrieved context (groundedness enforcement)
4. **Return:** ReviewResult with validated findings + summary

**Output:**
```python
class Finding(BaseModel):
    severity: Literal["critical", "warning", "info"]
    category: str  # "security" | "error-handling" | "performance" | "style" | "correctness"
    description: str
    file_path: str  # MUST be in context
    line_start: int
    line_end: int
    suggestion: str

class ReviewResult(BaseModel):
    findings: list[Finding]
    retrieved_nodes: list[str]   # node_ids assembled into context
    summary: str                 # LLM narrative
```

**Constraints:**
- file_path post-filter ensures findings reference only code seen by the LLM
- range-targeted review (REVW-03) optionally narrows to `selected_file` + `selected_range`

---

### Tester (`tester.py`)

**Purpose:** Generate runnable test code with framework awareness.

**Algorithm:**

1. **Framework detection:** Scan repo_root for marker files (pytest.ini, jest.config.js, etc.)
   - Priority: pytest → jest → vitest → junit
   - Fallback: search for test_*.py files
   - Final fallback: "unknown"

2. **Mock targets:** Enumerate callees (CALLS successors) of target node
3. **Test code generation:** LLM with with_structured_output(_LLMTestOutput)
   - Generates EXACTLY 3+ test functions (happy path, error, edge cases)
   - All callees are mocked/patched
   - Uses framework-specific syntax

4. **Test file path derivation:** Deterministic, never from LLM
   - Python: `tests/test_{target_name}.py` or `test_{target_name}.py`
   - TypeScript: `src/__tests__/{target_name}.test.ts`
   - Java: `src/test/java/.../Test{TargetName}.java`

**Output:**
```python
class _LLMTestOutput(BaseModel):
    test_code: str

class TestResult(BaseModel):
    test_code: str           # runnable test code
    test_file_path: str      # deterministic path (not LLM-generated)
    framework: str           # detected framework
```

**Constraints:**
- Test file path is ALWAYS derived, never generated (prevents LLM path injection)
- LLM only outputs test code, no metadata
- Framework detection is deterministic (marker files, not LLM guessing)

---

### Critic (`critic.py`)

**Purpose:** Deterministic quality gate. No LLM call — pure scoring.

**Algorithm:**

1. **Groundedness:** Fraction of cited nodes in retrieved set
   ```python
   cited_nodes = extract_node_ids(specialist_result)
   retrieved_nodes = extract_retrieval_context(specialist_result)
   groundedness = len(cited & retrieved) / len(cited) if cited else 1.0
   ```

2. **Relevance:** Content quality (specialist-specific)
   - **Debug:** suspects + diagnosis present → 1.0 else 0.3
   - **Review:** findings + summary present → 1.0 else 0.3
   - **Test:** test_code with "def test_" → 1.0 else 0.3
   - **Explain:** answer + nodes present → 1.0 else 0.3

3. **Actionability:** Specificity (specialist-specific)
   - **Debug:** min(len(suspects) / 5, 1.0)
   - **Review:** fraction of findings with suggestions
   - **Test:** min(count("def test_") / 3, 1.0)
   - **Explain:** N/A, default 0.5

4. **Composite score:**
   ```
   score = 0.40 * groundedness
         + 0.35 * relevance
         + 0.25 * actionability
   ```

5. **Decision:**
   - If `loop_count >= max_critic_loops` (default 2): passed=True (hard cap)
   - Else if `score >= critic_threshold` (default 0.7): passed=True
   - Else: passed=False, generate feedback text for retry

**Output:**
```python
class CriticResult(BaseModel):
    score: float                  # [0.0, 1.0]
    groundedness: float
    relevance: float
    actionability: float
    passed: bool
    feedback: str | None          # None if passed=True
    loop_count: int
```

**Hard Cap Logic:**

```
loop_count=0: first attempt
  → if score < threshold → retry (now loop_count=1)
loop_count=1: first retry
  → if score < threshold → retry (now loop_count=2)
loop_count=2: second retry
  → hard cap fires → passed=True unconditionally
```

---

### Explorer (`explorer.py`) — V1 Path

**Purpose:** V1 compatibility. SSE token streaming with citations.

**Algorithm:**

1. **Graph RAG retrieval:** (same as V1 query path)
   - Semantic search → BFS expansion → reranking
   - Returns: [CodeNode, ...], stats

2. **Token streaming:**
   ```python
   chain = SYSTEM_PROMPT | LLM
   async for chunk in chain.astream({"context": ..., "question": ...}):
       yield chunk.content
   ```

3. **LangSmith tracing:** (optional, if LANGCHAIN_TRACING_V2=true)

**Output:**
```python
class _ExplainResult(BaseModel):
    answer: str
    nodes: list[Any]  # [CodeNode, ...]
    stats: dict
```

---

## Retry & Loop Control

**Loop Semantics:**

```python
# orchestrator.py, _critic_node()
current_loop = state["loop_count"]
result = critique(specialist_result, loop_count=current_loop)

# Only increment on RETRY path
if not result.passed:
    new_loop_count = current_loop + 1
else:
    new_loop_count = current_loop
```

**Retry Routing:**

```python
def _route_after_critic(state) -> str:
    if state["critic_result"].passed:
        return "done"  # End the loop
    return state["intent"]  # Route back to same specialist (explain/debug/review/test)
```

---

## Lazy Import Pattern

All agent modules use lazy imports inside function bodies to prevent API key validation errors during pytest collection:

```python
def debug(question: str, G: nx.DiGraph) -> DebugResult:
    from app.core.model_factory import get_llm  # INSIDE function
    from app.config import get_settings         # INSIDE function
    # ... rest of implementation
```

This pattern is applied consistently across:
- `router.py`
- `orchestrator.py` (all node functions)
- `debugger.py`
- `reviewer.py`
- `tester.py`
- `explorer.py`

---

## Example: Full V2 Debug Flow

**User Query:**
```
{
  "question": "Why is graph_rag_retrieve returning empty results?",
  "repo_path": "/path/to/nexus",
  "intent_hint": "debug",
  "target_node_id": "backend/app/retrieval/graph_rag.py::graph_rag_retrieve",
  "G": <networkx.DiGraph>
}
```

**Execution:**

1. **Router:** hint="debug" → skip LLM → intent="debug", confidence=1.0
2. **Conditional routing:** route to debug_node
3. **Debugger:**
   - Entry nodes: "graph_rag.py::graph_rag_retrieve"
   - BFS forward (CALLS) up to 4 hops:
     - semantic_search → get_embedding_client → embed
     - expand_via_graph → ego_graph (NetworkX)
     - rerank_and_assemble → sorting
   - Anomaly scores:
     - semantic_search (0.72): high complexity, many branches
     - embed (0.45): simpler, but isolated
     - rerank_and_assemble (0.58): moderate
   - Top 5 suspects: [semantic_search (0.72), rerank_and_assemble (0.58), ...]
   - Impact radius: [graph_rag_retrieve (caller)]
   - LLM diagnosis: "semantic_search may be returning empty due to pgvector connection issues..."
   - Return DebugResult

4. **Critic:**
   - Cited nodes: {semantic_search, rerank_and_assemble, ...}
   - Retrieved nodes: {graph_rag_retrieve, semantic_search, ...}
   - Groundedness: 5/5 = 1.0
   - Relevance: suspects + diagnosis → 1.0
   - Actionability: 5 suspects / 5 → 1.0
   - Score: 0.4*1.0 + 0.35*1.0 + 0.25*1.0 = 1.0
   - Passed: True (score >= threshold)
   - Feedback: None

5. **Route after critic:** passed=True → "done" (END)

6. **Result:** DebugResult streamed back to extension via SSE

---

## Configuration & Tuning

**Tuning Knobs (`.env`):**

| Variable | Default | Impact |
|----------|---------|--------|
| `max_critic_loops` | 2 | Hard cap on retries |
| `critic_threshold` | 0.7 | Min score to pass |
| `debugger_max_hops` | 4 | BFS depth for debugging |
| `reviewer_context_hops` | 1 | Context radius for review |

**Model-Level (`.env`):**

| Variable | Default | Impact |
|----------|---------|--------|
| `llm_provider` | mistral | Router/Critic/Specialist LLM |
| `model_name` | mistral-small-latest | Model used by all agents |

---

## Testing

All agents are unit-tested with mocks:

| Test File | Coverage |
|-----------|----------|
| `test_router_agent.py` | Intent classification, confidence fallback |
| `test_orchestrator.py` | All 4 intents, retry loop, checkpointing |
| `test_debugger.py` | BFS, anomaly scoring, impact radius |
| `test_reviewer.py` | Context assembly, groundedness enforcement |
| `test_tester.py` | Framework detection, mock targets, file path derivation |
| `test_critic.py` | Scoring formula, hard cap, retry routing |

Run all:
```bash
python -m pytest backend/tests/test_agent*.py backend/tests/test_orchestrator.py -v
```

---

## Future Work (Phase 27+)

- [ ] Multi-turn agent conversations (maintain state across queries)
- [ ] Tool use (MCP integration for code execution)
- [ ] Streaming specialist results (token-by-token for agents, not just V1)
- [ ] Custom specialist registration (plugin architecture)
- [ ] Adaptive loop control (learn optimal max_loops per intent)