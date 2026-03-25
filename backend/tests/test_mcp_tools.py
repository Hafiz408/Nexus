"""Tests for backend/app/mcp/tools.py — TST-06 coverage.

All tests are fully offline: GitHub API interactions are mocked via
patch("app.mcp.tools.httpx.Client"), and filesystem tests use the
tmp_path pytest fixture for isolation.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
import httpx

from app.mcp.tools import post_review_comments, write_test_file, ALLOWED_EXTENSIONS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _finding(
    severity="warning",
    category="style",
    description="Test finding",
    file_path="src/foo.py",
    line_start=10,
    line_end=12,
    suggestion="Fix it",
):
    """Build a minimal Finding-compatible namespace for tests."""
    from types import SimpleNamespace
    return SimpleNamespace(
        severity=severity,
        category=category,
        description=description,
        file_path=file_path,
        line_start=line_start,
        line_end=line_end,
        suggestion=suggestion,
    )


def _mock_client(status_code: int = 200):
    """Return a pre-wired mock httpx.Client context manager."""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    if status_code < 400:
        mock_response.raise_for_status.return_value = None
    else:
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"HTTP {status_code}",
            request=MagicMock(),
            response=MagicMock(status_code=status_code),
        )

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.return_value = mock_response
    return mock_client


# ---------------------------------------------------------------------------
# post_review_comments tests
# ---------------------------------------------------------------------------

class TestPostReviewCommentsHappyPath:
    def test_posts_single_review_for_3_findings(self):
        """Three findings -> exactly 1 review call, posted=3, summary_posted=False."""
        findings = [_finding() for _ in range(3)]
        mock_client = _mock_client(200)

        with patch("app.mcp.tools.httpx.Client", return_value=mock_client):
            result = post_review_comments(
                findings=findings,
                repo="owner/myrepo",
                pr_number=42,
                commit_sha="abc123",
                github_token="ghp_token",
            )

        assert result["posted"] == 3
        assert result["skipped"] == 0
        assert result["summary_posted"] is False
        assert mock_client.post.call_count == 1  # single batched review call

    def test_review_url_contains_owner_and_repo(self):
        """URL must split 'owner/repo' into separate path segments."""
        findings = [_finding()]
        mock_client = _mock_client(200)

        with patch("app.mcp.tools.httpx.Client", return_value=mock_client):
            post_review_comments(
                findings=findings,
                repo="acme/backend",
                pr_number=7,
                commit_sha="def456",
                github_token="ghp_token",
            )

        url = mock_client.post.call_args[0][0]
        # URL must contain the correctly structured path: /repos/{owner}/{repo}/pulls/{pr}/reviews
        assert "/repos/acme/backend/pulls/7/reviews" in url
        # The repo string must be split at '/' so owner and repo_name are separate segments
        assert url.count("/") >= 6  # https://api.github.com/repos/acme/backend/pulls/7/reviews


class TestPostReviewCommentsOverflowCap:
    def test_12_findings_makes_2_api_calls(self):
        """12 findings -> 10 inline (1 review call) + 2 overflow (1 issue comment call)."""
        findings = [_finding(file_path=f"src/f{i}.py", line_start=i + 1) for i in range(12)]
        mock_client = _mock_client(200)

        with patch("app.mcp.tools.httpx.Client", return_value=mock_client):
            result = post_review_comments(
                findings=findings,
                repo="owner/repo",
                pr_number=5,
                commit_sha="sha999",
                github_token="ghp_token",
            )

        assert result["posted"] == 10
        assert result["summary_posted"] is True
        assert mock_client.post.call_count == 2

    def test_overflow_call_goes_to_issues_endpoint(self):
        """Second call for overflow must target /issues/{pr}/comments."""
        findings = [_finding(file_path=f"src/f{i}.py", line_start=i + 1) for i in range(12)]
        mock_client = _mock_client(200)

        with patch("app.mcp.tools.httpx.Client", return_value=mock_client):
            post_review_comments(
                findings=findings,
                repo="owner/repo",
                pr_number=5,
                commit_sha="sha999",
                github_token="ghp_token",
            )

        calls = mock_client.post.call_args_list
        assert "/issues/5/comments" in calls[1][0][0]

    def test_exactly_10_findings_no_overflow(self):
        """10 findings exactly -> 1 review call, summary_posted=False."""
        findings = [_finding(file_path=f"src/f{i}.py", line_start=i + 1) for i in range(10)]
        mock_client = _mock_client(200)

        with patch("app.mcp.tools.httpx.Client", return_value=mock_client):
            result = post_review_comments(
                findings=findings,
                repo="owner/repo",
                pr_number=3,
                commit_sha="abc",
                github_token="ghp_token",
            )

        assert result["summary_posted"] is False
        assert mock_client.post.call_count == 1


class TestPostReviewCommentsNoOp:
    def test_empty_token_returns_zeros_no_api_call(self):
        """Empty github_token (falsy) must no-op without any HTTP call."""
        with patch("app.mcp.tools.httpx.Client") as mock_client_class:
            result = post_review_comments(
                findings=[_finding()],
                repo="owner/repo",
                pr_number=1,
                commit_sha="abc",
                github_token="",   # empty string — Phase 16 default
            )

        assert result == {"posted": 0, "skipped": 0, "summary_posted": False}
        mock_client_class.assert_not_called()

    def test_none_pr_number_returns_zeros_no_api_call(self):
        """pr_number=None must no-op without any HTTP call."""
        with patch("app.mcp.tools.httpx.Client") as mock_client_class:
            result = post_review_comments(
                findings=[_finding()],
                repo="owner/repo",
                pr_number=None,
                commit_sha="abc",
                github_token="ghp_token",
            )

        assert result == {"posted": 0, "skipped": 0, "summary_posted": False}
        mock_client_class.assert_not_called()


class TestPostReviewComments5xxRetry:
    def test_5xx_raises_after_3_attempts(self):
        """500 response must trigger tenacity and raise after 3 attempts."""
        # Build a mock that always raises 5xx
        mock_response_500 = MagicMock()
        mock_response_500.status_code = 500
        mock_response_500.raise_for_status.side_effect = httpx.HTTPStatusError(
            message="Server Error",
            request=MagicMock(),
            response=MagicMock(status_code=500),
        )
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response_500

        with patch("app.mcp.tools.httpx.Client", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                post_review_comments(
                    findings=[_finding()],
                    repo="owner/repo",
                    pr_number=1,
                    commit_sha="abc",
                    github_token="ghp_token",
                )

        # tenacity retried 3 times total
        assert mock_client.post.call_count == 3


class TestPostReviewComments422Handling:
    def test_batch_422_falls_back_to_per_finding_and_skips_invalid(self):
        """Batch 422 -> retry individually; per-finding 422 is skipped, not raised."""
        # First call (batch) raises 422; second call (per-finding) raises 422
        call_count = [0]

        def _side_effect(*args, **kwargs):
            call_count[0] += 1
            mock_resp = MagicMock()
            mock_resp.status_code = 422
            exc = httpx.HTTPStatusError(
                message="Unprocessable Entity",
                request=MagicMock(),
                response=MagicMock(status_code=422),
            )
            mock_resp.raise_for_status.side_effect = exc
            return mock_resp

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = _side_effect

        with patch("app.mcp.tools.httpx.Client", return_value=mock_client):
            result = post_review_comments(
                findings=[_finding()],   # 1 finding
                repo="owner/repo",
                pr_number=1,
                commit_sha="abc",
                github_token="ghp_token",
            )

        # posted=0 (all skipped), skipped=1, summary_posted=False
        assert result["skipped"] == 1
        assert result["posted"] == 0
        assert result["summary_posted"] is False

    def test_422_is_not_retried_by_tenacity(self):
        """A 422 response must NOT trigger tenacity retry (call_count == 2 on first 422)."""
        mock_response = MagicMock()
        mock_response.status_code = 422
        exc_422 = httpx.HTTPStatusError(
            message="Unprocessable Entity",
            request=MagicMock(),
            response=MagicMock(status_code=422),
        )
        mock_response.raise_for_status.side_effect = exc_422

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response

        with patch("app.mcp.tools.httpx.Client", return_value=mock_client):
            # Single finding — batch call gets 422, per-finding call also gets 422
            result = post_review_comments(
                findings=[_finding()],
                repo="owner/repo",
                pr_number=1,
                commit_sha="abc",
                github_token="ghp_token",
            )

        # Batch (1 call) + per-finding (1 call) = 2 total; NOT 3 (tenacity not retrying 422)
        assert mock_client.post.call_count == 2
        assert result["skipped"] == 1


# ---------------------------------------------------------------------------
# write_test_file tests
# ---------------------------------------------------------------------------

class TestWriteTestFileHappyPath:
    def test_creates_file_with_content(self, tmp_path):
        """Writes test code to the resolved path and returns success."""
        result = write_test_file(
            test_code="def test_foo(): assert True",
            test_file_path="tests/test_foo.py",
            base_dir=str(tmp_path),
        )

        assert result["success"] is True
        assert result["error"] is None
        written = tmp_path / "tests" / "test_foo.py"
        assert written.exists()
        assert written.read_text(encoding="utf-8") == "def test_foo(): assert True"

    def test_creates_missing_parent_directories(self, tmp_path):
        """Parent directories that do not exist are created automatically."""
        result = write_test_file(
            test_code="// test",
            test_file_path="deep/nested/dir/test_bar.ts",
            base_dir=str(tmp_path),
        )

        assert result["success"] is True
        assert (tmp_path / "deep" / "nested" / "dir" / "test_bar.ts").exists()

    def test_overwrite_true_replaces_existing_file(self, tmp_path):
        """overwrite=True must replace an existing file without error."""
        existing = tmp_path / "tests" / "test_x.py"
        existing.parent.mkdir(parents=True)
        existing.write_text("old content", encoding="utf-8")

        result = write_test_file(
            test_code="new content",
            test_file_path="tests/test_x.py",
            base_dir=str(tmp_path),
            overwrite=True,
        )

        assert result["success"] is True
        assert existing.read_text(encoding="utf-8") == "new content"


class TestWriteTestFilePathTraversal:
    def test_rejects_dotdot_in_path(self, tmp_path):
        """'..' in test_file_path must be rejected before any filesystem operation."""
        result = write_test_file(
            test_code="code",
            test_file_path="../../etc/passwd",
            base_dir=str(tmp_path),
        )

        assert result["success"] is False
        assert "path traversal" in result["error"]
        # No file written
        assert not (tmp_path / "etc" / "passwd").exists()

    def test_rejects_embedded_dotdot(self, tmp_path):
        """Embedded '..' (e.g. 'tests/../../../etc') must also be rejected."""
        result = write_test_file(
            test_code="code",
            test_file_path="tests/../../../etc/shadow",
            base_dir=str(tmp_path),
        )

        assert result["success"] is False
        assert result["error"] is not None


class TestWriteTestFileExtensionFilter:
    def test_rejects_disallowed_extension(self, tmp_path):
        """Extensions outside the allowlist must be rejected."""
        result = write_test_file(
            test_code="rm -rf /",
            test_file_path="tests/malicious.sh",
            base_dir=str(tmp_path),
        )

        assert result["success"] is False
        assert ".sh" in result["error"] or "not allowed" in result["error"]

    def test_all_allowed_extensions_accepted(self, tmp_path):
        """Every extension in ALLOWED_EXTENSIONS must be accepted."""
        for ext in ALLOWED_EXTENSIONS:
            result = write_test_file(
                test_code=f"// test file {ext}",
                test_file_path=f"tests/test_file{ext}",
                base_dir=str(tmp_path),
                overwrite=True,
            )
            assert result["success"] is True, f"Expected {ext} to be allowed, got: {result}"


class TestWriteTestFileOverwriteProtection:
    def test_overwrite_false_rejects_existing_file(self, tmp_path):
        """When overwrite=False (default), existing file must not be modified."""
        existing = tmp_path / "tests" / "test_y.py"
        existing.parent.mkdir(parents=True)
        existing.write_text("original", encoding="utf-8")

        result = write_test_file(
            test_code="replacement",
            test_file_path="tests/test_y.py",
            base_dir=str(tmp_path),
            overwrite=False,
        )

        assert result["success"] is False
        assert "overwrite=False" in result["error"] or "already exists" in result["error"]
        # File unchanged
        assert existing.read_text(encoding="utf-8") == "original"
