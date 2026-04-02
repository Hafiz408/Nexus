# Phase 14: RAGAS Eval - Research

**Researched:** 2026-03-19
**Domain:** RAG evaluation with RAGAS framework; golden dataset construction; graph-RAG vs naive vector comparison
**Confidence:** MEDIUM-HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| EVAL-01 | `backend/eval/golden_qa.json` contains 30 Q&A pairs based on the FastAPI repo, covering routing, middleware, DI, request parsing, response models, exception handlers, background tasks, security | Golden dataset structure section; JSON schema defined below |
| EVAL-02 | `eval/run_ragas.py` runs faithfulness, answer_relevancy, context_precision metrics against golden dataset | RAGAS 0.4.3 API section; EvaluationDataset.from_list() + evaluate() pattern |
| EVAL-03 | Results written to `eval/results/ragas_results_{timestamp}.json` with per-question breakdown | EvaluationResult.to_pandas() → df.to_json() workflow |
| EVAL-04 | Comparison experiment: graph-traversal RAG vs naive vector-only RAG side-by-side scores committed | Naive baseline implementation pattern using semantic_search only (no graph expansion) |
| TEST-01 | `pytest backend/tests/` passes all unit tests | Existing 8 test files all pass; eval script is NOT a pytest file — no new pytest tests required |
</phase_requirements>

---

## Summary

Phase 14 adds quantitative evaluation to the Nexus system. The goal is to produce committed evidence that graph-traversal RAG outperforms naive vector-only retrieval on at least one RAGAS metric. This requires three deliverables: a hand-curated golden Q&A dataset about FastAPI, a runnable evaluation script, and a committed comparison results file.

RAGAS 0.4.3 (released January 2026) is the current version. The key API change from older versions is that metrics are now imported from `ragas.metrics` (class instances, not module-level objects), the dataset is built via `EvaluationDataset.from_list(list[dict])`, and results come back as an `EvaluationResult` with a `.to_pandas()` method. The three required metrics — Faithfulness, ResponseRelevancy (called AnswerRelevancy in some docs), and ContextPrecision — all require an LLM at evaluation time, meaning real OpenAI API calls will be made during `run_ragas.py` execution.

The naive baseline for EVAL-04 is trivially implementable by calling `semantic_search()` directly (which already exists in `graph_rag.py`) and skipping the `expand_via_graph` and `rerank_and_assemble` steps. This produces vector-only top-k nodes that are passed to `explore_stream()` in the same way as the full graph pipeline. The comparison is thus clean and architecturally honest.

**Primary recommendation:** Use ragas==0.4.3, build `EvaluationDataset.from_list()` from the golden JSON, run both retrieval modes in the same script, save per-question scores to timestamped JSON, and commit a second `ragas_comparison_{timestamp}.json` that shows the side-by-side aggregate scores.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| ragas | 0.4.3 | RAG evaluation metrics (Faithfulness, ResponseRelevancy, ContextPrecision) | Dominant open-source RAG eval framework; reference-free metrics require no human annotation beyond ground-truth answers |
| langchain-openai | >=0.3.0 (already in requirements.txt) | LangchainLLMWrapper for RAGAS evaluator LLM | Already present; RAGAS integrates cleanly via LangchainLLMWrapper |
| openai | >=1.0.0 (already in requirements.txt) | LLM and embeddings for ragas metrics | Already present |
| pandas | latest compatible | EvaluationResult.to_pandas() → JSON serialization | RAGAS result export path |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| datasets | ragas dependency | Hugging Face datasets; installed as ragas transitive dep | Needed if using ragas TestsetGenerator (not required here — hand-curating golden dataset) |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| ragas 0.4.3 | deepeval | deepeval has richer assertions but heavier setup; ragas is simpler for this use case |
| Hand-curated golden_qa.json | ragas TestsetGenerator | Generator requires crawling FastAPI docs and is non-deterministic; hand-curation gives deterministic 30 pairs covering exact topics required |
| LangchainLLMWrapper | Direct AsyncOpenAI + llm_factory | LangchainLLMWrapper is the simpler path since ChatOpenAI is already configured in the project |

**Installation:**
```bash
pip install ragas==0.4.3 pandas
```

Add to `backend/requirements.txt`:
```
ragas==0.4.3
pandas
```

