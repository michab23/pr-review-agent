# Team Brain MCP client — calls the FastMCP server via stdio subprocess using the mcp SDK.
# ADR-002: stdio transport chosen; mcp SDK handles JSON-RPC handshake and tool calls.
import asyncio
import json
from pathlib import Path

_STANDARDS_DIR = Path(__file__).parent.parent / "team_brain" / "standards"
_SERVER_MODULE = "src.team_brain.server"


def get_team_standards(topics: list[str]) -> list[str]:
    """Retrieve coding standard excerpts from the Team Brain MCP server.

    Topics map to standards files: 'security', 'python', 'testing', 'git'.
    Returns a list of standard file contents, one entry per matched topic.
    """
    try:
        return asyncio.run(_fetch_via_mcp(topics))
    except Exception:
        # Fall back to direct file read if MCP subprocess fails (e.g., import errors during dev)
        return _fetch_direct(topics)


async def _fetch_via_mcp(topics: list[str]) -> list[str]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command="python",
        args=["-m", _SERVER_MODULE],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("get_team_standards", {"topics": topics})
            if not result.content:
                return []
            raw = result.content[0].text
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return [raw] if raw else []


def _fetch_direct(topics: list[str]) -> list[str]:
    """Direct file read fallback — bypasses MCP protocol, used only if subprocess fails."""
    results = []
    for topic in topics:
        path = _STANDARDS_DIR / f"{topic}.md"
        if path.exists():
            results.append(path.read_text())
    return results
