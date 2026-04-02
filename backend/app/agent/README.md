# Agents

Routes queries to specialist agents based on intent, then evaluates output quality through a deterministic Critic gate with bounded retries.

## Flow

```
Question + intent_hint
    │
    ▼
  Router
    debug / review / test → Agent path (LangGraph orchestrator)
    auto / null / explain → Streaming path (graph RAG + token stream, bypasses orchestrator)
    │
    ▼  [Agent path only]
  Specialist
    ├── Debug    → BFS call graph → anomaly score → top-5 suspects + diagnosis
    ├── Review   → 1-hop context assembly → structured findings
    └── Test     → framework detection → test code generation
    │
    ▼
  Critic  (deterministic, no LLM)
    score = 0.4 × groundedness + 0.35 × relevance + 0.25 × actionability
    │
    ├── score ≥ 0.7       → accept
    ├── score < 0.7 AND loop < 2  → retry specialist with feedback
    └── loop ≥ 2          → force accept (hard cap)
    │
    ▼
  MCP Tools (optional side-effects)
    ├── Review → post findings to GitHub PR
    └── Test   → write test file to repo
```

## Specialists

| Agent | Core logic | Output |
|---|---|---|
| **Debug** | BFS forward on CALLS edges, 5-factor anomaly score | suspects, traversal path, diagnosis |
| **Review** | target node + 1-hop callers/callees → LLM | findings (severity, category, suggestion, file:line) |
| **Test** | marker-file framework detection + callees as mock targets | runnable test code, deterministic file path |

> **Explain** is not an agent — it uses the streaming path directly (graph RAG → token stream → citations) without going through the LangGraph orchestrator.

## Critic Scoring

| Dimension | Weight | How measured |
|---|---|---|
| Groundedness | 0.40 | Cited node IDs ∩ retrieved node IDs (set membership, no LLM) |
| Relevance | 0.35 | Required fields present (suspects, findings, test functions) |
| Actionability | 0.25 | Specificity — suspect count, suggestion completeness, test count |

## State Fields

Key fields in `NexusState` relevant to retrieval:

| Field | Type | Notes |
|---|---|---|
| `max_nodes` | `int` | Forwarded to `graph_rag_retrieve`; controls result cap |
| `hop_depth` | `int` | Forwarded to `graph_rag_retrieve`; controls BFS radius |
| `db_path` | `str` | Path to `.nexus/graph.db` — required by all retrieval calls |
| `intent_hint` | `str \| None` | `None` or `"auto"` → streaming path; `"explain"` → `_explain_node`; others → specialist |

`max_nodes` and `hop_depth` are user-configurable via VS Code settings (`nexus.maxNodes`, `nexus.hopDepth`) and are passed through from the extension on every request.

## Orchestration

LangGraph `StateGraph` manages the router → specialist → critic loop. Each request gets a unique `thread_id` to prevent state bleed across concurrent queries. The graph is passed fresh on every invocation (not checkpointed — NetworkX DiGraphs aren't JSON-serializable).
