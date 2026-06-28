# Contract: Webhook Receiver API

**Feature**: `010-github-app-trigger`  
**Date**: 2026-06-27

The webhook receiver exposes two HTTP endpoints consumed by GitHub (the webhook) and by operators (health check).

---

## POST /webhook

**Consumer**: GitHub (delivers `pull_request` events)  
**Authentication**: HMAC-SHA256 signature in `X-Hub-Signature-256` header

### Request

**Headers (required):**

| Header | Value |
|--------|-------|
| `X-GitHub-Event` | `pull_request` |
| `X-GitHub-Delivery` | UUID string (unique per delivery, same on retry) |
| `X-Hub-Signature-256` | `sha256=<hex>` (HMAC-SHA256 of raw body, signed with webhook secret) |
| `Content-Type` | `application/json` |

**Body** (GitHub pull_request webhook payload — relevant fields):

```json
{
  "action": "opened" | "synchronize" | "ready_for_review",
  "number": 42,
  "pull_request": {
    "html_url": "https://github.com/owner/repo/pull/42",
    "draft": false,
    "head": {
      "sha": "abc123def456"
    }
  },
  "repository": {
    "full_name": "owner/repo"
  },
  "installation": {
    "id": 12345678
  }
}
```

### Responses

| Status | Condition | Body |
|--------|-----------|------|
| `200 OK` | Event accepted (action recognized, pipeline started or queued) | `{"status": "accepted", "pr_key": "owner/repo#42"}` |
| `200 OK` | Event ignored (draft PR, unrecognised action, duplicate delivery) | `{"status": "ignored", "reason": "<string>"}` |
| `401 Unauthorized` | Missing or invalid `X-Hub-Signature-256` | `{"error": "invalid signature"}` |
| `422 Unprocessable Entity` | Missing required fields in payload | `{"error": "missing field: <field>"}` |
| `500 Internal Server Error` | Unexpected server error | `{"error": "internal error"}` |

**Note**: GitHub considers any `2xx` response a successful delivery. Return `200` even for ignored events to prevent GitHub from retrying them.

### Processing Rules (in order)

1. Verify `X-Hub-Signature-256` signature — reject `401` if invalid
2. Check `X-GitHub-Delivery` against seen-delivery set — return `200 {"status": "ignored", "reason": "duplicate"}` if seen
3. Check `X-GitHub-Event == "pull_request"` — return `200 {"status": "ignored"}` for other event types
4. Check `action in {"opened", "synchronize", "ready_for_review"}` — ignore others
5. For `action == "opened"`: check `pull_request.draft == false` — ignore drafts
6. Extract `pr_url`, `pr_key`, `installation_id`, `head_sha`
7. Cancel any in-flight run for `pr_key` (set stop flag + cancel task)
8. Launch new pipeline run in background
9. Return `200 {"status": "accepted"}`

---

## GET /health

**Consumer**: Operators, load balancers, uptime monitors

### Request

No headers or body required.

### Response

```json
{
  "status": "ok",
  "active_runs": 3
}
```

| Status | Condition |
|--------|-----------|
| `200 OK` | Server is healthy |
| `500 Internal Server Error` | Server is unhealthy (should not occur under normal operation) |

---

## GitHub App Webhook Configuration

When registering the webhook in the GitHub App settings:

| Field | Value |
|-------|-------|
| Webhook URL | `https://<host>/webhook` |
| Content type | `application/json` |
| Secret | Value of `GITHUB_WEBHOOK_SECRET` env var |
| Events | `pull_request` only |
| Active | ✓ |