---

## Architecture Patterns

### Recommended Project Structure

```
eval/                          # eval dir at repo root (not inside backend/)
├── golden_qa.json             # 30 Q&A pairs (EVAL-01)
├── run_ragas.py               # evaluation script (EVAL-02, EVAL-03, EVAL-04)
└── results/                   # created by run_ragas.py at runtime
    ├── ragas_results_{timestamp}.json     # graph-RAG scores (EVAL-03)
    └── ragas_comparison_{timestamp}.json  # side-by-side comparison (EVAL-04)
```

Note: REQUIREMENTS.md EVAL-02 says `eval/run_ragas.py` (repo root `eval/` directory), while EVAL-01 says `backend/eval/golden_qa.json`. The success criteria in the phase description says `eval/golden_qa.json` and `eval/run_ragas.py`. Use repo-root `eval/` throughout — this avoids placing an eval script inside the backend package and keeps evaluation as a project-level concern.

### Pattern 1: Golden Dataset JSON Schema

**What:** A JSON array of objects, each representing one Q&A pair with retrieval metadata.
**When to use:** Static hand-curated file; loaded by run_ragas.py.

```python
# eval/golden_qa.json schema — each entry:
{
  "id": "Q01",
  "topic": "routing",
  "question": "How does FastAPI define path parameters with type validation?",
  "ground_truth": "FastAPI uses Python type annotations in path operation functions. Declaring a path parameter like `item_id: int` in the function signature automatically validates and converts the value.",
  "notes": "Covers routing + type coercion"
}
```

Fields:
- `id`: unique identifier (Q01..Q30)
- `topic`: one of routing, dependency_injection, middleware, background_tasks, security, request_parsing, response_models, exception_handlers
- `question`: the natural language query
- `ground_truth`: the reference answer (used by ContextPrecision and optionally Faithfulness)
- `notes`: optional human annotation (ignored by eval script)

### Pattern 2: Building EvaluationDataset from Golden JSON

**What:** Load golden_qa.json, run both retrieval modes, build dataset entries.
**When to use:** In run_ragas.py main loop.

```python
# Source: https://docs.ragas.io/en/stable/getstarted/rag_eval/
from ragas import EvaluationDataset
from ragas.dataset_schema import SingleTurnSample

samples = []
for qa in golden_qa:
    # Run retrieval to get contexts and response
    nodes, _ = graph_rag_retrieve(qa["question"], repo_path, G, max_nodes=10, hop_depth=1)
    context_texts = [
        f"{n.file_path}:{n.line_start}-{n.line_end}\n{n.signature}\n{n.docstring or ''}\n{n.body_preview}"
        for n in nodes
    ]
    response = await get_answer(nodes, qa["question"])  # calls explore_stream

    samples.append(SingleTurnSample(
        user_input=qa["question"],
        retrieved_contexts=context_texts,
        response=response,
        reference=qa["ground_truth"],
    ))

dataset = EvaluationDataset(samples=samples)
```

### Pattern 3: Running evaluate() with Required Metrics

**What:** Instantiate metrics with LLM, call evaluate(), extract per-question scores.
**When to use:** After building EvaluationDataset.

```python
# Source: https://docs.ragas.io/en/stable/references/evaluate/
from ragas import evaluate
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import Faithfulness, ResponseRelevancy, ContextPrecision
from langchain_openai import ChatOpenAI

evaluator_llm = LangchainLLMWrapper(ChatOpenAI(model="gpt-4o-mini", temperature=0))

results = evaluate(
    dataset=dataset,
    metrics=[
        Faithfulness(llm=evaluator_llm),
        ResponseRelevancy(llm=evaluator_llm),
        ContextPrecision(llm=evaluator_llm),
    ],
    show_progress=True,
    raise_exceptions=False,
)

# Per-question breakdown
df = results.to_pandas()
# df has columns: user_input, retrieved_contexts, response, reference,
#                 faithfulness, answer_relevancy, context_precision
```

### Pattern 4: Naive Vector-Only Baseline (for EVAL-04)

**What:** Run `semantic_search()` only — no graph expansion, no reranking. Top-k nodes by cosine similarity.
**When to use:** Baseline comparison mode in run_ragas.py.

