# Data Model — MCP Server Standalone Mode

> This feature changes the *deployment model* of the MCP server and its client, not the data schema. No new Pydantic models are introduced.

---

## Changed Entities

### MCP Server (src/team_brain/server.py)

**Before**: Ephemeral stdio subprocess. Spawned per call by the pipeline client. Lifetime: duration of one `get_team_standards` invocation.

**After**: Persistent HTTP (SSE) server process. Started independently by the developer. Lifetime: until manually stopped.

| Attribute | Before | After |
|---|---|---|
| Transport | `stdio` | `sse` (HTTP SSE) |
| Process lifecycle | Spawned and torn down per call | Long-lived, always-on |
| Startup command | None (spawned internally) | `uv run python -m src.team_brain.server` |
| Endpoint | N/A (pipe) | `http://127.0.0.1:8000/sse` |
| Config | Hard-coded stdio | `FASTMCP_HOST`, `FASTMCP_PORT` env vars |

### Team Brain Client (src/tools/team_brain.py)

**Before**: Spawns a stdio subprocess, communicates over pipes, tears down after each call.

**After**: HTTP client that connects to the running SSE server. Falls back to direct file read on connection failure.

| Attribute | Before | After |
|---|---|---|
| Connection method | `StdioServerParameters` + `stdio_client` | `sse_client(url)` |
| Server address | N/A | `TEAM_BRAIN_URL` env var (default `http://127.0.0.1:8000/sse`) |
| Fallback trigger | Any exception | `ConnectionRefusedError` / HTTP error / any exception |
| Fallback behavior | Silent file read | File read + user warning printed |

---

## Environment Variables

| Variable | Component | Default | Purpose |
|---|---|---|---|
| `TEAM_BRAIN_URL` | Pipeline client | `http://127.0.0.1:8000/sse` | SSE endpoint URL for the running MCP server |
| `FASTMCP_HOST` | MCP server | `127.0.0.1` | Bind host for the HTTP server |
| `FASTMCP_PORT` | MCP server | `8000` | Bind port for the HTTP server |
| `FASTMCP_TRANSPORT` | MCP server | `sse` (after change) | Transport mode override (allows stdio for tooling) |
