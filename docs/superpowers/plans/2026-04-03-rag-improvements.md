# RAG Pipeline Improvement + Three-Way RAGAS Evaluation

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the golden QA dataset for code-intelligence use cases, implement RRF seed fusion + BFS score threshold + HyDE query expansion + cross-encoder reranking in a new improved pipeline, run a three-way RAGAS comparison (naive | graph | improved), then iterate on the pipeline until **all three metrics exceed 0.75** (faithfulness, answer_relevancy, context_precision).

**Architecture:**
- New retrieval modules (`query_expansion.py`, `reranker.py`, `improved_rag.py`) live alongside existing `graph_rag.py` in `backend/app/retrieval/`.
- `graph_rag.py` gains a `rrf_merge()` utility used by the improved pipeline.
- Three-way eval script (`eval/run_ragas_three_way.py`) imports all three pipelines, runs against `eval/golden_qa_v2.json`, and prints a scored comparison table.
- After the first full run, analyze the lowest-scoring metric and apply targeted improvements from the Iteration Playbook (Task 9) until all metrics ≥ 0.75.

**Tech Stack:** Python 3.11, sqlite-vec, NetworkX, sentence-transformers ≥ 3.0, LangChain (existing), RAGAS 0.4.3, Ollama (qwen2.5:7b + nomic-embed-text)

**Current baseline (Run 4, 30Q, graph_rag current):**
- faithfulness: 0.5714
- answer_relevancy: 0.4410
- context_precision: 0.1803

**Target:** all three ≥ 0.75

---

## File Map

| File | Status | Purpose |
|------|--------|---------|
| `eval/golden_qa_v2.json` | Create | 30 code-navigation Q&A pairs (navigation/implementation/relationship) |
| `backend/app/retrieval/graph_rag.py` | Modify | Add `rrf_merge()` function |
| `backend/app/retrieval/query_expansion.py` | Create | `hyde_expand(query)` — async HyDE via LLM |
| `backend/app/retrieval/reranker.py` | Create | `cross_encode_rerank()` — lazy-loaded cross-encoder |
| `backend/app/retrieval/improved_rag.py` | Create | `improved_graph_rag_retrieve()` — orchestrates all improvements |
| `backend/tests/test_rrf.py` | Create | Unit tests for `rrf_merge()` |
| `backend/tests/test_query_expansion.py` | Create | Tests for `hyde_expand()` with mock LLM |
| `backend/tests/test_reranker.py` | Create | Tests for cross-encoder with mock model |
| `backend/tests/test_improved_rag.py` | Create | Integration tests for improved pipeline |
| `backend/requirements.txt` | Modify | Add `sentence-transformers>=3.0.0` |
| `eval/run_ragas_three_way.py` | Create | Three-way evaluation script |

---

## Task 1: Create `eval/golden_qa_v2.json`

**Files:**
- Create: `eval/golden_qa_v2.json`

The 30 questions below are code-grounded, covering navigation (where is X?), implementation (how does this code work?), and cross-file relationships. Ground truths reference specific file paths and code constructs rather than documentation prose. This aligns the evaluation with what a code intelligence assistant actually does.

- [ ] **Step 1: Write golden_qa_v2.json**

Create `eval/golden_qa_v2.json` with this exact content:

