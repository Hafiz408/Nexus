# MCP Tools

Optional side-effect tools for the agent pipeline. Failures are **non-fatal** — the core result still reaches the extension even if a tool fails.

## Tools

### `write_test_file`

Writes generated test code to the filesystem.

- Path must be relative — rejects `..` traversal
- Allowed extensions: `.py .ts .js .tsx .jsx .java .go`
- Won't overwrite existing files unless `overwrite=True`

### `post_review_comments`

Posts review findings as inline GitHub PR comments.

- Caps at 10 inline comments per call; excess becomes a single summary comment
- Retries 5xx responses with exponential backoff (max 3 attempts)
- 422 (invalid line number) → skip that finding, continue
- No-op when `GITHUB_TOKEN` is unset

## Configuration

```bash
GITHUB_TOKEN=ghp_xxxx   # leave empty to disable GitHub posting
```

The extension shows or hides the "Post to PR" button based on the `has_github_token` flag in the SSE result event.

## Degradation

```
MCP tool fails?
  → log warning
  → file_written = false  (test: fallback to copy-to-clipboard)
  → has_github_token = false  (review: hide PR button)
  Core result still delivered to extension
```
