# GitHub API tools — see spec/spec.md §6 for endpoints and security requirements
import os
import re

from github import Github

from src.models import PRMetadata

_INJECTION_PATTERNS = [
    r"ignore previous instructions",
    r"<\|im_start\|>",
    r"<\|im_end\|>",
    r"system prompt",
    r"you are now",
]
_MAX_DIFF_BYTES = 102_400  # 100 KB


def get_pr_metadata(url: str) -> PRMetadata:
    """Fetch PR metadata and diff from GitHub. Rejects diffs > 100KB."""
    from github import GithubException

    token = os.environ["GITHUB_TOKEN"]
    gh = Github(token)

    # Parse https://github.com/owner/repo/pull/N
    match = re.match(r"https://github\.com/([^/]+/[^/]+)/pull/(\d+)", url)
    if not match:
        raise ValueError(f"Invalid GitHub PR URL: {url}")
    repo_name, pr_number = match.group(1), int(match.group(2))

    try:
        repo = gh.get_repo(repo_name)
        pr = repo.get_pull(pr_number)
    except GithubException as e:
        if e.status == 404:
            raise RuntimeError(
                f"Repository '{repo_name}' not found (404). "
                "If this is a private repo, ensure your GITHUB_TOKEN has 'repo' scope."
            ) from None
        raise RuntimeError(f"GitHub API error {e.status}: {e.data}") from None

    # Build diff from file patches — uses only Pull requests: Read, no Contents permission needed.
    # Each File object from get_files() carries the unified patch for that file.
    diff_parts = []
    files_changed = []
    try:
        for f in pr.get_files():
            files_changed.append(f.filename)
            if f.patch:
                diff_parts.append(f"--- a/{f.filename}\n+++ b/{f.filename}\n{f.patch}")
    except GithubException as e:
        msg = e.data.get("message", str(e)) if isinstance(e.data, dict) else str(e)
        if e.status == 403:
            raise RuntimeError(
                f"GitHub 403: cannot read files for {repo_name}#{pr_number}. "
                "Your GITHUB_TOKEN needs read access: for fine-grained tokens add "
                "'Pull requests: Read' permission; for classic tokens add 'repo' scope."
            ) from None
        raise RuntimeError(f"GitHub API error {e.status}: {msg}") from None
    diff = "\n".join(diff_parts)

    _TRUNCATION_MARKER = "\n\n[diff truncated — exceeds 100 KB]"
    diff_bytes = diff.encode()
    if len(diff_bytes) > _MAX_DIFF_BYTES:
        keep = _MAX_DIFF_BYTES - len(_TRUNCATION_MARKER.encode("utf-8"))
        diff = diff_bytes[:keep].decode("utf-8", errors="ignore") + _TRUNCATION_MARKER

    return PRMetadata(
        url=url,
        repo=repo_name,
        pr_number=pr_number,
        title=pr.title,
        description=pr.body or "",
        diff=diff,
        files_changed=files_changed,
        lines_added=pr.additions,
        lines_removed=pr.deletions,
    )


def validate_diff(diff: str) -> str:
    """Strip prompt injection patterns from a PR diff before it reaches any LLM."""
    cleaned = diff
    for pattern in _INJECTION_PATTERNS:
        cleaned = re.sub(pattern, "[REDACTED]", cleaned, flags=re.IGNORECASE)
    return cleaned


def post_pr_comment(repo: str, pr_number: int, body: str) -> str:
    """Post a review comment to a GitHub PR. Returns the comment URL."""
    from github import GithubException

    token = os.environ["GITHUB_TOKEN"]
    gh = Github(token)
    try:
        issue = gh.get_repo(repo).get_issue(pr_number)
        comment = issue.create_comment(body)
    except GithubException as e:
        status = e.status
        msg = e.data.get("message", str(e)) if isinstance(e.data, dict) else str(e)
        if status == 403:
            raise RuntimeError(
                f"GitHub 403: cannot post comment to {repo}#{pr_number}. "
                "To post PR comments your GITHUB_TOKEN needs write access: "
                "for fine-grained tokens add 'Pull requests: Read and write' permission; "
                "for classic tokens use 'public_repo' scope (public repos) "
                "or 'repo' scope (private repos)."
            ) from None
        raise RuntimeError(f"GitHub {status}: {msg}") from None
    return comment.html_url