```json
[
  {
    "id": "Q01",
    "topic": "navigation",
    "question": "In which file and class is the `Path()` function defined in the FastAPI source code?",
    "ground_truth": "The `Path` class is defined in `fastapi/params.py` as a subclass of `Param`. Its `__init__` method begins with `assert default is ..., 'Path parameters cannot have a default value'`, enforcing that path parameters are always required. It accepts validation kwargs including `gt`, `ge`, `lt`, `le`, `min_length`, `max_length`, and `pattern` that are forwarded to Pydantic's `FieldInfo`.",
    "notes": "Navigation — retrieves params.py Path class"
  },
  {
    "id": "Q02",
    "topic": "navigation",
    "question": "What class does `FastAPI` inherit from, and in which file is this inheritance declared?",
    "ground_truth": "In `fastapi/applications.py`, `class FastAPI(Starlette)` inherits from `starlette.applications.Starlette`. This gives FastAPI all of Starlette's ASGI application wiring, middleware stack, exception handler registration, and lifecycle event hooks on top of which FastAPI adds API routing, OpenAPI generation, and response model validation.",
    "notes": "Navigation — retrieves applications.py"
  },
  {
    "id": "Q03",
    "topic": "navigation",
    "question": "Where is the `Depends` callable defined in the FastAPI source, and what object does it return?",
    "ground_truth": "`Depends` is defined in `fastapi/params.py`. It is a function that creates and returns a `Depends` dataclass instance holding two fields: `dependency` (the callable to resolve) and `use_cache` (bool, default True). FastAPI's dependency injection machinery recognises this sentinel during route signature inspection to know it should call the callable and inject its result.",
    "notes": "Navigation — retrieves params.py Depends"
  },
  {
    "id": "Q04",
    "topic": "navigation",
    "question": "In which file is `OAuth2PasswordBearer` defined in FastAPI and what does its `__call__` method do?",
    "ground_truth": "`OAuth2PasswordBearer` is defined in `fastapi/security/oauth2.py`, inheriting from `OAuth2`. Its `__call__` method reads the `Authorization` header, verifies it starts with `'Bearer '`, and returns the token string. If the header is absent or malformed and `auto_error=True`, it raises `HTTPException(status_code=401, headers={'WWW-Authenticate': 'Bearer'})`.",
    "notes": "Navigation + implementation — security/oauth2.py"
  },
  {
    "id": "Q05",
    "topic": "navigation",
    "question": "Where is `APIKeyHeader` defined in the FastAPI source tree, and what method extracts the key?",
    "ground_truth": "`APIKeyHeader` is defined in `fastapi/security/api_key.py`. Its `__call__` method calls `request.headers.get(self.model.name)` where `self.model.name` is the header name passed at construction (e.g. `'X-API-Key'`). If the value is `None` and `auto_error=True`, it raises `HTTPException(status_code=403)`.",
    "notes": "Navigation — security/api_key.py"
  },
  {
    "id": "Q06",
    "topic": "navigation",
    "question": "Where is the `HTTPBasic` security class defined in FastAPI and what does it return on a successful request?",
    "ground_truth": "`HTTPBasic` is defined in `fastapi/security/http.py`. Its `__call__` method parses the `Authorization: Basic <base64>` header and returns an `HTTPBasicCredentials` instance with `username` and `password` string fields. If the header is absent or not in Basic format and `auto_error=True`, it raises HTTP 401 with `WWW-Authenticate: Basic`.",
    "notes": "Navigation — security/http.py"
  },
  {
    "id": "Q07",
    "topic": "navigation",
    "question": "Where is the `Security` function defined relative to `Depends`, and how does it differ?",
    "ground_truth": "Both `Security` and `Depends` are defined in `fastapi/params.py`. `Security` additionally accepts a `scopes` parameter (list of OAuth2 scope strings). This lets FastAPI populate `SecurityScopes.scopes` during dependency resolution and surface the required scopes in the OpenAPI security schema — something `Depends` does not do.",
    "notes": "Navigation + comparison — params.py"
  },
  {
    "id": "Q08",
    "topic": "navigation",
    "question": "What is the class hierarchy of `Query`, `Path`, `Header`, and `Cookie` in `params.py`?",
    "ground_truth": "In `fastapi/params.py`, `Query`, `Path`, `Header`, and `Cookie` all inherit from `Param`. `Param` inherits from Pydantic's `FieldInfo`. Each subclass sets a class-level `in_` attribute to the corresponding `ParamTypes` enum member (`query`, `path`, `header`, `cookie`), which FastAPI uses to determine which part of the HTTP request to read the value from.",
    "notes": "Structural — full Param hierarchy in params.py"
  },
  {
    "id": "Q09",
    "topic": "navigation",
    "question": "In which file is `CORSMiddleware` implemented that FastAPI uses?",
    "ground_truth": "`CORSMiddleware` is implemented in `starlette/middleware/cors.py`. FastAPI does not reimplement it — applications import it as `from starlette.middleware.cors import CORSMiddleware` and register it via `app.add_middleware(CORSMiddleware, allow_origins=[...])`. FastAPI inherits the `add_middleware()` method from Starlette.",
    "notes": "Navigation — starlette middleware cors"
  },
  {
    "id": "Q10",
    "topic": "navigation",
    "question": "Where is `BaseHTTPMiddleware` defined and what method must a subclass override?",
    "ground_truth": "`BaseHTTPMiddleware` is defined in `starlette/middleware/base.py`. A subclass must override the `dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response` coroutine. Code before `await call_next(request)` processes the incoming request; code after processes the outgoing response. This is the Starlette class FastAPI recommends for custom middleware.",
    "notes": "Navigation + implementation — starlette middleware base"
  },
  {
    "id": "Q11",
    "topic": "implementation",
    "question": "How does `Path.__init__` in `params.py` prevent path parameters from having a default value?",
    "ground_truth": "In `fastapi/params.py`, `Path.__init__` starts with `assert default is ..., 'Path parameters cannot have a default value'`. The `...` (Ellipsis) is Python's sentinel for a required Pydantic field. This assertion runs at route-definition time when `@app.get()` executes, not per-request — so misconfigured routes fail immediately at application startup.",
    "notes": "Implementation detail — params.py Path class"
  },
  {
    "id": "Q12",
    "topic": "implementation",
    "question": "What validation constraints does `Query.__init__` accept and how does it forward them to Pydantic?",
    "ground_truth": "In `fastapi/params.py`, `Query.__init__` accepts `gt`, `ge`, `lt`, `le` (numeric bounds), `min_length`, `max_length`, `pattern` (string constraints), `strict`, `multiple_of`, `allow_inf_nan`, `max_digits`, `decimal_places`, and `alias`/`validation_alias`/`serialization_alias`. All are forwarded via `super().__init__(...)` to `Param`, which calls Pydantic's `FieldInfo.__init__`. Pydantic evaluates these constraints when FastAPI calls `model_validate` on the parsed request data.",
    "notes": "Implementation — Query class constraints in params.py"
  },
  {
    "id": "Q13",
    "topic": "implementation",
    "question": "What does the `alias` parameter in `Query()` do at the HTTP request level?",
    "ground_truth": "In `fastapi/params.py`, `alias` lets you map a differently-named URL query key to the Python function parameter. For example, `q: str = Query(alias='item-query')` makes FastAPI read `?item-query=foo` from the URL but expose it as `q` in the handler. The `alias_priority` field controls whether the alias takes precedence over `validation_alias`. This is passed to Pydantic's `FieldInfo.alias` via `super().__init__()`.",
    "notes": "Implementation — alias parameter in Query"
  },
  {
    "id": "Q14",
    "topic": "implementation",
    "question": "How does `FastAPI.middleware('http')` register a function-based middleware?",
    "ground_truth": "In `fastapi/applications.py`, `FastAPI.middleware(middleware_type)` returns a decorator. When applied to a coroutine `async def my_mw(request, call_next)`, it calls `self.add_middleware(BaseHTTPMiddleware, dispatch=func)`. This wraps the function in a `BaseHTTPMiddleware` instance and prepends it to Starlette's ASGI middleware stack, identical in effect to the class-based `app.add_middleware()` form.",
    "notes": "Implementation — applications.py middleware() method"
  },
  {
    "id": "Q15",
    "topic": "implementation",
    "question": "What assertion or validation does the `test_invalid_dict` test in `test_invalid_sequence_param.py` verify about query parameter types?",
    "ground_truth": "In `tests/test_invalid_sequence_param.py`, `test_invalid_dict` uses `pytest.raises(AssertionError, match=\"Query parameter 'q' must be one of the supported types\")` to verify that FastAPI raises at route-definition time — not per-request — when a `dict[str, Item]` type is used as a `Query` parameter. FastAPI validates parameter types when the `@app.get()` decorator executes.",
    "notes": "Test-implementation — test_invalid_sequence_param.py"
  },
  {
    "id": "Q16",
    "topic": "implementation",
    "question": "What does the `test_multiple_path` function in `test_annotated.py` test?",
    "ground_truth": "`test_multiple_path` in `tests/test_annotated.py` creates a FastAPI app with two `@app.get` decorators on the same async handler — one for `/test1` and one for `/test2`. The handler uses `Annotated[str, Query()]` with a default. The test verifies both paths return 200 with the default value and that passing an explicit query value overrides the default on both paths.",
    "notes": "Test-navigation — test_annotated.py"
  },
  {
    "id": "Q17",
    "topic": "implementation",
    "question": "How does `get_path_param_min_length` in `tests/main.py` declare a path parameter with minimum length?",
    "ground_truth": "In `tests/main.py`, the function is declared as `def get_path_param_min_length(item_id: str = Path(min_length=3))`. `Path(min_length=3)` creates a `Path` instance with the `min_length` constraint forwarded to Pydantic. FastAPI enforces this at request parse time — a path segment shorter than 3 characters returns HTTP 422.",
    "notes": "Implementation — tests/main.py Path constraint"
  },
  {
    "id": "Q18",
    "topic": "implementation",
    "question": "What does `get_path_param_gt_int` in `tests/main.py` demonstrate about numeric path parameter constraints?",
    "ground_truth": "In `tests/main.py`, `def get_path_param_gt_int(item_id: int = Path(gt=3))` uses the `gt` (greater-than) constraint on a typed integer path parameter. The `int` type annotation causes FastAPI to coerce and validate the path segment as an integer, and `Path(gt=3)` adds the additional constraint that it must be greater than 3. Both are enforced by Pydantic on each request.",
    "notes": "Implementation — tests/main.py numeric constraint"
  },
  {
    "id": "Q19",
    "topic": "implementation",
    "question": "How does `test_optional_validation_alias_schema` in `test_request_params/test_query/test_optional_str.py` verify OpenAPI schema generation?",
    "ground_truth": "In `tests/test_request_params/test_query/test_optional_str.py`, the test calls `app.openapi()['paths'][path]['get']['parameters']` and asserts it matches a snapshot containing `'required': False`, `'schema': {'anyOf': [{'type': 'string'}, {'type': 'null'}]}`, and the aliased parameter name in the `'name'` field. This verifies FastAPI correctly reflects optional parameters with validation aliases in the generated OpenAPI schema.",
    "notes": "Implementation — test_request_params optional alias schema"
  },
  {
    "id": "Q20",
    "topic": "implementation",
    "question": "What does `test_redirect_slashes_enabled` in `test_router_redirect_slashes.py` verify about trailing slash handling?",
    "ground_truth": "In `tests/test_router_redirect_slashes.py`, the test registers `/hello/` on an `APIRouter` and checks that a request to `/hello/` (with slash) returns 200, while `/hello` (without slash) returns 307 Temporary Redirect. This verifies Starlette's redirect-slashes behaviour which FastAPI inherits — trailing slash normalisation via HTTP redirect rather than a 404.",
    "notes": "Implementation — router redirect slash behavior"
  },
  {
    "id": "Q21",
    "topic": "relationship",
    "question": "Trace how `@app.get('/items')` ultimately stores a route entry — which objects are created across which files?",
    "ground_truth": "`@app.get('/items')` calls `FastAPI.get()` in `fastapi/applications.py`, which delegates to `self.router.add_api_route('/items', endpoint, methods=['GET'], ...)`. `self.router` is an `APIRouter` instance (in `fastapi/routing.py`). `APIRouter.add_api_route` creates an `APIRoute` object storing the endpoint callable, path pattern, HTTP methods, and response model, then appends it to `self.routes`.",
    "notes": "Multi-hop — applications.py → routing.py APIRoute"
  },
  {
    "id": "Q22",
    "topic": "relationship",
    "question": "How does `app.include_router(router)` work internally — what is the complete call chain?",
    "ground_truth": "`app.include_router(router, prefix, tags, ...)` in `fastapi/applications.py` immediately delegates to `self.router.include_router(router, prefix, tags, ...)`. `self.router` is an `APIRouter`. `APIRouter.include_router` (in `fastapi/routing.py`) iterates over the nested router's routes, prepends the prefix to each path, and re-registers them via `self.add_api_route()`. Tags and dependencies are merged.",
    "notes": "Multi-hop — applications.py → routing.py include_router"
  },
  {
    "id": "Q23",
    "topic": "relationship",
    "question": "What happens in the ASGI middleware stack when two middlewares are added with `app.add_middleware(A)` then `app.add_middleware(B)`?",
    "ground_truth": "Starlette builds the ASGI stack by wrapping each new middleware around the existing app. `add_middleware` prepends to the stack, so the last-added middleware runs first. With `add_middleware(A)` then `add_middleware(B)`: incoming requests hit B first, then A, then the route handler. Responses travel in reverse order: handler → A → B. This LIFO execution is opposite to the order of registration calls.",
    "notes": "Multi-hop — Starlette middleware LIFO order"
  },
  {
    "id": "Q24",
    "topic": "relationship",
    "question": "How does FastAPI resolve sub-dependencies when a `Depends()` callable itself declares `Depends()` parameters?",
    "ground_truth": "FastAPI builds a dependency graph during route analysis (in `fastapi/dependencies/utils.py`). It recursively inspects each dependency callable's parameters for `Depends()` instances and resolves them depth-first. Results are cached per-request in a `dependency_cache` dict keyed by the callable when `use_cache=True`, so a dependency appearing multiple times in the tree is called only once per request.",
    "notes": "Multi-hop — dependencies/utils.py recursive resolution"
  },
  {
    "id": "Q25",
    "topic": "relationship",
    "question": "How does `app.dependency_overrides` work at the code level to replace dependencies in tests?",
    "ground_truth": "`app.dependency_overrides` is a plain dict on the `FastAPI` instance (propagated from its `APIRouter`). During dependency resolution in `fastapi/dependencies/utils.py`, before calling any dependency callable the resolver checks `request.app.dependency_overrides.get(dependency)`. If a replacement callable is found, it is used instead of the original — without modifying any application code.",
    "notes": "Implementation + relationship — dependency_overrides mechanism"
  },
  {
    "id": "Q26",
    "topic": "relationship",
    "question": "How does `response_model` declared on a path operation interact with the handler's return value?",
    "ground_truth": "After the path handler returns, FastAPI's `serialize_response` function (in `fastapi/routing.py`) calls `jsonable_encoder` on the return value, filtering to only fields declared in the `response_model`. It then runs `response_model.model_validate()` for Pydantic validation, strips fields not in the model, and serialises to JSON. A validation failure at this stage raises HTTP 500 (server error) rather than 422.",
    "notes": "Multi-hop — routing.py serialize_response"
  },
  {
    "id": "Q27",
    "topic": "relationship",
    "question": "How does FastAPI's `Form()` differ from `Query()` at the parsing level, and what extra package is required?",
    "ground_truth": "`Form` is defined in `fastapi/params.py` with `in_ = ParamTypes.body` (via `Body`). Unlike `Query` which reads from the URL query string, `Form` reads from `application/x-www-form-urlencoded` or `multipart/form-data` request bodies. The `python-multipart` package must be installed for form body parsing — FastAPI raises a `RuntimeError` at request time if it is missing. `Form` and JSON body parameters cannot coexist on the same endpoint.",
    "notes": "Comparison — Form vs Query, python-multipart dependency"
  },
  {
    "id": "Q28",
    "topic": "relationship",
    "question": "What is the class hierarchy of `OAuth2PasswordBearer` through to `SecurityBase` in the FastAPI security module?",
    "ground_truth": "`OAuth2PasswordBearer` (in `fastapi/security/oauth2.py`) inherits from `OAuth2`, also in that file. `OAuth2` inherits from `SecurityBase` (in `fastapi/security/base.py`). `OAuth2.__init__` stores an `OAuthFlows` Pydantic model for OpenAPI documentation. `OAuth2PasswordBearer` pre-configures `flows` as a password flow with the given `tokenUrl`.",
    "notes": "Structural — full OAuth2PasswordBearer hierarchy"
  },
  {
    "id": "Q29",
    "topic": "relationship",
    "question": "How does `UploadFile` reach the handler function — what is the path from HTTP multipart request to the `UploadFile` object?",
    "ground_truth": "When a route declares `file: UploadFile = File()`, FastAPI uses `python-multipart` to parse the `multipart/form-data` body. The uploaded bytes are stored in a `SpooledTemporaryFile` (in-memory below a threshold, spilled to disk above it). This is wrapped in Starlette's `UploadFile` class (from `starlette/datastructures.py`), which exposes async `read()`, `seek()`, `close()` methods plus `filename` and `content_type` attributes.",
    "notes": "Multi-hop — Form parsing → Starlette UploadFile"
  },
  {
    "id": "Q30",
    "topic": "relationship",
    "question": "How does using `Security()` instead of `Depends()` affect OAuth2 scope handling and the OpenAPI schema?",
    "ground_truth": "`Security` is defined in `fastapi/params.py` alongside `Depends` and accepts an additional `scopes` parameter. During dependency resolution FastAPI populates `SecurityScopes.scopes` with the union of scopes from all `Security()` declarations in the route's dependency tree. Inside the dependency you read `security_scopes.scopes` to verify the token grants the required scopes. FastAPI also emits the required scopes in the OpenAPI `security` field on the route.",
    "notes": "Implementation + relationship — Security scopes vs Depends"
  }
]
```

- [ ] **Step 2: Commit**

```bash
cd /Users/mohammedhafiz/Desktop/Personal/nexus
git add eval/golden_qa_v2.json
git commit -m "eval: add golden_qa_v2 — 30 code-navigation Q&As replacing doc-prose baseline"
```

---

## Task 2: Add `rrf_merge()` to `graph_rag.py`

**Files:**
- Modify: `backend/app/retrieval/graph_rag.py`
- Create: `backend/tests/test_rrf.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_rrf.py`:

```python
import pytest
from app.retrieval.graph_rag import rrf_merge


