# Tasks: GitHub Integration for Auto-Triggered PR Review

**Input**: Design documents from `specs/004-github-app-trigger/`  
**Branch**: `010-github-app-trigger`  
**Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

---

## Format: `[ID] [P?] [SYNC/ASYNC] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[SYNC]**: Requires human review — complex logic, security-critical, or concurrency concerns
- **[ASYNC]**: Can be delegated to autonomous agent — well-defined, deterministic, low-risk
- **[USn]**: Maps task to User Story n from spec.md

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Add dependencies and scaffold the new webhook package

- [x] T001 [ASYNC] Add `fastapi` and `uvicorn` to `[project].dependencies` in `pyproject.toml` and run `uv sync`
- [x] T002 [P] [ASYNC] Create `src/webhook/` package: add empty `src/webhook/__init__.py` and `src/webhook/__main__.py` that calls `uvicorn.run("src.webhook.server:app", host="0.0.0.0", port=8000)`
- [x] T003 [P] [ASYNC] Create `tests/webhook/` test package: add empty `tests/webhook/__init__.py`

---

## Phase 2: Foundational (Blocking Prerequisite)

**Purpose**: Modify the existing pipeline to support automated (no-HITL) invocation. **All user story work blocks on this.**

**⚠️ CRITICAL**: No webhook integration work can start until T004 is complete and reviewed

- [x] T004 [SYNC] Add `skip_hitl: bool = False` and `stop_event: threading.Event | None = None` optional parameters to `run()` in `src/pipeline.py`. When `skip_hitl=True`: skip `human_approval_gate()`; skip `post_pr_comment()` (posting is delegated to runner.py so it can use the installation token); set `state.human_approved = True` and return `state` with `draft_comment` populated. Add `if stop_event and stop_event.is_set(): state.error = "cancelled"; return state` after each of the 3 agent blocks. CLI path (`__main__` block) passes no new arguments — behaviour unchanged. **Do NOT call `post_pr_comment()` in the `skip_hitl=True` branch** — calling it would use `GITHUB_TOKEN` (PAT) instead of the installation token, and would double-post alongside runner.py.

**Checkpoint**: `uv run python -m src.pipeline <pr-url>` still shows HITL gate and posts via `post_pr_comment()`. `run(pr_url, skip_hitl=True)` returns `state.draft_comment` populated, `state.human_approved = True`, nothing posted to GitHub.

---

## Phase 3: User Story 1 — Auto-Trigger Pipeline on PR Creation (Priority: P1) 🎯 MVP

**Goal**: A non-draft PR opened/pushed-to/marked-ready on a configured repo triggers the 3-agent pipeline automatically and posts the review comment without manual intervention.

**Independent Test**: `POST /webhook` with a valid GitHub pull_request payload → pipeline runs → review comment appears on PR. Verify with `ngrok` + real GitHub App installation (see quickstart.md).

### Implementation

- [x] T005 [P] [SYNC] [US1] Implement `verify_signature(body: bytes, secret: str, header: str | None) -> bool` in `src/webhook/signature.py` using `hmac.new(secret.encode(), body, hashlib.sha256)` and `hmac.compare_digest()` for constant-time comparison. No external dependencies.

- [x] T006 [P] [ASYNC] [US1] Implement `src/webhook/event_filter.py`:
  - `_seen_ids: dict[str, datetime]` module-level deduplication store with 24h TTL eviction
  - `parse_event(headers: dict, body: dict) -> tuple[str, str, int, str] | None` — returns `(pr_url, pr_key, installation_id, head_sha)` or `None` for ignored events
  - Filter rules (in order): action must be in `{"opened", "synchronize", "ready_for_review"}`; for `opened`, `body["pull_request"]["draft"]` must be `False`; delivery ID must not be in `_seen_ids`; add delivery ID to `_seen_ids` on success
  - Use `dataclasses` or plain tuples — no new models needed

- [x] T007 [SYNC] [US1] Implement `src/webhook/runner.py` — async task registry with cooperative cancellation:
  - Module-level `_tasks: dict[str, asyncio.Task]` and `_stop_flags: dict[str, threading.Event]`
  - `async def launch_run(pr_key: str, pr_url: str, installation_id: int) -> None`:
    1. Cancel in-flight task for `pr_key` if exists: set `_stop_flags[pr_key]`, cancel task, `await asyncio.sleep(0)`
    2. Build GitHub App client: `Auth.AppAuth(APP_ID, PRIVATE_KEY)` → `GithubIntegration(auth=app_auth)` → `gi.get_github_for_installation(installation_id)` → extract `repo_full_name` + `pr_number` from `pr_key` → `gh.get_repo(...).get_pull(...)` → post "🤖 AI review in progress…" comment and store the returned `Comment` object for deletion later **(FR-004 deliverable)**
    3. Create `stop = threading.Event()`, store in `_stop_flags[pr_key]`
    4. `asyncio.create_task(_run_task(pr_key, pr_url, stop, gh))`
  - `async def _run_task(pr_key, pr_url, stop, gh)`:
    1. `loop.run_in_executor(None, functools.partial(run, pr_url, skip_hitl=True, stop_event=stop))` — pipeline returns `PipelineState` with `draft_comment` populated but nothing posted
    2. On success: `pr.create_issue_comment(state.draft_comment)` via the `gh` installation client (uses installation token — resolves I1/I2); delete the interim "in progress" comment posted by `launch_run`
    3. On `CancelledError`: swallow silently (run superseded by newer push — interim comment left as-is or updated to "review superseded")
    4. On any other exception: `pr.create_issue_comment("⚠️ AI review failed: {error}")` via `gh`
  - All env var reads (`GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY`, `GITHUB_WEBHOOK_SECRET`) from `os.environ`

