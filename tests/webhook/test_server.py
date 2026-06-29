import hashlib
import hmac
import json
import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


def _make_sig(body: bytes, secret: str = "test-secret") -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.fixture(autouse=True)
def env_vars(monkeypatch):
    monkeypatch.setenv("GITHUB_APP_ID", "12345")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "test-secret")


@pytest.fixture()
def client():
    with patch("src.webhook.server._WEBHOOK_SECRET", "test-secret"):
        from src.webhook.server import app
        import src.webhook.event_filter as ef
        ef._seen_ids.clear()
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


def _pr_body(action="opened", draft=False, delivery_id="test-delivery-1"):
    return {
        "action": action,
        "number": 42,
        "pull_request": {
            "number": 42,
            "html_url": "https://github.com/owner/repo/pull/42",
            "draft": draft,
            "head": {"sha": "abc123"},
        },
        "repository": {"full_name": "owner/repo"},
        "installation": {"id": 999},
    }


def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "active_runs" in data


def test_health_returns_active_run_count(client):
    resp = client.get("/health")
    assert resp.json()["active_runs"] == 0


def test_webhook_invalid_signature(client):
    body = json.dumps(_pr_body()).encode()
    resp = client.post("/webhook",
                       content=body,
                       headers={"x-hub-signature-256": "sha256=badsig",
                                "x-github-event": "pull_request",
                                "content-type": "application/json"})
    assert resp.status_code == 401


def test_webhook_missing_signature(client):
    body = json.dumps(_pr_body()).encode()
    resp = client.post("/webhook",
                       content=body,
                       headers={"x-github-event": "pull_request",
                                "content-type": "application/json"})
    assert resp.status_code == 401


def test_webhook_non_pr_event_ignored(client):
    body = json.dumps({"action": "created"}).encode()
    resp = client.post("/webhook",
                       content=body,
                       headers={"x-hub-signature-256": _make_sig(body),
                                "x-github-event": "issues",
                                "x-github-delivery": "delivery-issues",
                                "content-type": "application/json"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


def test_webhook_installation_event_ignored(client):
    body = json.dumps({"action": "created"}).encode()
    resp = client.post("/webhook",
                       content=body,
                       headers={"x-hub-signature-256": _make_sig(body),
                                "x-github-event": "installation",
                                "x-github-delivery": "delivery-install",
                                "content-type": "application/json"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


def test_webhook_draft_pr_ignored(client):
    body = json.dumps(_pr_body("opened", draft=True)).encode()
    resp = client.post("/webhook",
                       content=body,
                       headers={"x-hub-signature-256": _make_sig(body),
                                "x-github-event": "pull_request",
                                "x-github-delivery": "delivery-draft",
                                "content-type": "application/json"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


def test_webhook_oversized_payload_rejected(client):
    body = b"x" * (10 * 1024 * 1024 + 1)
    resp = client.post("/webhook",
                       content=body,
                       headers={"x-hub-signature-256": _make_sig(body),
                                "x-github-event": "pull_request",
                                "x-github-delivery": "delivery-big",
                                "content-type": "application/json"})
    assert resp.status_code == 413


def test_webhook_valid_pr_accepted(client):
    body = json.dumps(_pr_body("opened")).encode()
    with patch("src.webhook.server.asyncio") as mock_asyncio:
        mock_asyncio.create_task = lambda coro: None
        resp = client.post("/webhook",
                           content=body,
                           headers={"x-hub-signature-256": _make_sig(body),
                                    "x-github-event": "pull_request",
                                    "x-github-delivery": "delivery-ok",
                                    "content-type": "application/json"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"
    assert resp.json()["pr_key"] == "owner/repo#42"
