# Phase 23: mcp-tools - Research

**Researched:** 2026-03-22
**Domain:** GitHub REST API, Python filesystem I/O, HTTP retry logic
**Confidence:** HIGH

## Summary

Phase 23 adds two side-effect tools to the existing multi-agent pipeline: a GitHub MCP that posts Reviewer findings as PR comments, and a Filesystem MCP that writes Tester output to disk. Both tools are standalone Python modules (not LangGraph nodes) called by the orchestrator or API layer after a specialist agent produces its result. Neither tool modifies existing agents.

The GitHub MCP uses the GitHub REST API v3 via `httpx` (sync, no new async event-loop concerns). It batches up to 10 findings into a single review via `POST /repos/{owner}/{repo}/pulls/{pull_number}/reviews`, downgrades excess findings to a single issue comment via `POST /repos/{owner}/{repo}/issues/{pull_number}/comments`, retries 5xx responses three times with exponential backoff using `tenacity`, and skips any finding that produces a 422 (invalid line position) with a logged warning. The Filesystem MCP validates paths (rejects `..` traversal, rejects disallowed extensions, honours `overwrite=False`), creates parent directories, and writes the file. All behaviour is unit-testable with mocked HTTP responses — no live network calls are ever made in tests.

**Primary recommendation:** Implement both MCPs as a single new module `backend/app/mcp/tools.py` with two public functions `post_review_comments(...)` and `write_test_file(...)`. Add `httpx` and `tenacity` to `requirements.txt`. Test in `backend/tests/test_mcp_tools.py` using `unittest.mock.patch` to intercept `httpx.Client.post`.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| MCP-01 | GitHub MCP posts Reviewer findings as inline PR comments (max 10 per call; excess → summary comment); skips silently if no PR context or `github_token` not set | GitHub Reviews API batches ≤10 inline comments per call; issue comments API handles overflow |
| MCP-02 | GitHub MCP retries on 5xx errors (3 attempts, exponential backoff); skips invalid-line findings (422) with warning | tenacity `stop_after_attempt(3)` + `wait_exponential`; per-finding 422 catch + warning log |
| MCP-03 | Filesystem MCP writes Tester output to derived test file path; creates parent directories | `pathlib.Path.mkdir(parents=True, exist_ok=True)` + `Path.write_text()` |
| MCP-04 | Filesystem MCP rejects any path containing `..` | String check `".." in str(path)` before any I/O |
| MCP-05 | Filesystem MCP rejects extensions outside `.py`, `.ts`, `.js`, `.tsx`, `.jsx`, `.java`, `.go` | `Path.suffix` check against allowlist frozenset |
| MCP-06 | Filesystem MCP returns error (not overwrite) when file exists and `overwrite=False` | `Path.exists()` check before write; raise/return error dict |
| TST-06 | `test_mcp_tools.py` covers all behaviours with mocked GitHub API — no live network calls | `unittest.mock.patch("httpx.Client.post")` + `tmp_path` pytest fixture for filesystem tests |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| httpx | >=0.27.0 | Sync HTTP client for GitHub API calls | Already in Python ecosystem; async-capable but sync path avoids event-loop issues inside FastAPI; modern replacement for requests |
| tenacity | >=8.2.0 | Retry with exponential backoff on 5xx | Zero config, decorator-based, `retry_if_result` supports HTTP status-code predicates cleanly |
| pathlib | stdlib | Path manipulation and file I/O | Already used throughout project; `Path.mkdir(parents=True)`, `Path.write_text()`, `Path.suffix`, `Path.exists()` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| logging | stdlib | Warning log for skipped 422 findings | Log warning per skipped finding; caller receives summary of what was skipped |
| unittest.mock | stdlib | Mocking httpx.Client.post in tests | Patch `httpx.Client.post` at the call site |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| httpx | requests | requests is synchronous-only; httpx already in ecosystem consideration and supports both modes |
| tenacity | manual time.sleep retry loop | Manual loop is brittle, verbose, and hard to test; tenacity is a well-maintained standard |
| tenacity | httpx-retries | httpx-retries was deprecated in 2025; tenacity is actively maintained and already covers the exact need |