def test_single_list_scores_match_rrf_formula():
    results = [("nodeA", 0.9), ("nodeB", 0.7), ("nodeC", 0.5)]
    scores = rrf_merge([results])
    assert abs(scores["nodeA"] - 1 / 61) < 1e-9
    assert abs(scores["nodeB"] - 1 / 62) < 1e-9
    assert abs(scores["nodeC"] - 1 / 63) < 1e-9


def test_two_lists_same_node_sums_contributions():
    list1 = [("nodeA", 0.9), ("nodeB", 0.5)]
    list2 = [("nodeA", 0.8), ("nodeC", 0.3)]
    scores = rrf_merge([list1, list2])
    assert abs(scores["nodeA"] - (1 / 61 + 1 / 61)) < 1e-9
    assert abs(scores["nodeB"] - 1 / 62) < 1e-9
    assert abs(scores["nodeC"] - 1 / 62) < 1e-9


def test_node_shared_across_lists_beats_single_list_node():
    list1 = [("shared", 0.5), ("solo", 0.9)]
    list2 = [("shared", 0.5)]
    scores = rrf_merge([list1, list2])
    assert scores["shared"] > scores["solo"]


def test_empty_input_returns_empty():
    assert rrf_merge([]) == {}
    assert rrf_merge([[]]) == {}


def test_custom_k_affects_scores():
    results = [("nodeA", 1.0)]
    assert abs(rrf_merge([results], k=60)["nodeA"] - 1 / 61) < 1e-9
    assert abs(rrf_merge([results], k=10)["nodeA"] - 1 / 11) < 1e-9


