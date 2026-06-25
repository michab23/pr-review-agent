# Quickstart — MCP Server Standalone Mode

## Two-terminal workflow

**Terminal 1 — Start the MCP server (once)**

```bash
cd pr-review-agent
uv run python -m src.team_brain.server
```

The server is ready when you see:
```
Starting MCP server 'team-brain' with transport 'sse'
```

Leave this terminal running.

**Terminal 2 — Run the pipeline**

```bash
uv run python -m src.pipeline https://github.com/owner/repo/pull/123
```

The pipeline connects to the running server automatically.

---

## Optional: non-default address

Override server address (both terminals must agree):

```bash
# Terminal 1 — start server on custom port
FASTMCP_PORT=9000 uv run python -m src.team_brain.server

# Terminal 2 — point pipeline at custom address
TEAM_BRAIN_URL=http://127.0.0.1:9000/sse uv run python -m src.pipeline <pr-url>
```

---

## Running without the server

If the server is not running, the pipeline falls back to reading standards files directly and prints:

```
Warning: Team Brain MCP server unreachable — falling back to direct file read
```

The review still completes; team standards are loaded from disk instead of via MCP.
