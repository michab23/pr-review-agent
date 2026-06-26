# Tasks: MCP Server Standalone Mode

**Input**: Design documents from `specs/001-mcp-standalone/`

**Branch**: `001-mcp-standalone` | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

## Format: `[ID] [P?] [SYNC/ASYNC] [Story?] Description`

- **[P]**: Can run in parallel with other [P] tasks in the same phase (different files, no dependencies)
- **[SYNC]**: Requires human review — complex logic, integration boundary, fallback behavior
- **[ASYNC]**: Can be delegated to async agent — well-defined, mechanical, content-driven
- **[USN]**: Maps to user story N from spec.md

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Document environment variable before any story work begins.

- [x] T001 [ASYNC] Add `TEAM_BRAIN_URL` variable to `.env.example` with default value `http://127.0.0.1:8000/sse` and a comment explaining its purpose

**Checkpoint**: Environment variable contract documented — ready to begin user stories.

---

## Phase 2: User Story 1 — Start Server Once, Review Many PRs (Priority: P1) 🎯 MVP

**Goal**: The MCP server can be started independently as a persistent HTTP/SSE process, and the pipeline connects to it — no subprocess spawned per call.

**Independent Test**: Start `uv run python -m src.team_brain.server` in one terminal. In a second terminal, run the pipeline twice against any PR URL. Both runs should complete and use the running server (no `_fetch_direct` fallback triggered).

### Implementation

- [x] T002 [P] [SYNC] [US1] Update `src/team_brain/server.py`: change the `__main__` block from `mcp.run(transport="stdio")` to `mcp.run(transport="sse")` — this is the standalone startup command
- [x] T003 [P] [SYNC] [US1] Update `src/tools/team_brain.py`: replace `_fetch_via_mcp` (stdio subprocess) with `_fetch_via_http` that connects to the SSE server at `TEAM_BRAIN_URL` env var (default `http://127.0.0.1:8000/sse`) using `mcp.client.sse.sse_client`; remove `StdioServerParameters`, `stdio_client`, and `_SERVER_MODULE`

> T002 and T003 touch different files — they can be executed in parallel.

**Checkpoint**: `uv run python -m src.team_brain.server` starts a persistent server. Pipeline connects to it via SSE. User Story 1 is independently testable.

---

## Phase 3: User Story 2 — Graceful Fallback When Server Is Down (Priority: P2)

**Goal**: When the MCP server is not running, the pipeline falls back to direct file reads and prints a visible warning — no unhandled exception.

**Independent Test**: With the server stopped, run the pipeline. Verify (a) the review completes, (b) a warning about the unreachable server is printed to stderr.

### Implementation

- [x] T004 [SYNC] [US2] Update `src/tools/team_brain.py`: in `get_team_standards`, wrap the `_fetch_via_http` call so that any `ConnectionRefusedError` or other connection exception triggers `_fetch_direct` AND prints a warning message to stderr (e.g. `Warning: Team Brain MCP server unreachable at {url} — falling back to direct file read`)

> T004 modifies the same file as T003 — must run after T003 completes.

**Checkpoint**: Pipeline completes a review even when server is down. Warning is visible. User Story 2 is independently testable.

---

## Phase 4: User Story 3 — Clear Developer Onboarding (Priority: P3)

**Goal**: The README clearly documents the two-terminal workflow so a new developer can start the server and run the pipeline in under 2 minutes.

**Independent Test**: Follow the README "Running" section only. Verify the server starts and the pipeline connects, with no prior knowledge of the codebase.

### Implementation

- [x] T005 [P] [ASYNC] [US3] Update `README.md`: add a "Team Brain MCP server" subsection under "Running" with the standalone start command, expected ready message, and two-terminal workflow — content is fully specified in [quickstart.md](quickstart.md)
- [x] T006 [P] [ASYNC] [US3] Update `pyproject.toml` and `src/team_brain/server.py`: add a `main()` function to `server.py` that calls `mcp.run(transport="sse")`; add `[project.scripts]` entry `team-brain = "src.team_brain.server:main"` to `pyproject.toml` so developers can use `uv run team-brain` as a short-form command

> T005 and T006 touch different files — they can be executed in parallel.

**Checkpoint**: README documents the two-terminal workflow. `uv run team-brain` works as a short-form server start. User Story 3 is independently testable.

---

## Phase 5: Polish & Cross-Cutting Concerns

**Purpose**: Final validation and any remaining cross-cutting updates.

- [x] T007 [ASYNC] Manual end-to-end validation: follow `specs/001-mcp-standalone/quickstart.md` exactly — start server, run pipeline twice, verify both runs succeed; stop server, run pipeline once, verify fallback warning appears and review still completes

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (US1)**: Can start after Phase 1 (T002 and T003 are parallel; both need T001 env var documented first)
- **Phase 3 (US2)**: Depends on Phase 2 completion — T004 extends T003's changes
- **Phase 4 (US3)**: Can start after Phase 2 completes (T005/T006 are parallel, independent of T004)
- **Phase 5 (Polish)**: Depends on all phases complete

### Task-Level Dependencies

```
T001
  └─> T002 [P]
  └─> T003 [P]
        └─> T004
              └─> T007
T002 ──────────────┘
T005 [P] (after T002, T003)
T006 [P] (after T002, T003)
T005, T006 ──> T007
```

### Parallel Opportunities

**Within Phase 2**: T002 and T003 can execute simultaneously (different files: `server.py` vs `team_brain.py`).

**Within Phase 4**: T005 and T006 can execute simultaneously (different files: `README.md` + `pyproject.toml` vs `server.py`).

```bash
# Phase 2 parallel launch:
Task T002: "Update src/team_brain/server.py transport"
Task T003: "Update src/tools/team_brain.py SSE client"

# Phase 4 parallel launch (after Phase 2 + 3 complete):
Task T005: "Update README.md two-terminal workflow"
Task T006: "Add pyproject.toml script entry"
```

---

## Implementation Strategy

### MVP First (User Story 1 — Phase 2 only)

1. Complete Phase 1: Setup (T001)
2. Complete Phase 2: User Story 1 (T002 + T003 in parallel)
3. **STOP and VALIDATE**: Start server, run pipeline twice, confirm both connect to server
4. Demo or ship if sufficient

### Incremental Delivery

1. Phase 1 → Phase 2 → Validate US1 (server works standalone)
2. Phase 3 → Validate US2 (fallback graceful when server is down)
3. Phase 4 → Validate US3 (README clear, short-form command works)
4. Phase 5 → Full end-to-end validation

---

## Notes

- T002 is a one-line change (`stdio` → `sse`) — simple but an integration boundary change
- T003 replaces the entire async function `_fetch_via_mcp`; keep `_fetch_direct` untouched
- T004 adds the warning print but must NOT change the fallback logic (still calls `_fetch_direct`)
- [P] tasks = different files, can run concurrently
- Commit after each phase checkpoint