def test_three_lists_cumulative():
    l1 = [("X", 1.0)]
    l2 = [("X", 0.9)]
    l3 = [("X", 0.8)]
    scores = rrf_merge([l1, l2, l3])
    expected = 3 * (1 / 61)
    assert abs(scores["X"] - expected) < 1e-9
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /Users/mohammedhafiz/Desktop/Personal/nexus/backend
python -m pytest tests/test_rrf.py -v 2>&1 | head -15
```

Expected: `ImportError: cannot import name 'rrf_merge'`

- [ ] **Step 3: Add `rrf_merge()` to graph_rag.py**

Open `backend/app/retrieval/graph_rag.py`. Insert the following function immediately before `def fts_search(` (after the `_FTS_STOPWORDS` block, around line 240):

```python
def rrf_merge(
    ranked_lists: list[list[tuple[str, float]]],
    k: int = 60,
) -> dict[str, float]:
    """Reciprocal Rank Fusion across multiple ranked retrieval result lists.

    RRF score = Σ  1 / (k + rank_i + 1)  for each list where the node appears.
    k=60 is the empirically robust constant that dampens very-high-rank advantages.

    Unlike max()-based merging, RRF is rank-based: immune to score scale differences
    between cosine similarity [0,1] and BM25 scores. A node that ranks high in
    multiple lists scores higher than one that tops only one list.

    Args:
        ranked_lists: Zero or more result lists, each sorted descending by score.
                      Empty lists are silently skipped.
        k:            Damping constant (default 60).

    Returns:
        Dict mapping node_id -> RRF score (unbounded; higher is better).
    """
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, (node_id, _) in enumerate(ranked):
            scores[node_id] = scores.get(node_id, 0.0) + 1.0 / (k + rank + 1)
    return scores
```

- [ ] **Step 4: Run tests to confirm pass**

```bash
cd /Users/mohammedhafiz/Desktop/Personal/nexus/backend
python -m pytest tests/test_rrf.py -v
```

Expected: 6 PASSED

- [ ] **Step 5: Commit**

```bash
cd /Users/mohammedhafiz/Desktop/Personal/nexus
git add backend/app/retrieval/graph_rag.py backend/tests/test_rrf.py
git commit -m "feat(retrieval): add rrf_merge() — rank-based hybrid seed fusion"
```

---

## Task 3: Add `sentence-transformers` and create `reranker.py`

**Files:**
- Modify: `backend/requirements.txt`
- Create: `backend/app/retrieval/reranker.py`
- Create: `backend/tests/test_reranker.py`

- [ ] **Step 1: Add dependency to requirements.txt**

Open `backend/requirements.txt` and add on its own line (before the final blank line):

```
sentence-transformers>=3.0.0
```

- [ ] **Step 2: Install**

```bash
cd /Users/mohammedhafiz/Desktop/Personal/nexus
source venv/bin/activate
pip install "sentence-transformers>=3.0.0"
```

Expected: `Successfully installed sentence-transformers-...` (or already satisfied)

- [ ] **Step 3: Write failing tests**

Create `backend/tests/test_reranker.py`:

```python
import pytest
import numpy as np
from unittest.mock import MagicMock, patch
from app.models.schemas import CodeNode


def _make_node(name: str, file_path: str = "/repo/a.py") -> CodeNode:
    return CodeNode(
        node_id=f"{file_path}::{name}", name=name, type="function",
        file_path=file_path, line_start=1, line_end=10,
        signature=f"def {name}():", docstring=f"Does {name}.",
        body_preview="pass", complexity=1, embedding_text=f"def {name}():",
    )


@pytest.fixture(autouse=True)
def patch_cross_encoder():
    """Prevent real model download during tests."""
    with patch("app.retrieval.reranker.CrossEncoder") as MockCE:
        instance = MagicMock()
        MockCE.return_value = instance
        yield instance


def test_returns_top_n(patch_cross_encoder):
    from app.retrieval.reranker import cross_encode_rerank

    nodes = [_make_node(f"f{i}") for i in range(5)]
    scored = [(float(i) * 0.1, n) for i, n in enumerate(nodes)]
    patch_cross_encoder.predict.return_value = np.array([0.9, 0.1, 0.8, 0.2, 0.7])

    result = cross_encode_rerank("query", scored, top_n=3)
    assert len(result) == 3


def test_orders_by_ce_score(patch_cross_encoder):
    from app.retrieval.reranker import cross_encode_rerank

    nodes = [_make_node("high"), _make_node("low"), _make_node("mid")]
    scored = [(0.5, n) for n in nodes]
    patch_cross_encoder.predict.return_value = np.array([0.9, 0.1, 0.5])

    result = cross_encode_rerank("query", scored, top_n=3)
    assert [n.name for _, n in result] == ["high", "mid", "low"]


def test_pair_format_contains_query_and_code(patch_cross_encoder):
    from app.retrieval.reranker import cross_encode_rerank

    node = _make_node("my_func")
    scored = [(0.8, node)]
    patch_cross_encoder.predict.return_value = np.array([0.7])

    cross_encode_rerank("my special query", scored, top_n=1)

    pairs = patch_cross_encoder.predict.call_args[0][0]
    query_text, context_text = pairs[0]
    assert query_text == "my special query"
    assert "my_func" in context_text


def test_empty_scored_returns_empty(patch_cross_encoder):
    from app.retrieval.reranker import cross_encode_rerank

    result = cross_encode_rerank("query", [], top_n=5)
    assert result == []
    patch_cross_encoder.predict.assert_not_called()
```

- [ ] **Step 4: Run to confirm failure**

```bash
cd /Users/mohammedhafiz/Desktop/Personal/nexus/backend
python -m pytest tests/test_reranker.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'app.retrieval.reranker'`

- [ ] **Step 5: Create `reranker.py`**

Create `backend/app/retrieval/reranker.py`:

```python
"""Cross-encoder reranker for the improved RAG pipeline.

Uses cross-encoder/ms-marco-MiniLM-L-6-v2 (66 MB) — a model that jointly attends
to (query, document) pairs. Cross-encoders are significantly more accurate than
bi-encoder cosine similarity for relevance discrimination because they see both
inputs simultaneously rather than encoding them separately.

The model is lazy-loaded on first call and cached module-level.
It runs on CPU in ~100ms for 15 candidates — acceptable for a dev tool.
"""

from __future__ import annotations

import logging

import numpy as np

from app.models.schemas import CodeNode

logger = logging.getLogger(__name__)

_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_reranker = None


def _get_reranker():
    """Lazy-load the CrossEncoder model; cached after first call."""
    global _reranker
    if _reranker is None:
        from sentence_transformers import CrossEncoder
        logger.info("Loading cross-encoder model %s (first call)", _MODEL_NAME)
        _reranker = CrossEncoder(_MODEL_NAME)
    return _reranker


def cross_encode_rerank(
    query: str,
    scored: list[tuple[float, CodeNode]],
    top_n: int,
) -> list[tuple[float, CodeNode]]:
    """Rerank a scored candidate pool using a cross-encoder model.

    The cross-encoder jointly reads (query, context_text) for each node and
    produces a relevance score more accurate than bi-encoder cosine similarity.
    Applied after rerank_and_assemble over the 2×max_nodes candidate pool.

    Args:
        query:   Original user query string.
        scored:  Pre-scored (score, CodeNode) list from rerank_and_assemble.
        top_n:   Number of (ce_score, CodeNode) pairs to return.

    Returns:
        Top top_n (cross_encoder_score, CodeNode) tuples sorted descending.
        Empty list if scored is empty (model not called).
    """
    if not scored:
        return []

    reranker = _get_reranker()
    pairs = [
        (
            query,
            f"{n.file_path}:{n.line_start}-{n.line_end}\n"
            f"{n.signature or ''}\n{n.docstring or ''}\n{n.body_preview or ''}",
        )
        for _, n in scored
    ]

    ce_scores: np.ndarray = reranker.predict(pairs)
    reranked = sorted(
        zip(ce_scores.tolist(), [n for _, n in scored]),
        key=lambda x: x[0],
        reverse=True,
    )
    return reranked[:top_n]
```

- [ ] **Step 6: Run tests to confirm pass**

```bash
cd /Users/mohammedhafiz/Desktop/Personal/nexus/backend
python -m pytest tests/test_reranker.py -v
```

Expected: 4 PASSED

- [ ] **Step 7: Commit**

```bash
cd /Users/mohammedhafiz/Desktop/Personal/nexus
git add backend/requirements.txt backend/app/retrieval/reranker.py backend/tests/test_reranker.py
git commit -m "feat(retrieval): add cross-encoder reranker (ms-marco-MiniLM-L-6-v2)"
```

---

## Task 4: Create `query_expansion.py` with HyDE

**Files:**
- Create: `backend/app/retrieval/query_expansion.py`
- Create: `backend/tests/test_query_expansion.py`

- [ ] **Step 1: Install pytest-asyncio if needed**

```bash
cd /Users/mohammedhafiz/Desktop/Personal/nexus
source venv/bin/activate
pip show pytest-asyncio >/dev/null 2>&1 || pip install pytest-asyncio
```

- [ ] **Step 2: Write failing tests**

Create `backend/tests/test_query_expansion.py`:

```python
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
```

- [ ] **Step 3: Run to confirm failure**

```bash
cd /Users/mohammedhafiz/Desktop/Personal/nexus/backend
python -m pytest tests/test_query_expansion.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'app.retrieval.query_expansion'`

- [ ] **Step 4: Create `query_expansion.py`**

Create `backend/app/retrieval/query_expansion.py`:

```python
"""HyDE (Hypothetical Document Embeddings) query expansion.

HyDE bridges the vocabulary gap between natural-language questions and code:
  User query : "How does FastAPI validate path parameters?"
  Embedding  : question tokens are distant from `class Path(Param): assert default is ...`
  HyDE output: "def register_path(item_id: int = Path(gt=0)): ..."
  Embedding  : hypothetical code is near the actual Path implementation

We ask the LLM to generate a short hypothetical code snippet, embed it alongside
the original query, and RRF-merge the result sets. The snippet lives in the same
vector space as real indexed code, dramatically improving recall for questions
where the user vocabulary is far from the code vocabulary.
"""

from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage

from app.core.model_factory import get_llm

logger = logging.getLogger(__name__)

_HYDE_PROMPT = (
    'Write a short Python code snippet (5-15 lines) showing the key implementation '
    'or usage pattern that answers this question about a codebase:\n\n'
    '"{query}"\n\n'
    'Return only Python code. No explanations, no markdown fences.'
)


async def hyde_expand(query: str) -> str:
    """Generate a hypothetical code snippet to improve vector retrieval recall.

    Calls the configured LLM to produce a short code snippet representing an
    idealised answer. The snippet is then embedded and its semantic results are
    merged with the original query results via RRF. Falls back gracefully to
    empty string on any LLM error — the caller continues with original-query
    retrieval only.

    Args:
        query: Natural language question from the user.

    Returns:
        A Python code snippet string, or "" on LLM failure.
    """
    llm = get_llm()
    prompt = _HYDE_PROMPT.format(query=query)
    try:
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        return response.content.strip()
    except Exception as exc:
        logger.warning("HyDE expansion failed (falling back to original query): %s", exc)
        return ""
```

- [ ] **Step 5: Run tests to confirm pass**

```bash
cd /Users/mohammedhafiz/Desktop/Personal/nexus/backend
python -m pytest tests/test_query_expansion.py -v
```

Expected: 4 PASSED

- [ ] **Step 6: Commit**

```bash
cd /Users/mohammedhafiz/Desktop/Personal/nexus
git add backend/app/retrieval/query_expansion.py backend/tests/test_query_expansion.py
git commit -m "feat(retrieval): add HyDE query expansion — bridges NL-to-code vocabulary gap"
```

---

## Task 5: Create `improved_rag.py`

**Files:**
- Create: `backend/app/retrieval/improved_rag.py`
- Create: `backend/tests/test_improved_rag.py`

The improved pipeline: HyDE → dual semantic search → FTS → RRF merge + normalise → test-file penalty → BFS threshold expansion → dual-score rerank → cross-encoder final selection.

- [ ] **Step 1: Write failing integration tests**

Create `backend/tests/test_improved_rag.py`:

```python
import pytest
import asyncio
import networkx as nx
import numpy as np
from unittest.mock import patch, MagicMock, AsyncMock
from app.models.schemas import CodeNode


@pytest.fixture
def two_node_graph():
    G = nx.DiGraph()
    for nid, name, fp, pr in [
        ("a.py::func_a", "func_a", "/repo/a.py", 0.25),
        ("b.py::func_b", "func_b", "/repo/b.py", 0.30),
    ]:
        G.add_node(nid, node_id=nid, name=name, type="function",
                   file_path=fp, line_start=1, line_end=5,
                   signature=f"def {name}():", docstring="", body_preview="pass",
                   complexity=1, embedding_text=f"def {name}():",
                   pagerank=pr, in_degree=0, out_degree=0)
    G.add_edge("a.py::func_a", "b.py::func_b", type="CALLS")
    return G


@pytest.fixture
def mock_sem_search():
    with patch("app.retrieval.improved_rag.semantic_search") as m:
        m.return_value = [("a.py::func_a", 0.85), ("b.py::func_b", 0.60)]
        yield m


@pytest.fixture
def mock_fts():
    with patch("app.retrieval.improved_rag.fts_search") as m:
        m.return_value = [("a.py::func_a", 0.80)]
        yield m


@pytest.fixture
def mock_hyde():
    with patch("app.retrieval.improved_rag.hyde_expand", new_callable=AsyncMock) as m:
        m.return_value = "def func_a(): ..."
        yield m


@pytest.fixture
def mock_ce():
    with patch("app.retrieval.improved_rag.cross_encode_rerank") as m:
        m.side_effect = lambda q, scored, top_n: scored[:top_n]
        yield m


@pytest.mark.asyncio
async def test_returns_codenodes(two_node_graph, mock_sem_search, mock_fts, mock_hyde, mock_ce):
    from app.retrieval.improved_rag import improved_graph_rag_retrieve
    nodes, stats = await improved_graph_rag_retrieve(
        "how does func_a work", "/repo", two_node_graph, "/fake/db.sqlite", max_nodes=2
    )
    assert isinstance(nodes, list)
    assert all(isinstance(n, CodeNode) for n in nodes)


@pytest.mark.asyncio
async def test_stats_has_required_keys(two_node_graph, mock_sem_search, mock_fts, mock_hyde, mock_ce):
    from app.retrieval.improved_rag import improved_graph_rag_retrieve
    _, stats = await improved_graph_rag_retrieve(
        "test", "/repo", two_node_graph, "/fake/db.sqlite", max_nodes=2
    )
    for key in ("seed_count", "semantic_seeds", "fts_seeds", "hyde_used",
                "expanded_count", "returned_count", "hop_depth", "strong_bfs_seeds"):
        assert key in stats, f"Missing: {key}"


@pytest.mark.asyncio
async def test_hyde_disabled_does_not_call_expand(two_node_graph, mock_sem_search, mock_fts, mock_hyde, mock_ce):
    from app.retrieval.improved_rag import improved_graph_rag_retrieve
    _, stats = await improved_graph_rag_retrieve(
        "test", "/repo", two_node_graph, "/fake/db.sqlite", max_nodes=2, use_hyde=False
    )
    assert stats["hyde_used"] is False
    mock_hyde.assert_not_called()


@pytest.mark.asyncio
async def test_bfs_threshold_limits_expansion(two_node_graph, mock_fts, mock_hyde, mock_ce):
    from app.retrieval.improved_rag import improved_graph_rag_retrieve
    # Only func_a has score above threshold; func_b is weak
    with patch("app.retrieval.improved_rag.semantic_search") as m:
        m.return_value = [("a.py::func_a", 0.90), ("b.py::func_b", 0.10)]
        _, stats = await improved_graph_rag_retrieve(
            "test", "/repo", two_node_graph, "/fake/db.sqlite",
            max_nodes=2, bfs_score_threshold=0.45
        )
    # Only func_a is strong enough for BFS; func_b added directly
    assert stats["strong_bfs_seeds"] == 1


@pytest.mark.asyncio
async def test_cross_encoder_disabled_falls_back_to_mmr(two_node_graph, mock_sem_search, mock_fts, mock_hyde, mock_ce):
    from app.retrieval.improved_rag import improved_graph_rag_retrieve
    nodes, _ = await improved_graph_rag_retrieve(
        "test", "/repo", two_node_graph, "/fake/db.sqlite",
        max_nodes=2, use_cross_encoder=False
    )
    mock_ce.assert_not_called()
    assert isinstance(nodes, list)
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /Users/mohammedhafiz/Desktop/Personal/nexus/backend
python -m pytest tests/test_improved_rag.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'app.retrieval.improved_rag'`

- [ ] **Step 3: Create `improved_rag.py`**

Create `backend/app/retrieval/improved_rag.py`:

```python
"""Improved Graph RAG retrieval pipeline.

Extends the baseline graph_rag_retrieve with four improvements:

  1. HyDE query expansion  — generates a hypothetical code answer to bridge
     the NL-to-code vocabulary gap before semantic search.
  2. RRF seed fusion       — replaces max()-score merging with Reciprocal Rank
     Fusion across semantic, HyDE, and FTS result lists, then normalises to [0,1].
  3. BFS score threshold   — only BFS-expands seeds whose normalised RRF score
     meets or exceeds `bfs_score_threshold`, cutting noise from weak seeds.
  4. Cross-encoder rerank  — replaces MMR with a cross-encoder that jointly reads
     (query, context) to produce accurate relevance scores for final selection.
"""

from __future__ import annotations

import logging

import networkx as nx

from app.models.schemas import CodeNode
from app.retrieval.graph_rag import (
    expand_via_graph,
    fts_search,
    mmr_diversify,
    rerank_and_assemble,
    rrf_merge,
    semantic_search,
)
from app.retrieval.query_expansion import hyde_expand
from app.retrieval.reranker import cross_encode_rerank

logger = logging.getLogger(__name__)

_TEST_PENALTY = 0.5


async def improved_graph_rag_retrieve(
    query: str,
    repo_path: str,
    G: nx.DiGraph,
    db_path: str,
    max_nodes: int = 10,
    hop_depth: int = 1,
    use_hyde: bool = True,
    use_cross_encoder: bool = True,
    bfs_score_threshold: float = 0.45,
) -> tuple[list[CodeNode], dict]:
    """Improved Graph RAG: HyDE + RRF + BFS-threshold + cross-encoder rerank.

    Args:
        query:               Original user query string.
        repo_path:           Repository root path for scoped DB queries.
        G:                   Code call/import DiGraph with full node attributes.
        db_path:             Path to the SQLite database file.
        max_nodes:           Final number of CodeNode objects to return.
        hop_depth:           BFS depth for graph expansion from strong seeds.
        use_hyde:            Generate a hypothetical code snippet pre-retrieval.
                             Falls back gracefully if the LLM call fails.
        use_cross_encoder:   Apply cross-encoder as the final selection step.
                             Falls back to MMR if False.
        bfs_score_threshold: Min normalised RRF score for BFS expansion. Seeds
                             below this threshold are added to the candidate pool
                             directly without expanding their graph neighbours.

    Returns:
        Tuple of (list[CodeNode], stats_dict).
    """
    # ── 1. HyDE expansion ────────────────────────────────────────────────────
    hyde_text = ""
    if use_hyde:
        hyde_text = await hyde_expand(query)

    # ── 2. Semantic search (original + HyDE) ─────────────────────────────────
    seed_results = semantic_search(query, repo_path, top_k=max_nodes, db_path=db_path)
    semantic_seed_ids = {node_id for node_id, _ in seed_results}

    hyde_results: list[tuple[str, float]] = []
    if hyde_text:
        hyde_results = semantic_search(hyde_text, repo_path, top_k=max_nodes, db_path=db_path)

    # ── 3. FTS keyword search ─────────────────────────────────────────────────
    fts_results = fts_search(query, repo_path, top_k=5, db_path=db_path)

    # ── 4. RRF merge + normalise to [0, 1] ───────────────────────────────────
    lists_to_merge = [lst for lst in [seed_results, hyde_results, fts_results] if lst]
    rrf_scores = rrf_merge(lists_to_merge)
    max_rrf = max(rrf_scores.values()) if rrf_scores else 1.0
    seed_scores: dict[str, float] = {
        nid: s / max_rrf for nid, s in rrf_scores.items()
    }

    # ── 5. Test-file penalty ─────────────────────────────────────────────────
    penalised = 0
    for node_id in list(seed_scores):
        file_part = node_id.split("::")[0].lower()
        if "test" in file_part or "spec" in file_part:
            seed_scores[node_id] *= _TEST_PENALTY
            penalised += 1
    if penalised:
        logger.debug("test-file penalty applied to %d seeds", penalised)

    # ── 6. BFS expansion with score threshold ────────────────────────────────
    strong_seeds = [
        nid for nid in semantic_seed_ids
        if seed_scores.get(nid, 0.0) >= bfs_score_threshold
    ]
    expanded = expand_via_graph(strong_seeds, G, hop_depth)
    expanded.update(seed_scores.keys())  # add all seeds (weak + FTS-only) directly

    logger.info(
        "improved_rag: semantic=%d hyde=%d fts=%d strong_bfs=%d expanded=%d",
        len(semantic_seed_ids), len(hyde_results), len(fts_results),
        len(strong_seeds), len(expanded),
    )

    # ── 7. Dual-score rerank over 2× candidate pool ───────────────────────────
    scored = rerank_and_assemble(expanded, seed_scores, G, max_nodes * 2)

    # ── 8. Final selection ────────────────────────────────────────────────────
    if use_cross_encoder and scored:
        reranked = cross_encode_rerank(query, scored, top_n=max_nodes)
        nodes = [n for _, n in reranked]
    else:
        nodes = mmr_diversify(scored, max_nodes)

    stats = {
        "seed_count": len(seed_scores),
        "semantic_seeds": len(semantic_seed_ids),
        "fts_seeds": len(fts_results),
        "hyde_used": bool(hyde_text),
        "expanded_count": len(expanded),
        "returned_count": len(nodes),
        "hop_depth": hop_depth,
        "strong_bfs_seeds": len(strong_seeds),
    }
    return nodes, stats
```

- [ ] **Step 4: Run tests to confirm pass**

```bash
cd /Users/mohammedhafiz/Desktop/Personal/nexus/backend
python -m pytest tests/test_improved_rag.py -v
```

Expected: 5 PASSED

- [ ] **Step 5: Run full backend suite — no regressions**

```bash
cd /Users/mohammedhafiz/Desktop/Personal/nexus/backend
python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: all existing tests pass.

- [ ] **Step 6: Commit**

```bash
cd /Users/mohammedhafiz/Desktop/Personal/nexus
git add backend/app/retrieval/improved_rag.py backend/tests/test_improved_rag.py
git commit -m "feat(retrieval): add improved_graph_rag_retrieve — HyDE + RRF + BFS-threshold + cross-encoder"
```

---

## Task 6: Create `eval/run_ragas_three_way.py`

**Files:**
- Create: `eval/run_ragas_three_way.py`

Evaluates naive (semantic only), graph_rag (current baseline), and improved pipelines against `golden_qa_v2.json`. Generates answers for all three pipelines per question and scores them simultaneously with the same RAGAS judge.

- [ ] **Step 1: Create the eval script**

Create `eval/run_ragas_three_way.py`:

```python
"""Three-way RAGAS evaluation: naive | graph_rag | improved.

Evaluates against eval/golden_qa_v2.json (30 code-navigation questions).

Pipelines:
  naive    — semantic_search only, top-15, no FTS, no BFS, no reranking
  graph    — graph_rag_retrieve (FTS + BFS + MMR, current production baseline)
  improved — improved_graph_rag_retrieve (HyDE + RRF + BFS-threshold + cross-encoder)

Usage:
    # Quick sanity check — 5 questions
    python eval/run_ragas_three_way.py --limit 5

    # Full 30-question eval, 2 Ollama workers (~3-4 hours)
    OLLAMA_NUM_PARALLEL=2 python eval/run_ragas_three_way.py --limit 30 --workers 2

    # Mistral judge (faster scoring, requires MISTRAL_API_KEY)
    python eval/run_ragas_three_way.py --limit 30 --judge mistral
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.WARNING)
os.environ["LANGCHAIN_TRACING_V2"] = "false"

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root / "backend"))
_env = _root / ".env"
if _env.exists():
    for _line in _env.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            k, v = _line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from ragas import EvaluationDataset, evaluate, RunConfig
from ragas.dataset_schema import SingleTurnSample
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import ContextPrecision, Faithfulness, ResponseRelevancy

from app.ingestion.graph_store import load_graph
from app.models.schemas import CodeNode
from app.retrieval.graph_rag import semantic_search, graph_rag_retrieve
from app.retrieval.improved_rag import improved_graph_rag_retrieve
from app.agent.explorer import explore_stream

REPO_PATH = "/Users/mohammedhafiz/Desktop/Personal/fastapi"
DB_PATH = REPO_PATH + "/.nexus/graph.db"
GOLDEN_PATH = Path(__file__).parent / "golden_qa_v2.json"
MAX_NODES = 15


# ─── Retrieval helpers ────────────────────────────────────────────────────────

def naive_retrieve(
    query: str,
    G,
    max_nodes: int = MAX_NODES,
) -> tuple[list[CodeNode], dict]:
    """Semantic-only retrieval: cosine NN, no FTS, no BFS, no reranking.

    Hydrates CodeNode objects from the graph (same source as graph_rag_retrieve)
    so the context format is identical across all three pipelines.
    """
    results = semantic_search(query, REPO_PATH, top_k=max_nodes, db_path=DB_PATH)
    nodes: list[CodeNode] = []
    for node_id, _ in results:
        if node_id not in G:
            continue
        attrs = G.nodes[node_id]
        try:
            node = CodeNode(**{k: v for k, v in attrs.items() if k in CodeNode.model_fields})
            nodes.append(node)
        except Exception:
            pass
    return nodes, {"returned_count": len(nodes), "pipeline": "naive"}


def build_contexts(nodes: list[CodeNode]) -> list[str]:
    return [
        f"{n.file_path}:{n.line_start}-{n.line_end}\n"
        f"{n.signature or ''}\n{n.docstring or ''}\n{n.body_preview or ''}"
        for n in nodes
    ]


# ─── Answer generation ────────────────────────────────────────────────────────

async def get_answer(nodes: list[CodeNode], question: str) -> str:
    for attempt in range(6):
        try:
            return "".join([t async for t in explore_stream(nodes, question)])
        except Exception as e:
            if "429" in str(e) or "rate" in str(e).lower() or "capacity" in str(e).lower():
                wait = 60 * (attempt + 1)
                print(f"    [rate limited, retry {attempt+1}/6, wait {wait}s]")
                await asyncio.sleep(wait)
            else:
                raise
    return ""


# ─── Per-question evaluation ─────────────────────────────────────────────────

async def run_question(
    sem: asyncio.Semaphore,
    i: int,
    total: int,
    entry: dict,
    G,
) -> tuple:
    """Retrieve + answer for all three pipelines on one question.

    Returns (naive_sample, graph_sample, improved_sample,
             naive_stat, graph_stat, improved_stat).
    """
    q, ref = entry["question"], entry["ground_truth"]
    qid = entry.get("id", f"Q{i:02d}")

    # Retrieval (fast, outside semaphore)
    for attempt in range(5):
        try:
            naive_nodes, naive_stat = naive_retrieve(q, G)
            graph_nodes, graph_stat = graph_rag_retrieve(
                q, REPO_PATH, G, DB_PATH, max_nodes=MAX_NODES, hop_depth=1
            )
            improved_nodes, improved_stat = await improved_graph_rag_retrieve(
                q, REPO_PATH, G, DB_PATH, max_nodes=MAX_NODES, hop_depth=1
            )
            break
        except Exception as e:
            if "429" in str(e) or "capacity" in str(e).lower():
                print(f"  [{qid}] retrieval rate limited, retry {attempt+1}/5")
                await asyncio.sleep(60)
            else:
                raise

    # Answer generation (gated by semaphore to avoid LLM overload)
    async with sem:
        print(f"[{i}/{total}] {qid}: {q[:65]}...")
        naive_ans, graph_ans, improved_ans = await asyncio.gather(
            get_answer(naive_nodes, q),
            get_answer(graph_nodes, q),
            get_answer(improved_nodes, q),
        )

    def _sample(nodes, ans):
        return SingleTurnSample(
            user_input=q, retrieved_contexts=build_contexts(nodes),
            response=ans, reference=ref,
        )

    naive_stat.update({"qid": qid})
    graph_stat.update({"qid": qid})
    improved_stat.update({"qid": qid})

    return (
        _sample(naive_nodes, naive_ans),
        _sample(graph_nodes, graph_ans),
        _sample(improved_nodes, improved_ans),
        naive_stat, graph_stat, improved_stat,
    )


# ─── Scoring ──────────────────────────────────────────────────────────────────

def score_pipeline(samples, metrics, run_config, name):
    print(f"\nScoring {name} ({len(samples)} samples)...")
    ds = EvaluationDataset(samples=samples)
    res = evaluate(dataset=ds, metrics=metrics, run_config=run_config,
                   show_progress=True, raise_exceptions=False)
    df = res.to_pandas()

    def _mean(key):
        col = next((c for c in df.columns if key in c.lower()), None)
        if col is None:
            return None
        s = df[col].dropna()
        return float(s.mean()) if not s.empty else None

    agg = {
        "faithfulness": _mean("faithfulness"),
        "answer_relevancy": _mean("answer_relevancy") or _mean("response_relevancy"),
        "context_precision": _mean("context_precision"),
    }
    return agg, df


# ─── Main ────────────────────────────────────────────────────────────────────

async def main(limit, judge, ollama_chat, ollama_embed, answer_concurrency, workers):
    print(f"\nNexus RAGAS — Three-Way Evaluation")
    print(f"  corpus : {REPO_PATH}")
    print(f"  golden : {GOLDEN_PATH.name}")

    print("Loading graph...")
    G = load_graph(REPO_PATH, DB_PATH)
    print(f"  {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    golden: list[dict] = json.loads(GOLDEN_PATH.read_text())
    if limit:
        golden = golden[:limit]
    print(f"  {len(golden)} questions\n")

    if judge == "ollama":
        from langchain_ollama import ChatOllama, OllamaEmbeddings
        base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        llm = LangchainLLMWrapper(ChatOllama(model=ollama_chat, temperature=0, base_url=base))
        emb = LangchainEmbeddingsWrapper(OllamaEmbeddings(model=ollama_embed, base_url=base))
        print(f"  judge  : ollama  chat={ollama_chat}  embed={ollama_embed}")
        run_cfg = RunConfig(timeout=180, max_retries=1, max_workers=workers)
    else:
        from langchain_mistralai import ChatMistralAI, MistralAIEmbeddings
        key = os.environ.get("MISTRAL_API_KEY") or os.environ.get("LLM_PROVIDER_API_KEY")
        if not key:
            raise RuntimeError("Set MISTRAL_API_KEY in .env")
        llm = LangchainLLMWrapper(ChatMistralAI(model="mistral-large-latest", temperature=0, api_key=key))
        emb = LangchainEmbeddingsWrapper(MistralAIEmbeddings(model="mistral-embed", api_key=key))
        print(f"  judge  : mistral (mistral-large-latest)")
        run_cfg = RunConfig(timeout=120, max_retries=3, max_workers=workers)

    metrics = [Faithfulness(llm=llm), ResponseRelevancy(llm=llm, embeddings=emb), ContextPrecision(llm=llm)]

    sem = asyncio.Semaphore(answer_concurrency)
    all_results = await asyncio.gather(*[
        run_question(sem, i, len(golden), entry, G)
        for i, entry in enumerate(golden, 1)
    ])

    naive_samples  = [r[0] for r in all_results]
    graph_samples  = [r[1] for r in all_results]
    imprv_samples  = [r[2] for r in all_results]
    naive_stats    = [r[3] for r in all_results]
    graph_stats    = [r[4] for r in all_results]
    imprv_stats    = [r[5] for r in all_results]

    naive_agg, naive_df = score_pipeline(naive_samples,  metrics, run_cfg, "naive")
    graph_agg, graph_df = score_pipeline(graph_samples,  metrics, run_cfg, "graph_rag")
    imprv_agg, imprv_df = score_pipeline(imprv_samples,  metrics, run_cfg, "improved")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = {
        "timestamp": timestamp,
        "repo_path": REPO_PATH,
        "golden_qa": "golden_qa_v2.json",
        "questions": len(golden),
        "naive": naive_agg,
        "graph_rag": graph_agg,
        "improved": imprv_agg,
        "retrieval_stats": {
            "naive": naive_stats, "graph": graph_stats, "improved": imprv_stats,
        },
        "per_question": {
            "naive": naive_df.to_dict(orient="records"),
            "graph": graph_df.to_dict(orient="records"),
            "improved": imprv_df.to_dict(orient="records"),
        },
    }
    out_path = Path(__file__).parent / "results" / f"ragas_three_way_{timestamp}.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))

    # ── Print comparison table ────────────────────────────────────────────────
    W = 90
    print("\n" + "=" * W)
    print("  RAGAS THREE-WAY COMPARISON  —  golden_qa_v2.json")
    print("=" * W)
    header = f"  {'Metric':<26} {'Naive':>10} {'Graph RAG':>11} {'Improved':>11} {'Δ N→I':>9} {'Δ G→I':>9}"
    print(header)
    print("-" * W)
    for m in ("faithfulness", "answer_relevancy", "context_precision"):
        n = naive_agg.get(m)
        g = graph_agg.get(m)
        v = imprv_agg.get(m)
        f = lambda x: f"{x:.4f}" if x is not None else "  N/A"
        pct = lambda a, b: f"{(b-a)/a*100:+.1f}%" if a and b else "  N/A"
        print(f"  {m:<26} {f(n):>10} {f(g):>11} {f(v):>11} {pct(n,v):>9} {pct(g,v):>9}")
    print("=" * W)
    print(f"\n  Results → {out_path.name}")
    print("=" * W)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=5)
    p.add_argument("--judge", choices=["mistral", "ollama"], default="ollama")
    p.add_argument("--ollama-chat-model", default="qwen2.5:7b")
    p.add_argument("--ollama-embed-model", default="nomic-embed-text")
    p.add_argument("--answer-concurrency", type=int, default=3)
    p.add_argument("--workers", type=int, default=1)
    args = p.parse_args()
    asyncio.run(main(
        args.limit, args.judge, args.ollama_chat_model, args.ollama_embed_model,
        args.answer_concurrency, args.workers,
    ))
```

- [ ] **Step 2: Verify imports work cleanly**

```bash
cd /Users/mohammedhafiz/Desktop/Personal/nexus
source venv/bin/activate
cd backend && python -c "
import sys; sys.path.insert(0, '.')
from app.retrieval.improved_rag import improved_graph_rag_retrieve
from app.retrieval.graph_rag import graph_rag_retrieve, semantic_search, rrf_merge
from app.retrieval.reranker import cross_encode_rerank
from app.retrieval.query_expansion import hyde_expand
print('All imports OK')
"
```

Expected: `All imports OK`

- [ ] **Step 3: Commit**

```bash
cd /Users/mohammedhafiz/Desktop/Personal/nexus
git add eval/run_ragas_three_way.py
git commit -m "eval: add three-way RAGAS script (naive | graph | improved) vs golden_qa_v2"
```

---

## Task 7: Smoke Test (5 Questions)

Verify the pipeline end-to-end before committing to the full 30-question run.

- [ ] **Step 1: Confirm prerequisites**

```bash
# Ollama running
brew services list | grep ollama
# Models available
ollama list | grep -E "qwen2.5:7b|nomic-embed-text"
# FastAPI DB indexed
ls -lh /Users/mohammedhafiz/Desktop/Personal/fastapi/.nexus/graph.db
```

If models are missing: `ollama pull qwen2.5:7b && ollama pull nomic-embed-text`
If DB missing: start Nexus backend and index the FastAPI repo.

- [ ] **Step 2: Run 5-question smoke test**

```bash
cd /Users/mohammedhafiz/Desktop/Personal/nexus
source venv_eval/bin/activate
python eval/run_ragas_three_way.py --limit 5 --judge ollama --workers 1
```

Expected: script completes, prints comparison table, no crash. Scores at 5 questions are noisy but the pipeline must not error.

- [ ] **Step 3: Confirm output file**

```bash
ls -lh eval/results/ragas_three_way_*.json | tail -1
```

Expected: new file with non-zero size.

---

## Task 8: Full 30-Question Evaluation

- [ ] **Step 1: Run full evaluation**

```bash
cd /Users/mohammedhafiz/Desktop/Personal/nexus
source venv_eval/bin/activate
OLLAMA_NUM_PARALLEL=2 python eval/run_ragas_three_way.py \
  --limit 30 --judge ollama --answer-concurrency 3 --workers 2
```

Expected runtime: 3-5 hours. The script auto-saves to `eval/results/ragas_three_way_<ts>.json`.

- [ ] **Step 2: Record the output table**

Copy the printed comparison table here and proceed to Task 9 to determine which metrics need iteration.

```
# PASTE OUTPUT TABLE HERE AFTER RUN COMPLETES
```

- [ ] **Step 3: Commit result**

```bash
cd /Users/mohammedhafiz/Desktop/Personal/nexus
git add eval/results/ragas_three_way_*.json
git commit -m "eval: three-way RAGAS baseline — naive vs graph vs improved on golden_qa_v2"
```

---

## Task 9: Iteration Loop — Improve Until All Metrics ≥ 0.75

**STOP condition:** all three metrics for the `improved` pipeline ≥ 0.75.

After each full or 10-question spot-check run, consult the playbook below, apply the highest-priority fix for the lowest-scoring metric, run a 10-question spot-check, then run the full 30 if the direction is positive.

### Iteration Playbook

Read the latest `ragas_three_way_*.json` and identify the weakest metric. Apply the corresponding fix.

---

#### If `answer_relevancy` < 0.75

**Root cause:** The LLM is answering with code-citations but the RAGAS judge doesn't recognise them as directly answering the question. Two sub-causes:

**A) Improve the system prompt to produce more direct answers:**

