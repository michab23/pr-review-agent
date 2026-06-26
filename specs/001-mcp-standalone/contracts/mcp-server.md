# Contract: Team Brain MCP Server (HTTP/SSE)

## Endpoint

```
GET/POST http://<host>:<port>/sse
```

Default: `http://127.0.0.1:8000/sse`

## Tool: get_team_standards

**Input**
```json
{
  "topics": ["security", "python", "testing", "git"]
}
```
- `topics`: array of strings; each must match a standards file name (without `.md`)
- Valid values: `"security"`, `"python"`, `"testing"`, `"git"`

**Output**
```json
["<content of security.md>", "<content of python.md>"]
```
- Array of strings, one entry per matched topic
- Unrecognised topics are silently skipped (no error)

## Startup Command

```bash
uv run python -m src.team_brain.server
```

Server is ready when it prints:
```
Starting MCP server 'team-brain' with transport 'sse'
```

## Configuration

| Env Var | Default | Effect |
|---|---|---|
| `FASTMCP_HOST` | `127.0.0.1` | Bind address |
| `FASTMCP_PORT` | `8000` | Bind port |
| `FASTMCP_TRANSPORT` | `sse` | Transport (sse / stdio / http) |

## Client Configuration

The pipeline client reads `TEAM_BRAIN_URL` (default `http://127.0.0.1:8000/sse`).
If the server is unreachable, the client falls back to direct file reads and prints a warning.
