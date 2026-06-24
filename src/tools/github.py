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
    token = os.environ["GITHUB_TOKEN"]
    gh = Github(token)

    # Parse https://github.com/owner/repo/pull/N
    match = re.match(r"https://github\.com/([^/]+/[^/]+)/pull/(\d+)", url)
    if not match:
        raise ValueError(f"Invalid GitHub PR URL: {url}")
    repo_name, pr_number = match.group(1), int(match.group(2))

    repo = gh.get_repo(repo_name)
    pr = repo.get_pull(pr_number)

    # Fetch unified diff via raw API
    import httpx
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3.diff"}
    resp = httpx.get(f"https://api.github.com/repos/{repo_name}/pulls/{pr_number}", headers=headers)
    diff = resp.text

    if len(diff.encode()) > _MAX_DIFF_BYTES:
        raise ValueError(f"Diff exceeds 100KB limit ({len(diff.encode())} bytes). Aborting.")

    files_changed = [f.filename for f in pr.get_files()]

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
        raise RuntimeError(f"GitHub {status}: {msg}") from None
    return comment.html_url
