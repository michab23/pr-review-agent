import os
from datetime import datetime, timedelta, timezone

_TRIGGER_ACTIONS = {"opened", "synchronize", "ready_for_review"}
_DEDUP_TTL = timedelta(hours=24)

_seen_ids: dict[str, datetime] = {}


def _evict_expired() -> None:
    cutoff = datetime.now(timezone.utc) - _DEDUP_TTL
    expired = [k for k, v in _seen_ids.items() if v < cutoff]
    for k in expired:
        del _seen_ids[k]


def parse_event(
    headers: dict[str, str],
    body: dict,
) -> tuple[str, str, int, str] | None:
    """Parse and filter a GitHub pull_request webhook event.

    Returns (pr_url, pr_key, installation_id, head_sha) or None if the event
    should be ignored (wrong action, draft PR, duplicate delivery, blocked repo).
    """
    _evict_expired()

    action = body.get("action", "")
    if action not in _TRIGGER_ACTIONS:
        return None

    pr = body.get("pull_request", {})
    if action == "opened" and pr.get("draft", False):
        return None

    delivery_id = headers.get("x-github-delivery") or headers.get("X-GitHub-Delivery", "")
    if delivery_id and delivery_id in _seen_ids:
        return None

    repo_full_name = body.get("repository", {}).get("full_name", "")
    allowed_raw = os.environ.get("ALLOWED_REPOS", "")
    if allowed_raw:
        allowed = {r.strip() for r in allowed_raw.split(",") if r.strip()}
        if repo_full_name not in allowed:
            return None

    pr_number = pr.get("number") or body.get("number")
    pr_url = pr.get("html_url", "")
    head_sha = pr.get("head", {}).get("sha", "")
    installation_id = body.get("installation", {}).get("id")

    if not all([pr_url, pr_number, head_sha, installation_id, repo_full_name]):
        return None

    pr_key = f"{repo_full_name}#{pr_number}"

    if delivery_id:
        _seen_ids[delivery_id] = datetime.now(timezone.utc)

    return pr_url, pr_key, int(installation_id), head_sha
