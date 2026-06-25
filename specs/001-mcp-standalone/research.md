# Research — MCP Server Standalone Mode

> Generated at the spec-plan stage. Records transport decisions, version findings, and design rationale.

---

## Transport Selection

| Decision | Choice | Rationale |
|---|---|---|
| Server transport | `sse` (HTTP Server-Sent Events) | Battle-tested, supported by all `mcp` SDK client versions; simpler URL scheme (`/sse`) |
| Client protocol | `mcp.client.sse.sse_client` | Confirmed available in installed `mcp` 3.4.2; connects to SSE endpoint by URL |
| Fallback | Direct file read (`_fetch_direct`) | Already exists; activated on any connection error |

**Alternatives considered**:
- `streamable-http` transport: Also available in FastMCP 3.4.2, exposes `/mcp`. Not chosen because SSE has wider compatibility and simpler client setup.
- Keeping `stdio`: Does not satisfy the requirement — a new subprocess is spawned per call and cannot remain always-on.

---

## Server Address Configuration

| Setting | Default | Override |
|---|---|---|
| Host | `127.0.0.1` | `FASTMCP_HOST` env var (FastMCP native) |
| Port | `8000` | `FASTMCP_PORT` env var (FastMCP native) |
| Full SSE URL | `http://127.0.0.1:8000/sse` | `TEAM_BRAIN_URL` env var in pipeline client |

FastMCP reads `FASTMCP_HOST`, `FASTMCP_PORT`, and `FASTMCP_TRANSPORT` natively from env vars — no custom arg parsing needed in the server module.

---

## Server Startup Strategy

The server module already has `if __name__ == "__main__": mcp.run(transport="stdio")`. Changing the default to `transport="sse"` makes `python -m src.team_brain.server` the standalone start command with no extra flags. The `FASTMCP_TRANSPORT` env var can override it if stdio mode is ever needed for tooling compatibility.

A convenience script entry in `pyproject.toml` (`team-brain = "src.team_brain.server:main"`) lets users run `uv run team-brain` instead of the module path, but is optional.

---

## Client Update Strategy

Current flow in `src/tools/team_brain.py`:
1. Try `_fetch_via_mcp` → spawns stdio subprocess → calls tool → returns results
2. On any exception → `_fetch_direct` (file read)

New flow:
1. Try `_fetch_via_http` → connects to running SSE server → calls tool → returns results
2. On `ConnectionRefusedError` / `httpx` error / any exception → `_fetch_direct` + print warning
3. Remove `_fetch_via_mcp` (stdio subprocess path) — no longer needed

The `TEAM_BRAIN_URL` env var (default `http://127.0.0.1:8000/sse`) allows the client to be pointed at a non-default host/port without code changes.

---

## Constitution Alignment

| Principle | Status |
|---|---|
| Simplicity First | The change is minimum-necessary: two files changed (server.py, team_brain.py), README updated |
| Stateless Services | Server remains stateless — no session state stored between requests |
| Observability | Fallback path prints a visible warning; existing LangFuse tracing unchanged |
| Dependency Injection | Server URL injected via env var, not hard-coded |

No constitution violations.
