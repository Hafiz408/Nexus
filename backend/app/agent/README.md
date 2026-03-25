# Agents

Routes queries to specialist agents based on intent, then evaluates output quality through a deterministic Critic gate with bounded retries.

## Flow

```
Question + intent_hint
    │
    ▼
  Router
    explicit hint (explain/debug/review/test) → skip LLM, confidence = 1.0
    auto / null → LLM classify (confidence < 0.6 → fallback to explain)
    │
    ▼
  Specialist
    ├── Explain  → graph RAG retrieval → stream tokens + citations
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
| **Explain** | graph RAG + LLM chain | streaming tokens, file citations |
| **Debug** | BFS forward on CALLS edges, 5-factor anomaly score | suspects, traversal path, diagnosis |
| **Review** | target node + 1-hop callers/callees → LLM | findings (severity, category, suggestion, file:line) |
| **Test** | marker-file framework detection + callees as mock targets | runnable test code, deterministic file path |

## Critic Scoring

| Dimension | Weight | How measured |
|---|---|---|
| Groundedness | 0.40 | Cited node IDs ∩ retrieved node IDs (set membership, no LLM) |
| Relevance | 0.35 | Required fields present (suspects, findings, test functions) |
| Actionability | 0.25 | Specificity — suspect count, suggestion completeness, test count |

## Orchestration

LangGraph `StateGraph` manages the router → specialist → critic loop. Each request gets a unique `thread_id` to prevent state bleed across concurrent queries. The graph is passed fresh on every invocation (not checkpointed — NetworkX DiGraphs aren't JSON-serializable).
