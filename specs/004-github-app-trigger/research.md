# Research: GitHub Integration for Auto-Triggered PR Review

**Feature**: `010-github-app-trigger`  
**Date**: 2026-06-27  
**Phase**: 0 — Research

---

## 1. GitHub App Authentication with PyGithub

**Decision**: Use `github.Auth.AppAuth` + `GithubIntegration.get_github_for_installation()`

**Rationale**: PyGithub >= 2.0 provides first-class GitHub App auth. No raw HTTP calls needed for posting PR comments or check runs — the installed library handles JWT creation, token exchange, and refresh automatically.

**Verified API signatures (from installed package):**
```python
from github import Auth, GithubIntegration, Github

# 1. Build App-level auth (signs JWTs with RS256)
app_auth = Auth.AppAuth(
    app_id=APP_ID,               # int or str from GitHub App settings
    private_key=PRIVATE_KEY_PEM, # str, contents of .pem file
)

# 2. Get an installation-scoped Github client
gi = GithubIntegration(auth=app_auth)
gh = gi.get_github_for_installation(installation_id)  # returns Github instance

# 3. Use gh normally — posts as the App installation bot account
repo = gh.get_repo("owner/repo")
pr = repo.get_pull(pr_number)
pr.create_issue_comment(review_comment_markdown)

# 4. Post "in progress" indicator via PR comment (PyGithub)
# NOTE: create_check_run does NOT exist in PyGithub — verified against installed package.
# For MVP: use a PR comment as the "in progress" signal.
comment = pr.create_issue_comment("🤖 AI review in progress…")
# Later: post the full review, and optionally delete the interim comment
comment.delete()
pr.create_issue_comment(full_review_markdown)

# For GitHub Check Runs (if needed later): raw REST call required
# token = gi.get_access_token(installation_id).token
# requests.post("https://api.github.com/repos/owner/repo/check-runs", headers={...}, json={...})
```

**App permissions required** (set when creating the GitHub App):
- Pull requests: Read & Write (to post comments)
- Checks: Write (to post status checks / check runs)
- Metadata: Read (to read repo info)

**Alternatives considered**:
- Webhook + PAT: ruled out — tied to a personal account, no status check support, not installable across orgs
- Raw `requests` against GitHub REST API: more code, reinvents what PyGithub provides

---

## 2. Async Task Management with Cancellation in FastAPI

**Decision**: `asyncio.create_task()` with a per-PR task registry + cooperative cancellation via `threading.Event`

**Rationale**: FastAPI's built-in `BackgroundTasks` is fire-and-forget — no handle, no cancellation. `asyncio.create_task()` gives a cancellable handle. However, the existing `run()` in `pipeline.py` is synchronous; it must be offloaded to a thread executor (`loop.run_in_executor`). Cancelling an asyncio task wrapping a sync thread does NOT stop the thread — only cooperative cancellation (checking a `threading.Event` stop flag inside the pipeline) can do that.

**Pattern:**
```python
import asyncio
import threading
from fastapi import FastAPI

app = FastAPI()
_tasks: dict[str, asyncio.Task] = {}          # pr_key → current task
_stop_flags: dict[str, threading.Event] = {}   # pr_key → stop event

async def _run_pipeline_for_pr(pr_key: str, pr_url: str, stop: threading.Event):
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, run, pr_url, stop)  # run() accepts stop_event

@app.post("/webhook")
async def webhook(request: Request):
    # ... validate signature, parse payload ...
    pr_key = f"{repo}#{pr_number}"

    # Cancel any in-flight run for this PR
    if pr_key in _tasks and not _tasks[pr_key].done():
        _stop_flags[pr_key].set()          # signal thread to stop cooperatively
        _tasks[pr_key].cancel()            # cancel the coroutine wrapper
        await asyncio.sleep(0)             # yield to let cancellation propagate

    # Launch new run
    stop = threading.Event()
    _stop_flags[pr_key] = stop
    task = asyncio.create_task(_run_pipeline_for_pr(pr_key, pr_url, stop))
    _tasks[pr_key] = task
    return {"status": "accepted"}
```

**Key gotcha**: `asyncio.Task.cancel()` injects `CancelledError` into the coroutine but the underlying thread in `run_in_executor` keeps running until it checks the `threading.Event`. The stop flag must be checked at meaningful points in `pipeline.py` — after each agent completes — to bound how long a cancelled run continues consuming API credits.

**Thread safety**: No concern. FastAPI async mode runs on a single-threaded event loop; `dict` reads and writes from coroutines are safe without locks.

**Alternatives considered**:
- `concurrent.futures.ProcessPoolExecutor`: enables hard cancellation but adds IPC complexity and startup overhead per-run
- Refactoring pipeline to pure async: cleanest long-term but out of scope here; would require replacing `select.select` and all sync agent calls

---

## 3. Webhook Signature Verification

**Decision**: Verify `X-Hub-Signature-256` header using HMAC-SHA256 over raw request body

**Pattern (stdlib only, no new dependency):**
```python
import hashlib
import hmac

def verify_signature(body: bytes, secret: str, header: str | None) -> bool:
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    received = header.removeprefix("sha256=")
    return hmac.compare_digest(expected, received)  # constant-time comparison
```

**Why constant-time**: timing attacks on naive `==` comparison can leak the secret byte-by-byte. `hmac.compare_digest` mitigates this.

---

## 4. Deduplication Strategy

**Decision**: Use GitHub's `X-GitHub-Delivery` header (UUID per delivery) stored in an in-memory set, with TTL expiry after 24 hours.

**Rationale**: GitHub retries webhook deliveries on timeout/5xx responses with the same delivery UUID. Tracking seen delivery IDs prevents duplicate pipeline runs. The set is bounded by discarding entries older than 24 hours (PRs don't receive the same delivery ID after a day).

**For MVP**: A plain `set[str]` is sufficient. Expiry can be approximated by capping the set size (evict oldest) or resetting at server restart (acceptable for a hosted service with rare restarts).

---

## 5. Draft PR Event Filtering

**Decision**: Check `pull_request.draft` field in payload; for `synchronize` events, also check PR draft status via API

**GitHub sends:**
- `action: "opened"` — payload includes `"draft": true/false`
- `action: "ready_for_review"` — only fires when draft→ready transition happens; always non-draft
- `action: "synchronize"` — for push events; payload does NOT include draft status → need API call or cache

**Simple approach for synchronize**: call `repo.get_pull(pr_number).draft` to check. Adds one API call per push event but avoids maintaining a draft-status cache.

---

## Summary of Technology Choices

| Concern | Choice | Rationale |
|---------|--------|-----------|
| HTTP server | FastAPI + uvicorn | Async-native, Pydantic built-in, matches project style |
| GitHub App auth | `PyGithub.Auth.AppAuth` | Already installed, handles JWT + token refresh |
| Check runs / comments | `PyGithub` (existing) | `repo.create_check_run()`, `pr.create_issue_comment()` |
| Webhook verification | `hmac` (stdlib) | Zero new dependencies |
| Task cancellation | `asyncio.create_task` + `threading.Event` | Only viable approach for sync pipeline code |
| Deduplication | In-memory `set` + delivery ID | Simple, no external state for MVP |
| New dependencies | `fastapi`, `uvicorn` | 2 additions; everything else is stdlib or existing |