Open `backend/app/agent/prompts.py` and replace `SYSTEM_PROMPT`:

```python
SYSTEM_PROMPT = """You are an expert code assistant. You answer questions about a codebase using ONLY the code context provided.

Rules:
1. Answer the question directly in 1-3 sentences first, then cite the evidence.
2. Cite code by referencing the exact file path and line range, e.g. `auth/login.py:42-55`.
3. Never fabricate a citation. Only cite locations that appear verbatim in the context headers.
4. If the context does not contain enough information, say: "I'm not certain based on the retrieved context."
5. Do not invent function names, class names, or module paths not present in the context.
6. Keep answers concise. Lead with the answer, not the file path.
"""
```

The change: rule 1 now says "answer directly first, then cite." This shifts the answer structure closer to what RAGAS's ResponseRelevancy metric expects (it generates reverse-questions from the answer and checks cosine similarity with the original question).

Commit:
```bash
git add backend/app/agent/prompts.py
git commit -m "fix(prompt): lead with direct answer before citations to improve answer_relevancy"
```

**B) Add multi-query expansion alongside HyDE:**

In `improved_rag.py`, add a second semantic search pass using a rephrased query. Open `backend/app/retrieval/improved_rag.py` and in `improved_graph_rag_retrieve`, after the HyDE expansion, add:

```python
    # Step 1b: multi-query expansion — rephrase to code-navigation form
    # "How does X work?" → "Where is X implemented? What does X call?"
    nav_query = f"definition implementation source code of {query}"
    nav_results = semantic_search(nav_query, repo_path, top_k=max_nodes // 2, db_path=db_path)
    lists_to_merge = [lst for lst in [seed_results, hyde_results, nav_results, fts_results] if lst]
```

Commit:
```bash
git add backend/app/retrieval/improved_rag.py
git commit -m "feat(retrieval): add nav-query expansion — 'definition implementation of X' alongside HyDE"
```

---

#### If `context_precision` < 0.75

**Root cause:** Retrieved nodes are relevant but not ranked with the most relevant ones first (context precision is a ranking metric).

**A) Tighten the test-file penalty:**

In `improved_rag.py`, increase `_TEST_PENALTY` from 0.5 to 0.3:

```python
_TEST_PENALTY = 0.3  # was 0.5 — stronger penalty keeps test files lower in ranking
```

**B) Reduce BFS threshold to surface more focused results:**

Change `bfs_score_threshold` default from 0.45 to 0.55 in `improved_graph_rag_retrieve`. This expands only the strongest seeds, producing a tighter, more relevant candidate pool.

```python
async def improved_graph_rag_retrieve(
    ...
    bfs_score_threshold: float = 0.55,  # was 0.45
    ...
```