**Installation (additions to requirements.txt):**
```bash
httpx>=0.27.0
tenacity>=8.2.0
```

## Architecture Patterns

### Recommended Module Placement
```
backend/
└── app/
    ├── mcp/
    │   ├── __init__.py
    │   └── tools.py          # post_review_comments() + write_test_file()
    └── agent/
        ├── reviewer.py       # Finding, ReviewResult (unchanged)
        └── tester.py         # TestResult (unchanged)
backend/tests/
└── test_mcp_tools.py         # TST-06
```

The `mcp/` package is a new top-level package within `app/`. It does NOT go into `app/agent/` because MCP tools are side-effect I/O layers, not reasoning agents.

### Pattern 1: GitHub MCP — post_review_comments()

**What:** Posts a list of `Finding` objects as GitHub PR review inline comments. Caps at 10 inline comments; overflow becomes a single issue comment. No-ops when `github_token` is empty or `pr_number` is None.

**Signature:**
```python
def post_review_comments(
    findings: list[Finding],
    repo: str,          # "owner/repo"
    pr_number: int | None,
    commit_sha: str,
    github_token: str,
) -> dict:
    """Returns {"posted": int, "skipped": int, "summary_posted": bool}"""
```

**Flow:**
1. Guard: if `not github_token` or `pr_number is None` → return early with zeros
2. Split findings: `inline = findings[:10]`, `overflow = findings[10:]`
3. Build comments list for reviews API (see Code Examples section)
4. `POST /repos/{repo}/pulls/{pr_number}/reviews` with per-finding retry on 5xx via tenacity
5. For each finding that returns 422 → log warning, record as skipped, do not raise
6. If `overflow` → build single markdown summary → `POST /repos/{repo}/issues/{pr_number}/comments`
7. Return summary dict

**When to use:** Called after reviewer agent produces `ReviewResult` and PR context is available.

### Pattern 2: GitHub API endpoints

**Inline comments (batched in single review):**
```
POST https://api.github.com/repos/{owner}/{repo}/pulls/{pull_number}/reviews
Authorization: Bearer {token}
X-GitHub-Api-Version: 2022-11-28
Content-Type: application/json

{
  "commit_id": "{commit_sha}",
  "event": "COMMENT",
  "body": "",
  "comments": [
    {
      "path": "{finding.file_path}",
      "line": {finding.line_start},
      "body": "[{finding.severity}] {finding.description}\n\nSuggestion: {finding.suggestion}"
    }
  ]
}
```

**Summary / overflow comment:**
```
POST https://api.github.com/repos/{owner}/{repo}/issues/{pull_number}/comments
Authorization: Bearer {token}
X-GitHub-Api-Version: 2022-11-28

{"body": "## Code Review Summary\n\n{markdown table of overflow findings}"}
```

Note: `repo` parameter is `"owner/repo"` string — split on `/` to get `owner` and `repo_name` for URL construction.

### Pattern 3: Filesystem MCP — write_test_file()

**What:** Writes test code to a derived path with validation guards.

**Signature:**
```python
def write_test_file(
    test_code: str,
    test_file_path: str,    # from TestResult.test_file_path
    base_dir: str = ".",    # repo root; written path = base_dir / test_file_path
    overwrite: bool = False,
) -> dict:
    """Returns {"success": bool, "path": str, "error": str | None}"""
```

**Validation order (each check returns error dict immediately on failure):**
1. Reject `..` in path: `if ".." in str(test_file_path)` → `{"success": False, "error": "path traversal rejected"}`
2. Reject disallowed extension: `if Path(test_file_path).suffix not in ALLOWED_EXTENSIONS` → error
3. Resolve full path: `full_path = Path(base_dir) / test_file_path`
4. Reject existing file when `overwrite=False`: `if full_path.exists() and not overwrite` → error
5. Create parent dirs: `full_path.parent.mkdir(parents=True, exist_ok=True)`
6. Write: `full_path.write_text(test_code, encoding="utf-8")`
7. Return `{"success": True, "path": str(full_path), "error": None}`

**When to use:** Called after tester agent produces `TestResult`.

### Pattern 4: Tenacity Retry for 5xx

