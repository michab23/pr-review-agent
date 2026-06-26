# Team Brain MCP client — connects to the standalone SSE server via the mcp SDK.
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

_STANDARDS_DIR = Path(__file__).parent.parent / "team_brain" / "standards"
_DEFAULT_URL = "http://127.0.0.1:8000/sse"


def get_team_standards(topics: list[str]) -> list[str]:
    """Retrieve coding standard excerpts from the Team Brain MCP server.

    Topics map to standards files: 'security', 'python', 'testing', 'git'.
    Returns a list of standard file contents, one entry per matched topic.
    """
    try:
        return asyncio.run(_fetch_via_http(topics))
    except (OSError, httpx.NetworkError, httpx.TimeoutException) as exc:
        url = os.environ.get("TEAM_BRAIN_URL", _DEFAULT_URL)
        print(
            f"Warning: Team Brain MCP server unreachable at {url} — falling back to direct file read ({exc})",
            file=sys.stderr,
        )
        return _fetch_direct(topics)


async def _fetch_via_http(topics: list[str]) -> list[str]:
    from mcp import ClientSession
    from mcp.client.sse import sse_client

    url = os.environ.get("TEAM_BRAIN_URL", _DEFAULT_URL)
    async with sse_client(url) as (read, write):
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
    """Direct file read fallback — bypasses MCP protocol, used only if server is unreachable."""
    results = []
    for topic in topics:
        path = _STANDARDS_DIR / f"{topic}.md"
        if path.exists():
            results.append(path.read_text())
    return results