**C) Increase the candidate pool multiplier:**

In `improved_rag.py`, change:
```python
scored = rerank_and_assemble(expanded, seed_scores, G, max_nodes * 3)  # was max_nodes * 2
```

A larger pool for the cross-encoder gives it more options and tends to improve context precision.

Commit:
```bash
git add backend/app/retrieval/improved_rag.py
git commit -m "tune(retrieval): tighten test penalty + BFS threshold + wider CE pool for precision"
```

---

#### If `faithfulness` < 0.75

**Root cause:** The LLM is generating claims not supported by the retrieved context.

**A) Add grounding reinforcement to the prompt:**

Open `backend/app/agent/prompts.py` and add a rule:

```python
SYSTEM_PROMPT = """You are an expert code assistant. You answer questions about a codebase using ONLY the code context provided.

Rules:
1. Answer the question directly in 1-3 sentences first, then cite the evidence.
2. Cite code by referencing the exact file path and line range, e.g. `auth/login.py:42-55`.
3. Never fabricate a citation. Only cite locations that appear verbatim in the context headers.
4. If the context does not contain enough information, say: "I'm not certain based on the retrieved context."
5. Do not invent function names, class names, or module paths not present in the context.
6. Keep answers concise. Lead with the answer, not the file path.
7. Every factual claim about the code MUST be traceable to a specific line in the provided context.
"""
```

