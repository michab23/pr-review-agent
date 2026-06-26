# Implementation Plan: MCP Server Standalone Mode

**Branch**: `001-mcp-standalone` | **Date**: 2026-06-25 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/001-mcp-standalone/spec.md`

## Summary

Switch the Team Brain MCP server from ephemeral stdio subprocess mode (spawned per pipeline call) to a persistent HTTP/SSE server process with its own startup command. The pipeline client is updated to connect to the always-running server via SSE, with a graceful fallback to direct file reads when the server is unreachable.

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: FastMCP 3.4.2 (SSE transport), mcp SDK 3.4.2 (`sse_client`), uv
**Storage**: N/A — no data storage; standards are read from `src/team_brain/standards/*.md`
**Testing**: pytest (unit + integration)
**Target Platform**: Linux/macOS development machine
**Project Type**: CLI tool with embedded MCP server component
**Performance Goals**: Server starts in < 2 seconds; pipeline connection latency negligible (localhost)
**Constraints**: No new dependencies; uses only existing FastMCP/mcp SDK capabilities
**Scale/Scope**: Single developer session; one server instance, one client

## Constitution Check

| Principle | Status | Notes |
|---|---|---|
| Simplicity First | ✅ PASS | 2 source files changed + README; no new dependencies, no new abstractions |
| Stateless Services | ✅ PASS | Server remains stateless — no session state between requests |
| Observability | ✅ PASS | Fallback path emits a visible warning; LangFuse tracing unchanged |
| Tests Drive Confidence | ✅ PASS | Existing integration test updated; new unit test for fallback warning |
| Dependency Injection | ✅ PASS | Server URL injected via `TEAM_BRAIN_URL` env var |
| Surgical Changes | ✅ PASS | Only `server.py`, `team_brain.py`, README, and pyproject.toml touched |

No violations. No Complexity Tracking entries required.

## Project Structure

### Documentation (this feature)

```text
specs/001-mcp-standalone/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   └── mcp-server.md   # MCP server HTTP contract
└── tasks.md             # Phase 2 output (/spec-tasks — not yet created)
```

### Source Code (changes only)

```text
src/
├── team_brain/
│   └── server.py        # Change: default transport stdio → sse
└── tools/
    └── team_brain.py    # Change: stdio client → SSE HTTP client

README.md                # Change: add two-terminal workflow section
pyproject.toml           # Change (optional): add team-brain script entry
```

## Triage Framework: [SYNC] vs [ASYNC] Classification

**Execution Strategy**: Hybrid — architectural changes are [SYNC]; documentation and config are [ASYNC].

### Preliminary Task Classification

| Task Category | Estimated [SYNC] Tasks | Estimated [ASYNC] Tasks | Rationale |
|---|---|---|---|
| Server transport change | 1 | 0 | Architecture change at an integration boundary |
| Client transport change | 1 | 0 | Connectivity logic with fallback — requires careful error handling |
| README documentation | 0 | 1 | Well-defined content, no code logic |
| pyproject.toml script | 0 | 1 | Trivial config addition |

### Triage Decision Criteria Applied

**High-Risk [SYNC] Classifications:**
- Server transport change: external interface change; wrong transport leaves server unreachable
- Client transport change: fallback behavior is security/reliability critical; must not silently break

**Agent-Delegated [ASYNC] Classifications:**
- README update: content is fully specified in quickstart.md
- pyproject.toml script entry: mechanical one-liner addition

### Triage Audit Trail

| Task | Classification | Primary Criteria | Risk Level | Rationale |
|---|---|---|---|---|
| Update server.py default transport | [SYNC] | External integration point, architectural change | Medium | Changes how all consumers connect; wrong default breaks CI |
| Update team_brain.py client | [SYNC] | Connectivity logic + fallback error handling | Medium | Must distinguish connection errors from tool errors; fallback must not mask real failures |
| Update README | [ASYNC] | Documentation, content fully defined in quickstart.md | Low | No logic; copy from quickstart.md |
| Add pyproject.toml script | [ASYNC] | Config, one-line addition | Low | Well-defined pattern, no risk |

## Implementation Details

### Task 1 [SYNC]: Update `src/team_brain/server.py`

**Change**: Switch `__main__` block from `mcp.run(transport="stdio")` to `mcp.run(transport="sse")`.

FastMCP already reads `FASTMCP_TRANSPORT` env var natively, so operators can override to `stdio` for tooling that requires it. No custom argument parsing needed.

**Before**:
```python
if __name__ == "__main__":
    mcp.run(transport="stdio")
```

**After**:
```python
if __name__ == "__main__":
    mcp.run(transport="sse")
```

That single line change is the entire server update.

---

### Task 2 [SYNC]: Update `src/tools/team_brain.py`

**Change**: Replace `_fetch_via_mcp` (stdio subprocess) with `_fetch_via_http` (SSE client).

Key behaviours:
- Read server URL from `TEAM_BRAIN_URL` env var; default `http://127.0.0.1:8000/sse`
- On any connection error, fall back to `_fetch_direct` and print a warning to stderr
- Remove `StdioServerParameters`, `stdio_client`, `_SERVER_MODULE` — no longer needed

The public `get_team_standards` function signature is unchanged.

---

### Task 3 [ASYNC]: Update README

Add a "Running the MCP server" section before the "Production pipeline" section. Content is specified in [quickstart.md](quickstart.md).

---

### Task 4 [ASYNC]: Add pyproject.toml script entry (optional)

Add under `[project.scripts]`:
```toml
team-brain = "src.team_brain.server:main"
```

Requires adding a `main()` function to `server.py` that calls `mcp.run(transport="sse")`, enabling `uv run team-brain` as the short-form command.

This is optional — `uv run python -m src.team_brain.server` works without it.