```python
# Source: tenacity docs + httpx docs
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

def _is_5xx(exc: Exception) -> bool:
    return isinstance(exc, httpx.HTTPStatusError) and 500 <= exc.response.status_code < 600

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception(_is_5xx),
    reraise=True,
)
def _post_with_retry(client: httpx.Client, url: str, headers: dict, json: dict) -> httpx.Response:
    response = client.post(url, headers=headers, json=json)
    response.raise_for_status()   # raises HTTPStatusError on 4xx/5xx
    return response
```

The `reraise=True` ensures the final exception propagates after 3 failed attempts. 422 is caught separately in the caller (not retried — it is a permanent client error for that finding).

### Anti-Patterns to Avoid

- **Importing httpx at module level inside agent files:** Keep MCP imports inside `tools.py` only; agents never import httpx directly.
- **Using `requests` library:** Do not add requests; httpx is the consistent choice.
- **Retrying 422:** 422 means the line number is invalid for that diff — retrying will never succeed. Catch it separately, log a warning, and skip.
- **Catching all exceptions in retry predicate:** Only catch `HTTPStatusError` with 5xx status; network errors (`httpx.ConnectError`) should propagate immediately or be handled separately.
- **Writing to absolute path from test_file_path:** Always join `base_dir / test_file_path`; never allow `test_file_path` to be treated as absolute.
- **Lazy import inside write_test_file:** Unlike agents, MCP tools have no LLM calls and no `get_settings()` at module level, so lazy imports are not required — import httpx/tenacity at module top.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Exponential backoff retry | Manual `time.sleep(2**attempt)` loop | tenacity `wait_exponential` | Edge cases: jitter, max cap, reraise semantics, thread-safety |
| HTTP status error detection | `if response.status_code >= 500:` inside loop | `response.raise_for_status()` + tenacity predicate | Consistent with httpx idioms; raise_for_status covers all error ranges |
| Parent directory creation | `os.makedirs(path, exist_ok=True)` | `Path.parent.mkdir(parents=True, exist_ok=True)` | Project uses pathlib throughout; consistent with existing code |

**Key insight:** The retry and filesystem primitives each have well-known edge cases (backoff jitter, race conditions on mkdir, Unicode encoding). Use the standard tools.

## Common Pitfalls

### Pitfall 1: 422 on Invalid Line Numbers
**What goes wrong:** GitHub returns 422 when a `line` value does not correspond to a line in the diff (e.g., line is in a file context but not in the changed hunk).
**Why it happens:** The Reviewer agent generates `line_start` from graph node attributes, which may not align with the PR diff position.
**How to avoid:** Catch `httpx.HTTPStatusError` with `status_code == 422` separately from 5xx. Log warning including the finding's `file_path` and `line_start`. Skip the finding, do not abort the whole batch.
**Warning signs:** Tests with fabricated line numbers always hit 422; production comments on unchanged lines will 422.

### Pitfall 2: github_token Guard Must Check Truthiness Not None
**What goes wrong:** `github_token` in `Settings` defaults to `""` (empty string), not `None`. A guard of `if github_token is None` silently proceeds when token is empty.
**Why it happens:** Phase 16 decision: `github_token: str = ""` — downstream MCP layer checks truthiness.
**How to avoid:** Always guard with `if not github_token` (falsy check), not `if github_token is None`.

### Pitfall 3: repo Parameter Format
**What goes wrong:** GitHub API URLs require separate `{owner}` and `{repo}` path segments. If the caller passes `"owner/repo"` as a single string, the URL is malformed.
**How to avoid:** Accept `repo: str` in `"owner/repo"` format. Split inside the function: `owner, repo_name = repo.split("/", 1)`. Document the expected format in the docstring.

### Pitfall 4: Path Traversal Check Must Happen Before Path.resolve()
**What goes wrong:** `Path.resolve()` converts `../../etc/passwd` into an absolute path, after which the `..` is gone and the check is bypassed.
**How to avoid:** Check `".." in str(test_file_path)` on the raw input string BEFORE any Path operations. This is the first guard executed.