- [x] T008 [SYNC] [US1] Implement `src/webhook/server.py` — FastAPI app:
  - `app = FastAPI()`
  - `POST /webhook`: read raw body bytes, call `verify_signature()` → 401 if invalid; call `parse_event()` → 200 `{"status": "ignored", "reason": ...}` if None; call `await launch_run(...)` in background; return 200 `{"status": "accepted", "pr_key": ...}`
  - `GET /health`: return `{"status": "ok", "active_runs": len([t for t in _tasks.values() if not t.done()])}`
  - Read `GITHUB_WEBHOOK_SECRET` from env in startup; raise `RuntimeError` if missing

### Tests

- [x] T00 [P] [SYNC] [US1] Unit tests for `src/webhook/signature.py` in `tests/webhook/test_signature.py`: valid signature accepted; invalid signature rejected; missing header rejected; constant-time path exercised (parametrize over correct/tampered/empty bodies)

- [x] T01 [P] [ASYNC] [US1] Unit tests for `src/webhook/event_filter.py` in `tests/webhook/test_event_filter.py`: `opened` non-draft accepted; `opened` draft ignored; `synchronize` accepted; unknown action ignored; duplicate delivery ID ignored; dedup TTL eviction

- [x] T01 [SYNC] [US1] Unit tests for `src/webhook/runner.py` in `tests/webhook/test_runner.py`:
  - At-most-one-run invariant: second `launch_run()` for same PR cancels first task
  - Stop event set on cancellation: `_stop_flags[pr_key].is_set()` after cancel
  - Successful run: mock `run()` to return a `PipelineState` with `draft_comment="review text"`; assert `pr.create_issue_comment("review text")` called once; assert interim comment deleted **(FR-003 + FR-004)**
  - **Failure path (FR-005)**: mock `run()` to raise `RuntimeError("api error")`; assert `pr.create_issue_comment` called with error message; assert no review comment posted; assert interim comment deleted or updated
  - Cancelled run: mock `run()` to block until stop_event set; assert `CancelledError` swallowed, no error comment posted

**Checkpoint**: US1 fully functional. `POST /webhook` with a valid non-draft `opened` payload → interim "in progress" comment appears → pipeline runs (no HITL, no auto-post inside pipeline) → runner.py posts full review comment via installation token → interim comment deleted. `POST` with draft payload → 200 ignored. Duplicate delivery → 200 ignored. Exactly one comment appears on the PR.

---

## Phase 4: User Story 2 — GitHub App Installation (Priority: P2)

**Goal**: Repository owner installs the GitHub App; subsequent PRs auto-trigger; uninstalling stops triggers.

**Independent Test**: Install App on test repo → open PR → confirm review fires. Uninstall → open PR → confirm no review. (Manual verification per quickstart.md; code already handles this via `installation.id` in each payload.)

### Implementation

- [x] T01 [ASYNC] [US2] Add `installation` webhook event type handling to `src/webhook/server.py`: if `X-GitHub-Event` is `"installation"` or `"installation_repositories"`, return `200 {"status": "ignored", "reason": "installation event — no action needed"}`. This prevents 422 errors in GitHub's delivery log when the App is installed/uninstalled.

- [x] T01 [ASYNC] [US2] Verify `GET /health` from T008 reports `active_runs` correctly; add a test in `tests/webhook/test_server.py` that patches `_tasks` with one done + one running task and asserts `active_runs == 1`

**Checkpoint**: GitHub App can be installed and uninstalled without webhook errors. `/health` accurately reflects in-flight runs.

---

## Phase 5: User Story 3 — Repository Configuration Management (Priority: P3)

**Goal**: Operator can limit which repositories trigger the pipeline via configuration; changes take effect without restart.

**Independent Test**: Set `ALLOWED_REPOS=owner/repo1` in env → PR on `owner/repo2` returns `200 ignored` → PR on `owner/repo1` triggers pipeline.

### Implementation