```python
# Naive mode: vector-only, no BFS expansion
from app.retrieval.graph_rag import semantic_search
from app.ingestion.graph_store import load_graph

def vector_only_retrieve(query: str, repo_path: str, G: nx.DiGraph, max_nodes: int = 10):
    """Baseline: semantic search only, no graph traversal."""
    seed_results = semantic_search(query, repo_path, top_k=max_nodes)
    # Hydrate nodes from graph (same as graph_rag_retrieve does)
    nodes = []
    for node_id, score in seed_results:
        if node_id in G:
            attrs = G.nodes[node_id]
            from app.models.schemas import CodeNode
            node = CodeNode(**{k: v for k, v in attrs.items() if k in CodeNode.model_fields})
            nodes.append(node)
    return nodes
```

### Pattern 5: Saving Per-Question JSON Results

**What:** Convert EvaluationResult → pandas DataFrame → JSON file with timestamp.
**When to use:** After evaluate() call.

```python
import json
from datetime import datetime

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
results_path = f"eval/results/ragas_results_{timestamp}.json"

df = results.to_pandas()
# Drop non-serializable columns if any, add metadata
output = {
    "timestamp": timestamp,
    "mode": "graph_rag",
    "aggregate": {
        "faithfulness": float(df["faithfulness"].mean()),
        "answer_relevancy": float(df["answer_relevancy"].mean()),
        "context_precision": float(df["context_precision"].mean()),
    },
    "per_question": df.to_dict(orient="records"),
}

os.makedirs("eval/results", exist_ok=True)
with open(results_path, "w") as f:
    json.dump(output, f, indent=2, default=str)
```

### Anti-Patterns to Avoid