### Pitfall 5: httpx.Client Must Be Used as Context Manager in Tests
**What goes wrong:** If `httpx.Client()` is used without `with`, the mock patch target differs from the actual call site.
**How to avoid:** Use `with httpx.Client() as client:` in production code. In tests, patch `httpx.Client` at the module level: `@patch("app.mcp.tools.httpx.Client")`.

### Pitfall 6: Tenacity and 422 Confusion
**What goes wrong:** If the retry predicate is `status_code >= 400`, then 422 gets retried 3 times wastefully before failing.
**How to avoid:** Predicate must be `500 <= status_code < 600` only. Test that a mocked 422 response is NOT retried (assert `mock_post.call_count == 1`).

## Code Examples

Verified patterns from official sources and project codebase conventions:

### GitHub inline review — request body construction
```python
# Source: https://docs.github.com/en/rest/pulls/reviews
comments_payload = [
    {
        "path": f.file_path,
        "line": f.line_start,
        "body": f"**[{f.severity}] {f.category}**\n\n{f.description}\n\n*Suggestion:* {f.suggestion}",
    }
    for f in inline_findings
]
payload = {
    "commit_id": commit_sha,
    "event": "COMMENT",
    "body": "",
    "comments": comments_payload,
}
```

### GitHub overflow summary comment
```python
# Source: https://docs.github.com/en/rest/issues/comments
lines = ["## Code Review Summary (additional findings)\n"]
for f in overflow_findings:
    lines.append(f"- **[{f.severity}]** `{f.file_path}:{f.line_start}` — {f.description}")
summary_body = "\n".join(lines)
overflow_payload = {"body": summary_body}
# POST /repos/{owner}/{repo_name}/issues/{pr_number}/comments
```

### Tenacity retry predicate for 5xx only
```python
# Source: tenacity docs (tenacity.readthedocs.io) + httpx docs
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

def _is_server_error(exc: Exception) -> bool:
    return (
        isinstance(exc, httpx.HTTPStatusError)
        and 500 <= exc.response.status_code < 600
    )

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception(_is_server_error),
    reraise=True,
)
def _post_with_retry(client: httpx.Client, url: str, headers: dict, json_body: dict) -> httpx.Response:
    resp = client.post(url, headers=headers, json=json_body, timeout=10.0)
    resp.raise_for_status()
    return resp
```

### Filesystem path validation guards
```python
# Source: stdlib pathlib, project convention
from pathlib import Path

ALLOWED_EXTENSIONS: frozenset[str] = frozenset({
    ".py", ".ts", ".js", ".tsx", ".jsx", ".java", ".go"
})

def write_test_file(test_code: str, test_file_path: str, base_dir: str = ".", overwrite: bool = False) -> dict:
    # Guard 1: path traversal
    if ".." in str(test_file_path):
        return {"success": False, "path": None, "error": "path traversal rejected: '..' found in path"}

    # Guard 2: extension allowlist
    if Path(test_file_path).suffix not in ALLOWED_EXTENSIONS:
        return {"success": False, "path": None, "error": f"extension '{Path(test_file_path).suffix}' not allowed"}

    full_path = Path(base_dir) / test_file_path

    # Guard 3: existing file + overwrite=False
    if full_path.exists() and not overwrite:
        return {"success": False, "path": str(full_path), "error": "file already exists and overwrite=False"}

    # Write
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(test_code, encoding="utf-8")
    return {"success": True, "path": str(full_path), "error": None}
```

### Test mocking pattern (consistent with project patterns)
```python
# Source: project pattern from test_orchestrator.py, test_reviewer.py
from unittest.mock import MagicMock, patch
import httpx

def test_post_review_comments_calls_github_api(tmp_path):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status.return_value = None

    with patch("app.mcp.tools.httpx.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        result = post_review_comments(
            findings=sample_findings[:3],
            repo="owner/myrepo",
            pr_number=42,
            commit_sha="abc123",
            github_token="ghp_token",
        )

    assert result["posted"] == 3
    assert mock_client.post.call_count == 1  # single review call batching all 3
```

