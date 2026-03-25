# MCP Tools

Model Context Protocol (MCP) tools provide side-effect I/O for the V2 multi-agent pipeline: posting review findings to GitHub PRs and writing test files to the user's filesystem.

## Overview

```
Specialist Result
    ↓
Review Intent?
    ├─ YES → post_review_comments()  [GitHub API]
    └─ NO
        Test Intent?
            ├─ YES → write_test_file()  [Filesystem]
            └─ NO  (no MCP for explain/debug)
    ↓
Result → Extension (with file_written / posted flags)
```

## Public Functions

### `post_review_comments`

**Purpose:** Post code review findings to a GitHub PR as inline comments.

**Signature:**
```python
def post_review_comments(
    findings: list,           # list[Finding] from ReviewResult
    repo: str,                # "owner/repo" format
    pr_number: int | None,
    commit_sha: str,
    github_token: str,
) -> dict:                    # {"posted": int, "skipped": int, "summary_posted": bool}
```

**Algorithm:**

1. **Guard check:** If `github_token` is falsy or `pr_number` is None, return {posted: 0, ...}
2. **Parse repo:** Split "owner/repo" into owner and repo_name
3. **Batch findings:** Cap at 10 inline comments per call
4. **Post inline comments:**
   - For each finding in top 10:
     - POST to `/repos/{owner}/{repo}/pulls/{pr}/comments`
     - Body includes severity, category, description, suggestion
     - Positioned at commit_sha, finding.file_path, finding.line_start
5. **Post summary (if > 10 findings):**
   - Excess findings become a single issue comment
   - POST to `/repos/{owner}/{repo}/issues/{pr}/comments`
6. **Error handling:**
   - 422 (invalid line numbers) → log warning, skip finding
   - 5xx → retry with exponential backoff (max 3 attempts)
   - Other errors → log, return partial results

**Request Example:**
```bash
curl -X POST https://api.github.com/repos/owner/repo/pulls/42/comments \
  -H "Authorization: Bearer github_token" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  -d '{
    "body": "**Critical** [security] SQL injection vulnerability...\nSuggestion: Use parameterized queries",
    "commit_id": "abc123...",
    "path": "backend/auth.py",
    "line": 45,
    "side": "RIGHT"
  }'
```

**Response:**
```python
{
    "posted": 8,           # inline comments successfully posted
    "skipped": 2,          # findings that failed (line issues, etc.)
    "summary_posted": True # whether excess findings got summary comment
}
```

**Constraints:**
- `github_token` must be a valid GitHub PAT (Personal Access Token)
- `pr_number` must be valid; invalid PR → silently no-op (not an error)
- Line numbers must be valid for the commit; invalid → 422 → skipped
- Max 10 inline comments per call (GitHub API rate limit)

**Error Recovery:**
- Single comment failure (422) → skip that finding, continue
- Multiple 5xx → retry with backoff, eventually fail gracefully
- No-op when github_token is empty string (Phase 16 decision)

---

### `write_test_file`

**Purpose:** Write generated test code to the filesystem via MCP.

**Signature:**
```python
def write_test_file(
    test_code: str,        # from TestResult.test_code
    test_file_path: str,   # from TestResult.test_file_path (deterministic)
    base_dir: str = ".",   # repo root
    overwrite: bool = False,
) -> dict:                 # {"success": bool, "path": str, "error": str}
```

**Algorithm:**

1. **Path validation:**
   - Check for `..` (directory traversal attack)
   - Reject if present → return {success: False, error: "..."}

2. **Extension validation:**
   ```python
   ALLOWED_EXTENSIONS = frozenset({".py", ".ts", ".js", ".tsx", ".jsx", ".java", ".go"})
   # Reject if test_file_path ends with disallowed extension
   ```

3. **File existence check:**
   - If file exists and overwrite=False → return {success: False, error: "File exists"}

4. **Directory creation:**
   - `Path(test_file_path).parent.mkdir(parents=True, exist_ok=True)`

5. **File write:**
   ```python
   Path(test_file_path).write_text(test_code, encoding="utf-8")
   return {success: True, path: test_file_path}
   ```

6. **Error handling:**
   - Permission denied → return {success: False, error: "..."}
   - Disk full → return {success: False, error: "..."}
   - Any exception → return {success: False, error: str(exc)}

**Example:**
```python
result = write_test_file(
    test_code="def test_route():\n    ...",
    test_file_path="tests/test_router.py",
    base_dir="/Users/me/nexus",
)
# Returns: {"success": True, "path": "tests/test_router.py"}
```

