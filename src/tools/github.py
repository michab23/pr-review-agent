# GitHub API tools — see spec/spec.md §6 for endpoints and security requirements
import os

from github import Github
from langfuse import observe

from src.guardrails.validators import InputValidator
from src.models import PRMetadata


@observe(name="get_pr_metadata", as_type="tool")
def get_pr_metadata(url: str) -> PRMetadata:
    """Fetch PR metadata and diff from GitHub. Rejects diffs > 100KB."""
    from github import GithubException

    token = os.environ["GITHUB_TOKEN"]
    gh = Github(token)

    repo_name, pr_number = InputValidator.validate_pr_url(url)

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

    diff = InputValidator.scrub_diff(diff)

    return PRMetadata(
        url=f"https://github.com/{repo_name}/pull/{pr_number}",
        repo=repo_name,
        pr_number=pr_number,
        title=pr.title,
        description=pr.body or "",
        diff=diff,
        files_changed=files_changed,
        lines_added=pr.additions,
        lines_removed=pr.deletions,
    )


@observe(name="validate_diff", as_type="tool")
def validate_diff(diff: str) -> str:
    """Scrub a PR diff before it reaches any LLM. Delegates to InputValidator."""
    return InputValidator.scrub_diff(diff)


@observe(name="post_pr_comment", as_type="tool")
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
