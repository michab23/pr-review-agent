import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

import src.webhook.event_filter as ef
from src.webhook.event_filter import parse_event


def _headers(delivery_id="abc-123"):
    return {"x-github-delivery": delivery_id, "x-github-event": "pull_request"}


def _body(action="opened", draft=False, repo="owner/repo", pr_number=1,
          head_sha="abc123", install_id=999):
    return {
        "action": action,
        "number": pr_number,
        "pull_request": {
            "number": pr_number,
            "html_url": f"https://github.com/{repo}/pull/{pr_number}",
            "draft": draft,
            "head": {"sha": head_sha},
        },
        "repository": {"full_name": repo},
        "installation": {"id": install_id},
    }


@pytest.fixture(autouse=True)
def clear_seen_ids():
    ef._seen_ids.clear()
    yield
    ef._seen_ids.clear()


def test_opened_non_draft_accepted():
    result = parse_event(_headers(), _body("opened", draft=False))
    assert result is not None
    pr_url, pr_key, install_id, head_sha = result
    assert pr_key == "owner/repo#1"
    assert install_id == 999


def test_opened_draft_ignored():
    assert parse_event(_headers(), _body("opened", draft=True)) is None


def test_synchronize_accepted():
    assert parse_event(_headers(delivery_id="xyz"), _body("synchronize")) is not None


def test_ready_for_review_accepted():
    assert parse_event(_headers(delivery_id="zzz"), _body("ready_for_review")) is not None


def test_unknown_action_ignored():
    assert parse_event(_headers(), _body("closed")) is None


def test_duplicate_delivery_ignored():
    parse_event(_headers("dup-id"), _body("opened"))
    assert parse_event(_headers("dup-id"), _body("synchronize")) is None


def test_dedup_ttl_eviction():
    ef._seen_ids["old-id"] = datetime.now(timezone.utc) - timedelta(hours=25)
    result = parse_event(_headers("old-id"), _body("opened"))
    assert result is not None


def test_allowed_repos_blocks_unknown(monkeypatch):
    monkeypatch.setenv("ALLOWED_REPOS", "owner/repo1,owner/repo2")
    assert parse_event(_headers(), _body(repo="owner/other")) is None


def test_allowed_repos_passes_known(monkeypatch):
    monkeypatch.setenv("ALLOWED_REPOS", "owner/repo")
    assert parse_event(_headers(), _body(repo="owner/repo")) is not None


def test_allowed_repos_unset_allows_all(monkeypatch):
    monkeypatch.delenv("ALLOWED_REPOS", raising=False)
    assert parse_event(_headers(), _body(repo="any/repo")) is not None
