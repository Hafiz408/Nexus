"""MCP Tool Layer — side-effect I/O for the V2 multi-agent pipeline.

Exposes:
  - post_review_comments(findings, repo, pr_number, commit_sha, github_token) -> dict
  - write_test_file(test_code, test_file_path, base_dir, overwrite) -> dict

Neither function imports from app.agent.* at module level to avoid circular
imports. Finding type is imported locally inside post_review_comments.
httpx and tenacity are imported at module level (no lazy import needed —
MCP tools have no get_llm() / get_settings() call at import time).
"""
from __future__ import annotations

import logging
from pathlib import Path

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS: frozenset[str] = frozenset({
    ".py", ".ts", ".js", ".tsx", ".jsx", ".java", ".go"
})


def _is_server_error(exc: Exception) -> bool:
    """Return True only for HTTP 5xx — 422 is a permanent client error, never retried."""
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
def _post_with_retry(
    client: httpx.Client, url: str, headers: dict, json_body: dict
) -> httpx.Response:
    resp = client.post(url, headers=headers, json=json_body, timeout=10.0)
    resp.raise_for_status()
    return resp


def post_review_comments(
    findings: list,          # list[Finding] — typed as list to avoid circular import
    repo: str,               # "owner/repo" format — split internally
    pr_number: int | None,
    commit_sha: str,
    github_token: str,
) -> dict:
    """Post Reviewer findings as GitHub PR inline comments.

    Caps at 10 inline comments per call; excess findings become a single
    summary issue comment. No-ops when github_token is falsy (empty string
    per Phase 16 decision) or pr_number is None.

    Returns {"posted": int, "skipped": int, "summary_posted": bool}.
    """
    # Guard: check truthiness — github_token defaults to "" not None (Phase 16 decision)
    if not github_token or pr_number is None:
        return {"posted": 0, "skipped": 0, "summary_posted": False}

    owner, repo_name = repo.split("/", 1)
    base_url = f"https://api.github.com/repos/{owner}/{repo_name}"
    headers = {
        "Authorization": f"Bearer {github_token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
        "Accept": "application/vnd.github+json",
    }

    inline_findings = findings[:10]
    overflow_findings = findings[10:]
    posted = 0
    skipped = 0

    # Build inline review batch
    comments_payload = [
        {
            "path": f.file_path,
            "line": f.line_start,
            "body": (
                f"**[{f.severity}] {f.category}**\n\n"
                f"{f.description}\n\n"
                f"*Suggestion:* {f.suggestion}"
            ),
        }
        for f in inline_findings
    ]

    review_payload = {
        "commit_id": commit_sha,
        "event": "COMMENT",
        "body": "",
        "comments": comments_payload,
    }

    # Post inline review — retry on 5xx; catch 422 per-finding fallback below
    with httpx.Client() as client:
        try:
            _post_with_retry(
                client,
                f"{base_url}/pulls/{pr_number}/reviews",
                headers,
                review_payload,
            )
            posted = len(inline_findings)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 422:
                # Batch has at least one invalid line — retry one-by-one
                logger.warning(
                    "Batch review returned 422; retrying findings individually"
                )
                for finding in inline_findings:
                    single_payload = {
                        "commit_id": commit_sha,
                        "event": "COMMENT",
                        "body": "",
                        "comments": [
                            {
                                "path": finding.file_path,
                                "line": finding.line_start,
                                "body": (
                                    f"**[{finding.severity}] {finding.category}**\n\n"
                                    f"{finding.description}\n\n"
                                    f"*Suggestion:* {finding.suggestion}"
                                ),
                            }
                        ],
                    }
                    try:
                        _post_with_retry(
                            client,
                            f"{base_url}/pulls/{pr_number}/reviews",
                            headers,
                            single_payload,
                        )
                        posted += 1
                    except httpx.HTTPStatusError as inner_exc:
                        if inner_exc.response.status_code == 422:
                            logger.warning(
                                "Skipping finding with invalid line position: "
                                "%s:%s",
                                finding.file_path,
                                finding.line_start,
                            )
                            skipped += 1
                        else:
                            raise
            else:
                raise

        # Overflow summary comment
        summary_posted = False
        if overflow_findings:
            lines = ["## Code Review Summary (additional findings)\n"]
            for f in overflow_findings:
                lines.append(
                    f"- **[{f.severity}]** `{f.file_path}:{f.line_start}` — {f.description}"
                )
            overflow_payload = {"body": "\n".join(lines)}
            _post_with_retry(
                client,
                f"{base_url}/issues/{pr_number}/comments",
                headers,
                overflow_payload,
            )
            summary_posted = True

    return {"posted": posted, "skipped": skipped, "summary_posted": summary_posted}


def write_test_file(
    test_code: str,
    test_file_path: str,     # relative path from TestResult.test_file_path
    base_dir: str = ".",     # repo root; final path = base_dir / test_file_path
    overwrite: bool = False,
) -> dict:
    """Write generated test code to disk with safety validation.

    Validation order (each guard returns immediately on failure):
      1. Reject '..' in path (path traversal protection — BEFORE any Path ops)
      2. Reject disallowed extension
      3. Reject existing file when overwrite=False
      4. Create parent directories
      5. Write file

    Returns {"success": bool, "path": str | None, "error": str | None}.
    """
    # Guard 1: path traversal — check raw string BEFORE Path.resolve() or join
    if ".." in str(test_file_path):
        return {
            "success": False,
            "path": None,
            "error": "path traversal rejected: '..' found in path",
        }

    # Guard 2: extension allowlist
    ext = Path(test_file_path).suffix
    if ext not in ALLOWED_EXTENSIONS:
        return {
            "success": False,
            "path": None,
            "error": f"extension '{ext}' not allowed; must be one of {sorted(ALLOWED_EXTENSIONS)}",
        }

    # Resolve full path only after guards pass
    full_path = Path(base_dir) / test_file_path

    # Guard 3: existing file protection
    if full_path.exists() and not overwrite:
        return {
            "success": False,
            "path": str(full_path),
            "error": "file already exists and overwrite=False",
        }

    # Write
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(test_code, encoding="utf-8")
    return {"success": True, "path": str(full_path), "error": None}