### Test: 10-comment cap + overflow summary
```python
def test_overflow_beyond_10_posts_summary_comment():
    # 12 findings → 10 inline + 1 summary issue comment
    # assert mock_client.post.call_count == 2
    # First call: /pulls/{pr}/reviews with 10 comments
    # Second call: /issues/{pr}/comments with summary body
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `requests` + urllib3 Retry adapter | `httpx` + `tenacity` | 2023-2024 shift | httpx is now the standard sync/async HTTP client; urllib3 retry adapters are requests-specific |
| `httpx-retry` transport | `tenacity` decorator | 2025 (httpx-retry deprecated) | tenacity is actively maintained and more expressive for status-code-based retry |
| `os.makedirs` | `pathlib.Path.mkdir(parents=True)` | Python 3.5+ | pathlib is idiomatic Python 3; project already uses pathlib exclusively |

**Deprecated/outdated:**
- `httpx-retry`: Abandoned 2025-04-23, do not use. Use `tenacity` instead.
- `httpx-retries`: Separate active project (not the same as httpx-retry), but tenacity is simpler and project already imports nothing in this space.

## Open Questions

1. **commit_sha availability**
   - What we know: GitHub review comments require `commit_id` (SHA of the commit to attach comments to)
   - What's unclear: Where does the orchestrator or API caller obtain the commit SHA? It is not currently in `NexusState` or `ReviewResult`.
   - Recommendation: The planner should add `commit_sha: str | None` and `pr_number: int | None` as optional parameters to `post_review_comments()`. The caller (query endpoint or VS Code extension) is responsible for supplying these from PR context. The MCP tool silently no-ops when they are absent (same guard as missing github_token).

2. **Per-finding retry vs batch retry**
   - What we know: The reviews API batches all inline comments into one request.
   - What's unclear: If one finding in the batch has an invalid line (422), does the entire review call fail, or does GitHub accept the rest?
   - Recommendation: The safe approach is to iterate findings individually if batching fails with 422. Plan for: (a) try batch; (b) if 422, retry one-by-one catching 422 per finding. This keeps the 10-comment cap behaviour while isolating invalid-line failures.

3. **Test file path relative vs absolute**
   - What we know: `TestResult.test_file_path` is a relative path like `tests/test_func.py`.
   - What's unclear: Should `base_dir` default to the current working directory or be required?
   - Recommendation: Default `base_dir="."` matches the tester agent's implicit repo-root assumption. Document that callers should pass the actual repo root.

## Sources

### Primary (HIGH confidence)
- https://docs.github.com/en/rest/pulls/reviews — POST review endpoint, request schema, 422 meaning
- https://docs.github.com/en/rest/issues/comments — POST issue comment for summary fallback
- https://docs.github.com/en/rest/pulls/comments — PR review comment endpoint details
- https://www.python-httpx.org/advanced/transports/ — httpx native retry scope (network errors only, not 5xx)
- tenacity.readthedocs.io — `stop_after_attempt`, `wait_exponential`, `retry_if_exception` API
- stdlib pathlib — `Path.mkdir(parents=True)`, `Path.write_text()`, `Path.suffix`, `Path.exists()`

### Secondary (MEDIUM confidence)
- scrapeops.io/python-web-scraping-playbook/python-httpx-retry-failed-requests/ — httpx + tenacity pattern for status-code retry (verified against tenacity docs)
- Project codebase: `backend/app/agent/reviewer.py` — `Finding` model schema (file_path, line_start, severity, description, suggestion)
- Project codebase: `backend/app/agent/tester.py` — `TestResult` model, `test_file_path` convention
- Project codebase: `backend/app/config.py` — `github_token: str = ""` default, truthiness check pattern

### Tertiary (LOW confidence)
- Per-finding vs batch 422 behaviour (could not verify from official docs whether GitHub accepts partial batches on 422)

## Metadata

**Confidence breakdown:**
- Standard stack (httpx + tenacity + pathlib): HIGH — verified from official docs and pypi
- GitHub API endpoints and request schema: HIGH — verified from official GitHub REST docs
- Architecture (mcp/ package placement): HIGH — consistent with project structure
- Pitfalls: HIGH for token/422/traversal guards; MEDIUM for batch vs per-finding 422 behaviour
- Test mocking pattern: HIGH — consistent with established project pattern from phases 17-22

**Research date:** 2026-03-22
**Valid until:** 2026-04-22 (GitHub REST API is stable; tenacity API is stable)