**B) Raise `max_nodes` to 20 in the eval script and `improved_rag.py`:**

More context gives the LLM more grounding material. In `run_ragas_three_way.py`:

```python
MAX_NODES = 20  # was 15
```

And update the retrieval calls:
```python
graph_nodes, graph_stat = graph_rag_retrieve(q, REPO_PATH, G, DB_PATH, max_nodes=20, hop_depth=1)
improved_nodes, improved_stat = await improved_graph_rag_retrieve(q, REPO_PATH, G, DB_PATH, max_nodes=20, hop_depth=1)
```

Commit:
```bash
git add backend/app/agent/prompts.py eval/run_ragas_three_way.py
git commit -m "tune(faithfulness): stronger grounding rules + max_nodes 15→20"
```

---

#### If all three are close to 0.75 but not there

**Run a spot-check on 10 questions before committing to a full 30-question run:**

```bash
cd /Users/mohammedhafiz/Desktop/Personal/nexus
source venv_eval/bin/activate
python eval/run_ragas_three_way.py --limit 10 --judge ollama --workers 1
```

If the 10-question spot-check shows improvement in the right direction, run the full 30:

```bash
OLLAMA_NUM_PARALLEL=2 python eval/run_ragas_three_way.py --limit 30 --workers 2
```

---

### Iteration Tracking

Fill in after each iteration:

| Iteration | Change applied | faith | ans_rel | ctx_prec | Met 0.75? |
|-----------|---------------|-------|---------|----------|-----------|
| 1 (baseline) | — | ? | ? | ? | — |
| 2 | | | | | |
| 3 | | | | | |
| 4 | | | | | |

**DONE when all three Improved metrics ≥ 0.75.**

Final commit when target is reached:
```bash
cd /Users/mohammedhafiz/Desktop/Personal/nexus
git add eval/results/ragas_three_way_*.json
git commit -m "eval: RAGAS target reached — all three metrics ≥ 0.75 on golden_qa_v2"
```
