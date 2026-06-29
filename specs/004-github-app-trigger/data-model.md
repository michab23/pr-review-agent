# Data Model: GitHub Integration for Auto-Triggered PR Review

**Feature**: `010-github-app-trigger`  
**Date**: 2026-06-27

---

## Entities

### WebhookEvent

Represents a single delivery from GitHub. Used for deduplication and routing.

| Field | Type | Source | Notes |
|-------|------|--------|-------|
| `delivery_id` | `str` | `X-GitHub-Delivery` header | UUID; same on retry |
| `event_type` | `str` | `X-GitHub-Event` header | `"pull_request"` |
| `action` | `str` | payload `action` | `"opened"` / `"synchronize"` / `"ready_for_review"` |
| `pr_number` | `int` | payload `pull_request.number` | |
| `repo_full_name` | `str` | payload `repository.full_name` | `"owner/repo"` |
| `pr_url` | `str` | payload `pull_request.html_url` | Passed to `src.pipeline.run()` |
| `head_sha` | `str` | payload `pull_request.head.sha` | Latest commit; used as run key |
| `is_draft` | `bool` | payload `pull_request.draft` | Skip if `True` (on `opened`) |
| `installation_id` | `int` | payload `installation.id` | Used to get GitHub App token |
| `received_at` | `datetime` | server time | For deduplication TTL |

**Uniqueness rule**: `delivery_id` is globally unique per GitHub delivery. Two retries of the same event share the same `delivery_id`.

**State filter**: Only process events where:
- `action in {"opened", "synchronize", "ready_for_review"}` AND
- `is_draft == False` (for `opened`) — `ready_for_review` is never draft

---

### PipelineRun

In-memory record of an active or completed pipeline execution. Keyed by `pr_key`.

| Field | Type | Notes |
|-------|------|-------|
| `pr_key` | `str` | `"{repo_full_name}#{pr_number}"` — one active run per PR |
| `task` | `asyncio.Task` | Current asyncio task; cancelled on supersede |
| `stop_event` | `threading.Event` | Set to signal cooperative cancellation to pipeline thread |
| `triggered_by` | `str` | `delivery_id` of the event that launched this run |
| `head_sha` | `str` | Commit SHA this run is reviewing |
| `status` | `Literal["running", "completed", "cancelled", "failed"]` | |
| `started_at` | `datetime` | |

**Lifecycle / state transitions:**

```
(new event arrives)
        │
        ▼
   [running] ──── new event for same PR ────► [cancelled]
        │
        ├── pipeline completes ──────────────► [completed]
        │
        └── pipeline raises exception ────────► [failed]
```

**Invariant**: At most one `PipelineRun` with `status == "running"` per `pr_key`.

---

### AppInstallation

Managed entirely by GitHub. The webhook receiver reads `installation.id` from each payload and uses it to obtain a scoped GitHub App token. No local persistence needed for MVP.

| Field | Type | Source |
|-------|------|--------|
| `installation_id` | `int` | GitHub webhook payload |
| `repo_full_name` | `str` | GitHub webhook payload |

---

### SeenDeliveries

In-memory deduplication store.

| Field | Type | Notes |
|-------|------|-------|
| `delivery_id` | `str` | Key |
| `received_at` | `datetime` | For TTL eviction (24h) |

**Eviction rule**: On each incoming event, remove entries older than 24 hours before checking membership.

---

## Pipeline Integration Point

The webhook runner calls the existing `src.pipeline.run()` with two new parameters (minimal surgical change):

```python
# Current signature
def run(pr_url: str) -> PipelineState: ...

# Updated signature (backward-compatible default values)
def run(pr_url: str, *, skip_hitl: bool = False, stop_event: threading.Event | None = None) -> PipelineState: ...
```

| Parameter | CLI path | Automated path |
|-----------|----------|----------------|
| `skip_hitl` | `False` (HITL runs normally) | `True` (gate bypassed, auto-post) |
| `stop_event` | `None` (ignored) | `threading.Event` (checked after each agent) |

Stop-event check points inside `run()` (after each agent completes):
```python
if stop_event and stop_event.is_set():
    state.error = "cancelled"
    return state
```

---

## In-Memory Registries (server lifetime)

```python
# src/webhook/runner.py
_tasks:      dict[str, asyncio.Task]       = {}  # pr_key → Task
_stop_flags: dict[str, threading.Event]    = {}  # pr_key → Event
_seen_ids:   dict[str, datetime]           = {}  # delivery_id → received_at
```

These are reset on server restart — acceptable for MVP. A persistent queue (Redis, etc.) is a future scaling concern outside this spec's scope.