**Safety Measures:**

| Attack | Defense |
|--------|---------|
| Directory traversal (`../../../etc/passwd`) | Reject if `..` in path |
| Arbitrary file creation (`/etc/passwd`) | Only allow relative paths (base_dir prefix) |
| Executable code injection | Trust that LLM generates valid code; no sandboxing |
| Overwrite critical files | Guard with `overwrite` flag (default False) |

---

## Integration with Query Router

**V2 Query Path:**

```python
# In query_router.py, v2_event_generator()
if intent == "test":
    try:
        from app.mcp.tools import write_test_file as _write_test_file
        _mcp_result = _write_test_file(
            result_dict.get("test_code", ""),
            result_dict.get("test_file_path", "tests/test_output.py"),
            base_dir=str(request_body.repo_root or "."),
        )
        file_written = bool(_mcp_result.get("success", False))
        written_path = _mcp_result.get("path")
    except Exception as _mcp_exc:
        # Silent failure; file_written=False signals fallback
        logger.warning("write_test_file raised; file_written=False: %s", _mcp_exc)
        file_written = False
        written_path = None

# SSE result includes file_written and written_path for extension UI
payload = {
    "type": "result",
    "intent": "test",
    "result": result_dict,
    "has_github_token": ...,
    "file_written": file_written,
    "written_path": written_path,
}
```

**GitHub PR Posting (Future Phase 27+):**

```python
if intent == "review" and has_github_token:
    try:
        from app.mcp.tools import post_review_comments
        mcp_result = post_review_comments(
            findings=specialist_result.findings,
            repo=extract_github_repo(request_body.repo_path),  # e.g., "owner/repo"
            pr_number=extract_pr_number(...),  # from active PR URL
            commit_sha=get_commit_sha(),       # current commit
            github_token=settings.github_token,
        )
        # Payload includes mcp_result summary
    except Exception as mcp_exc:
        logger.warning("post_review_comments failed: %s", mcp_exc)
```

---

## Error Handling & Graceful Degradation

**Philosophy:** MCP tools are optional side effects. If they fail, the core result still reaches the extension.

**Handling Strategy:**

1. **Wrap in try-except**
2. **Log exceptions (non-fatal)**
3. **Return success=False in result dict**
4. **Extension shows fallback UI** (copy-to-clipboard for tests, no PR button for reviews)

**No Retry on First Failure:**

Unlike the Critic loop (which retries the specialist), MCP tool failures don't trigger specialist retries. The result is still valuable even if the side effect failed.

---

## Configuration

### GitHub Token (`GITHUB_TOKEN` in `.env`)

```bash
GITHUB_TOKEN=ghp_xxxxxxxxxxxx  # GitHub Personal Access Token

# Scopes required:
# - repo (read/write for PR comments)
# - read:user (read profile)
```

**Absence Handling:**

- If `GITHUB_TOKEN` is empty string (default in `.env.example`): post_review_comments() is a no-op
- Extension detects `has_github_token=False` and hides the "Post to GitHub PR" button
- User must set token in `.env` to enable posting

---

## Testing

MCP tools are unit-tested with mock HTTP clients:

| Test File | Coverage |
|-----------|----------|
| `test_mcp_tools.py` | post_review_comments retry logic, path validation, error cases |

**Key Test Cases:**

- **post_review_comments:**
  - 10 findings → all posted inline
  - 15 findings → 10 inline + 1 summary issue comment
  - 422 on line N → skip finding, continue
  - 5xx → retry with backoff (up to 3)
  - github_token empty → no-op

- **write_test_file:**
  - Valid path → file created
  - Path with `..` → rejected
  - Invalid extension → rejected
  - File exists, overwrite=False → rejected
  - File exists, overwrite=True → overwritten
  - Permission denied → {success: False, error: "..."}

Run tests:
```bash
python -m pytest backend/tests/test_mcp_tools.py -v
```

---

## Future Work (Phase 27+)

- [ ] Bidirectional MCP tools (e.g., fetch open PRs, current commit, branch info)
- [ ] Bulk finding posting (GitHub Suggestions API for batched comments)
- [ ] Support for GitLab, Gitea, Bitbucket (provider-agnostic posting)
- [ ] Test file preview before writing (ask user)
- [ ] Custom file naming templates (e.g., `test_{timestamp}_{intent}.py`)
- [ ] Dry-run mode for GitHub posting (show what would be posted)