- **Running eval from inside backend/**: run_ragas.py needs to import `app.*` modules so it must run with `PYTHONPATH=backend` set, OR be placed inside the backend package. Do NOT embed it in `backend/app/` — it is not an app module.
- **Using `asyncio.run()` inside explore_stream loop**: explore_stream is an async generator. Use `asyncio.run(main())` at the top level of run_ragas.py.
- **Instantiating metric classes without LLM**: `Faithfulness()` with no LLM argument will raise at evaluation time. Always pass `llm=evaluator_llm`.
- **Treating EvaluationResult as a dict**: It is a custom object. Use `.to_pandas()` first, then serialize.
- **Forgetting `raise_exceptions=False`**: Individual question failures will abort the entire run without this flag.
- **Using old ragas 0.1.x import patterns**: `from ragas.metrics import faithfulness` (lowercase singleton) is the old API. Use `Faithfulness()` (class instantiation) in 0.4.x.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Faithfulness scoring | LLM prompt to check if answer is supported by context | `Faithfulness(llm=evaluator_llm)` | Handles claim decomposition, NLI classification; not trivial |
| Answer relevancy | Cosine similarity of question vs answer | `ResponseRelevancy(llm=evaluator_llm)` | Generates reverse questions, handles paraphrase; hand-roll misses this |
| Context precision | Fraction of relevant chunks | `ContextPrecision(llm=evaluator_llm)` | Uses LLM to judge relevance per chunk position; hand-roll can't replicate AP@k properly |
| Result aggregation | Manual averaging | `results.to_pandas()` | Handles NaN values, metric weighting, per-row breakdown automatically |

**Key insight:** RAGAS metrics are deceptively complex — Faithfulness does NLI decomposition, ResponseRelevancy generates reverse questions and measures embedding similarity. Custom implementations would be wrong or incomplete.

---

## Common Pitfalls

### Pitfall 1: Metric Import Path Confusion (0.4.x)

**What goes wrong:** Importing `from ragas.metrics import faithfulness` (lowercase) raises ImportError or returns deprecated singleton object that doesn't accept LLM parameter.
**Why it happens:** RAGAS changed its API significantly between 0.1.x and 0.2.x+. Old blog posts and examples use the singleton style.
**How to avoid:** Always use class instantiation: `Faithfulness(llm=evaluator_llm)`. Import from `ragas.metrics` (uppercase class names).
**Warning signs:** `AttributeError: 'Faithfulness' object has no attribute 'llm'` or `TypeError: evaluate() got unexpected keyword argument`.

### Pitfall 2: ContextPrecision Requires `reference` Field

**What goes wrong:** Running ContextPrecision with `SingleTurnSample` entries that have no `reference` field causes NaN scores silently.
**Why it happens:** ContextPrecision compares each context chunk against the reference answer to judge relevance. Without reference, it has no ground truth to compare against.
**How to avoid:** Always populate `reference=qa["ground_truth"]` in every SingleTurnSample when using ContextPrecision.
**Warning signs:** All context_precision scores are `NaN` in the results DataFrame.

### Pitfall 3: run_ragas.py Must Run with Correct PYTHONPATH

**What goes wrong:** `ModuleNotFoundError: No module named 'app'` when running `python eval/run_ragas.py`.
**Why it happens:** `app.*` imports in graph_rag.py, explorer.py etc. require the `backend/` directory to be on the Python path.
**How to avoid:** Run as `cd /path/to/nexus && PYTHONPATH=backend python eval/run_ragas.py` OR add `sys.path.insert(0, "backend")` at the top of run_ragas.py.
**Warning signs:** ImportError on first `from app.retrieval.graph_rag import ...`.

### Pitfall 4: Async Context for explore_stream

**What goes wrong:** `RuntimeError: This event loop is already running` or generator not fully consumed.
**Why it happens:** explore_stream is an async generator; run_ragas.py runs synchronously unless wrapped in `asyncio.run()`.
**How to avoid:** Wrap the entire evaluation loop in an `async def main()` and call it with `asyncio.run(main())`.
**Warning signs:** Empty string responses in the dataset, or RuntimeError at the first `await`.

### Pitfall 5: OpenAI API Rate Limits During Evaluation

**What goes wrong:** 30 questions × 3 metrics × LLM calls = ~90+ API requests. Rate limits hit with 429 errors.
**Why it happens:** RAGAS batches but still makes many LLM calls.
**How to avoid:** Use `RunConfig(timeout=120, max_retries=3)` parameter in `evaluate()`. Use `gpt-4o-mini` not `gpt-4o` to stay within rate limits for a dev eval run.
**Warning signs:** Partial NaN results in output DataFrame.

### Pitfall 6: pytest backend/tests/ and eval/ are Separate

**What goes wrong:** Placing run_ragas.py inside `backend/tests/` causes pytest collection to attempt to import it as a test module.
**Why it happens:** pytest collects all `test_*.py` files but also `*.py` if misconfigured.
**How to avoid:** Keep `eval/` at the repo root, completely outside `backend/tests/`. TEST-01 only requires `pytest backend/tests/` to pass — that suite already exists and must not be broken.
**Warning signs:** pytest collecting run_ragas.py and failing on `main()` import.

### Pitfall 7: Naive Baseline Must Use Same Answer Generation

**What goes wrong:** Comparing graph-RAG answers vs. naive answers that were generated differently (e.g., different prompt, different model) invalidates the comparison.
**Why it happens:** The context passed to the LLM differs between modes, but the answer generation chain should be identical.
**How to avoid:** Use the same `explore_stream()` function for both modes. The only difference is the `nodes` list passed to it.

---

## Code Examples

Verified patterns from official sources:

### Minimal run_ragas.py Entry Point

```python
# Source: https://docs.ragas.io/en/stable/getstarted/rag_eval/
import asyncio
import json
import os
import sys
from datetime import datetime

# Ensure app.* imports work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from ragas import EvaluationDataset, evaluate
from ragas.dataset_schema import SingleTurnSample
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import ContextPrecision, Faithfulness, ResponseRelevancy
from langchain_openai import ChatOpenAI

from app.config import get_settings
from app.ingestion.graph_store import load_graph
from app.retrieval.graph_rag import graph_rag_retrieve, semantic_search
from app.agent.explorer import explore_stream, format_context_block
from app.models.schemas import CodeNode


async def get_answer(nodes: list[CodeNode], question: str) -> str:
    """Collect full streamed answer from explore_stream."""
    tokens = []
    async for token in explore_stream(nodes, question):
        tokens.append(token)
    return "".join(tokens)


async def main():
    settings = get_settings()
    repo_path = os.environ.get("EVAL_REPO_PATH", "/fastapi")  # path to indexed FastAPI repo

    # Load graph from SQLite
    import networkx as nx
    from app.db.database import DATABASE_PATH
    G = load_graph(repo_path)

    # Load golden dataset
    golden_path = os.path.join(os.path.dirname(__file__), "golden_qa.json")
    with open(golden_path) as f:
        golden_qa = json.load(f)

    # Build samples for both modes
    graph_samples = []
    naive_samples = []

    for qa in golden_qa:
        question = qa["question"]
        reference = qa["ground_truth"]

        # --- Graph RAG mode ---
        graph_nodes, _ = graph_rag_retrieve(question, repo_path, G, max_nodes=10, hop_depth=1)
        graph_response = await get_answer(graph_nodes, question)
        graph_contexts = [
            f"{n.file_path}:{n.line_start}-{n.line_end}\n{n.signature}\n{n.body_preview}"
            for n in graph_nodes
        ]
        graph_samples.append(SingleTurnSample(
            user_input=question,
            retrieved_contexts=graph_contexts,
            response=graph_response,
            reference=reference,
        ))

        # --- Naive vector-only mode ---
        seed_results = semantic_search(question, repo_path, top_k=10)
        naive_nodes = [
            CodeNode(**{k: v for k, v in G.nodes[nid].items() if k in CodeNode.model_fields})
            for nid, _ in seed_results if nid in G
        ]
        naive_response = await get_answer(naive_nodes, question)
        naive_contexts = [
            f"{n.file_path}:{n.line_start}-{n.line_end}\n{n.signature}\n{n.body_preview}"
            for n in naive_nodes
        ]
        naive_samples.append(SingleTurnSample(
            user_input=question,
            retrieved_contexts=naive_contexts,
            response=naive_response,
            reference=reference,
        ))

    # Evaluator LLM (use gpt-4o-mini for rate-limit safety)
    evaluator_llm = LangchainLLMWrapper(
        ChatOpenAI(model="gpt-4o-mini", temperature=0, api_key=settings.openai_api_key)
    )
    metrics = [
        Faithfulness(llm=evaluator_llm),
        ResponseRelevancy(llm=evaluator_llm),
        ContextPrecision(llm=evaluator_llm),
    ]

    # Evaluate both datasets
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs(os.path.join(os.path.dirname(__file__), "results"), exist_ok=True)

    for mode, samples in [("graph_rag", graph_samples), ("naive_vector", naive_samples)]:
        dataset = EvaluationDataset(samples=samples)
        results = evaluate(dataset=dataset, metrics=metrics,
                           show_progress=True, raise_exceptions=False)
        df = results.to_pandas()
        output = {
            "timestamp": timestamp,
            "mode": mode,
            "aggregate": {
                "faithfulness": float(df["faithfulness"].mean()),
                "answer_relevancy": float(df["answer_relevancy"].mean()),
                "context_precision": float(df["context_precision"].mean()),
            },
            "per_question": df.to_dict(orient="records"),
        }
        out_path = os.path.join(
            os.path.dirname(__file__), "results",
            f"ragas_results_{mode}_{timestamp}.json"
        )
        with open(out_path, "w") as f:
            json.dump(output, f, indent=2, default=str)
        print(f"Saved {mode} results to {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
```

### golden_qa.json Topic Coverage

The 30 Q&A pairs must cover these FastAPI topics (per EVAL-01):

| Topic | Count | Example Question |
|-------|-------|-----------------|
| routing | 5 | "How does FastAPI register path operations for different HTTP methods?" |
| dependency_injection | 5 | "How do you declare a reusable dependency with `Depends()`?" |
| middleware | 4 | "How do you add CORS middleware in FastAPI?" |
| background_tasks | 4 | "How does BackgroundTasks work in a route handler?" |
| security | 4 | "How do you implement OAuth2 password bearer in FastAPI?" |
| request_parsing | 4 | "How does FastAPI parse a JSON request body?" |
| response_models | 4 | "How do you declare a response_model to filter output fields?" |

The `ground_truth` answers should be accurate descriptions of FastAPI internals, written based on the official FastAPI documentation — they do not need to be code snippets.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `from ragas.metrics import faithfulness` (singleton) | `Faithfulness(llm=evaluator_llm)` (class instance) | ragas 0.2.x | Old singletons deprecated; now requires explicit LLM binding |
| `Dataset` from HuggingFace datasets | `EvaluationDataset.from_list()` | ragas 0.2.x | No HuggingFace dependency for simple eval datasets |
| Manual ground truth for all metrics | Reference-free faithfulness | original | Faithfulness does not need `reference`; ContextPrecision still needs it |
| `evaluate(dataset, metrics=DEFAULT_METRICS)` | Pass explicit metric instances | ragas 0.2+ | `DEFAULT_METRICS` constant removed; always pass list |

**Deprecated/outdated:**
- `ragas.metrics.faithfulness` (lowercase singleton): Removed in 0.4. Use `Faithfulness(llm=...)` instead.
- `answer_relevancy` singleton: Use `ResponseRelevancy(llm=..., embeddings=...)` instead. Note: ResponseRelevancy requires both `llm` AND `embeddings` because it generates reverse questions and uses embedding similarity.
- `dataset["contexts"]` column name: New API uses `retrieved_contexts`.

---

## Open Questions

1. **ResponseRelevancy embeddings requirement**
   - What we know: ResponseRelevancy requires an `embeddings` parameter (it generates reverse questions and measures cosine similarity to the original question via embeddings).
   - What's unclear: Whether `LangchainLLMWrapper` automatically provides embeddings or whether a separate `LangchainEmbeddingsWrapper` must be passed.
   - Recommendation: Pass explicit embeddings: `ResponseRelevancy(llm=evaluator_llm, embeddings=LangchainEmbeddingsWrapper(OpenAIEmbeddings(model="text-embedding-3-small")))`. If it fails, fall back to `AnswerRelevancy` from `ragas.metrics.collections` which uses `llm_factory`.

2. **FastAPI repo availability for indexing**
   - What we know: The eval script needs `repo_path` pointing to an indexed FastAPI repository (embeddings in pgvector, graph in SQLite).
   - What's unclear: Whether the evaluator needs to run `POST /index` first or assumes the repo is already indexed.
   - Recommendation: Document in run_ragas.py that the FastAPI repo must be indexed first. Add a `--repo-path` CLI argument. Provide instructions in a top-level comment.

3. **`answer_relevancy` vs `response_relevancy` column name in DataFrame**
   - What we know: The requirement says "answer_relevancy" scores. RAGAS 0.4.x names the metric `ResponseRelevancy` but may output `answer_relevancy` or `response_relevancy` as the DataFrame column.
   - What's unclear: Exact column name in `to_pandas()` output for ragas 0.4.3.
   - Recommendation: Run a quick test after installation and adapt the column name in the JSON serialization. Use `df.columns.tolist()` to inspect.

---

## Sources

### Primary (HIGH confidence)
- https://docs.ragas.io/en/stable/references/evaluate/ — evaluate() function signature, parameters, return type
- https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/faithfulness/ — Faithfulness class name, import path, required inputs
- https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/context_precision/ — ContextPrecision class name, reference requirement
- https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/answer_relevance/ — ResponseRelevancy/AnswerRelevancy class names, embeddings requirement
- https://docs.ragas.io/en/stable/getstarted/rag_eval/ — EvaluationDataset.from_list() and end-to-end example
- https://pypi.org/project/ragas/ — Version 0.4.3 confirmed (released January 13, 2026)

### Secondary (MEDIUM confidence)
- https://docs.ragas.io/en/stable/concepts/components/eval_sample/ — SingleTurnSample field names (user_input, retrieved_contexts, response, reference)
- https://github.com/explodinggradients/ragas — Source code for metric class names
- Project codebase: `backend/app/retrieval/graph_rag.py` — semantic_search signature, graph_rag_retrieve signature (used to design naive baseline)
- Project codebase: `backend/app/agent/explorer.py` — explore_stream() signature (used to design answer generation wrapper)

### Tertiary (LOW confidence)
- Various blog posts and Medium articles about RAGAS evaluation patterns — used only for pitfall identification, not for API assertions

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — ragas 0.4.3 confirmed on PyPI with release date; langchain-openai already in project
- Architecture: MEDIUM — EvaluationDataset.from_list() and SingleTurnSample verified from official docs; exact DataFrame column names for 0.4.3 not confirmed
- Pitfalls: MEDIUM — import path changes verified from official docs; async/PYTHONPATH patterns from project patterns

**Research date:** 2026-03-19
**Valid until:** 2026-04-19 (ragas moves fast; verify metric class names against installed version before finalizing)