- [x] T01 [ASYNC] [US3] Add optional `ALLOWED_REPOS` env var support to `src/webhook/event_filter.py`: if `ALLOWED_REPOS` is set (comma-separated list of `owner/repo`), filter out events from repos not in the list. Return `None` with reason `"repo not in ALLOWED_REPOS"`. If `ALLOWED_REPOS` is unset, all installed repos are allowed (default). Read env var on each call so changes are picked up without restart (SC-005).

- [x] T01 [ASYNC] [US3] Unit tests for `ALLOWED_REPOS` filtering in `tests/webhook/test_event_filter.py`: allowed repo passes; non-allowed repo ignored; unset env var allows all repos

**Checkpoint**: All 3 user stories independently functional. Full pipeline: PR opened → webhook received → verified → filtered → pipeline run → comment posted.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [x] T01 [P] [ASYNC] Add `[pytest]` env var loading (via `pytest-dotenv` or fixture) to `tests/webhook/conftest.py` so tests can run with a `.env.test` containing dummy secrets without hitting real APIs
- [x] T01 [P] [ASYNC] Update module docstring in `src/pipeline.py` comment to reference this plan (`specs/004-github-app-trigger/plan.md`) alongside the existing reference
- [x] T01 [ASYNC] Run through `specs/004-github-app-trigger/quickstart.md` end-to-end with ngrok and a real GitHub App installation; update any steps that don't work as written
- [x] T01 [P] [ASYNC] Add structured logging (Python `logging` module, INFO level) to `src/webhook/server.py` and `src/webhook/runner.py`: log `delivery_id`, `pr_key`, `action`, and run status (`accepted`/`ignored`/`cancelled`/`completed`/`failed`) on every event processed and every state transition **(Constitution Principle 2 — Observability)**

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately; T002 and T003 run in parallel
- **Phase 2 (Foundational)**: Depends on Phase 1 — **BLOCKS all user story work**
- **Phase 3 (US1)**: Depends on Phase 2 — T005 and T006 run in parallel; T007 depends on T004 (pipeline.py change); T008 depends on T005, T006, T007; tests T009 and T010 run in parallel after their targets
- **Phase 4 (US2)**: Depends on T008 (server.py) — T012 and T013 can run in parallel
- **Phase 5 (US3)**: Depends on T006 (event_filter.py) — T014 and T015 run in parallel
- **Phase 6 (Polish)**: Depends on all phases complete

### User Story Dependencies

- **US1 (P1)**: Depends on Foundational (T004) — core flow
- **US2 (P2)**: Depends on US1 — extends the server already built
- **US3 (P3)**: Depends on US1 (event_filter.py) — adds filtering on top of existing filter logic

### Within US1

```
T004 (pipeline.py)
     │
     ├── T005 [P] (signature.py) ─────┐
     ├── T006 [P] (event_filter.py) ──┤
     └── T007 (runner.py) ────────────┤
                                       ▼
                                  T008 (server.py)
                                       │
                              ┌────────┴────────┐
                         T009 [P]          T010 [P]
                     (test_signature)  (test_event_filter)
                                       T011 (test_runner)
```

---

## Parallel Execution Examples

### Phase 3 — US1 parallelizable tasks

```bash
# After T004 completes, launch T005, T006, T007 together:
Task T005: "Implement verify_signature() in src/webhook/signature.py"
Task T006: "Implement parse_event() in src/webhook/event_filter.py"
Task T007: "Implement launch_run() + _run_task() in src/webhook/runner.py"

# After T008 completes, launch T009, T010 together:
Task T009: "Unit tests in tests/webhook/test_signature.py"
Task T010: "Unit tests in tests/webhook/test_event_filter.py"
```

---

## Implementation Strategy

### MVP (User Story 1 only — recommended first milestone)

1. Complete Phase 1: Setup (T001–T003)
2. Complete Phase 2: Foundational (T004) — **review before proceeding**
3. Complete Phase 3: US1 (T005–T011)
4. **STOP and VALIDATE**: Run quickstart.md, open a real PR, confirm end-to-end flow
5. Demo-ready: automated PR review fires without any manual command

### Incremental Delivery

- US1 complete → working webhook integration (demo-ready)
- US1 + US2 → clean install/uninstall behaviour + health endpoint
- US1 + US2 + US3 → multi-repo with `ALLOWED_REPOS` configuration

---

## Notes

- [P] tasks operate on different files — safe to run in parallel
- T004 is the highest-risk task: it modifies the existing CLI pipeline. Human review required before any webhook code is written.
- T005 (signature verification) is security-critical: wrong implementation enables webhook spoofing
- T007 (runner.py) is concurrency-critical: the at-most-one-run invariant must hold
- GitHub App credentials (`GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY`) are never committed — env vars or secret manager only
- **Token strategy**: `get_pr_metadata()` continues to use `GITHUB_TOKEN` (PAT) for reading PR data — this is fine. `post_pr_comment()` is NOT called in the automated path (`skip_hitl=True`). Runner.py posts the review comment using the installation token via `pr.create_issue_comment()` on the `gh` client. No changes to `src/tools/github.py` are needed.
