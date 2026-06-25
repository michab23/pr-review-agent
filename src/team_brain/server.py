# Team Brain MCP server — see spec/spec.md §5 for transport and tool spec
from pathlib import Path

from fastmcp import FastMCP

mcp = FastMCP("team-brain")
STANDARDS_DIR = Path(__file__).parent / "standards"


@mcp.tool()
def get_team_standards(topics: list[str]) -> list[str]:
    """Retrieve coding standard excerpts relevant to the given topics.

    Topics map to standards files (e.g. 'security', 'python', 'testing', 'git').
    Returns the full content of each matched standards file.
    """
    results = []
    for topic in topics:
        path = STANDARDS_DIR / f"{topic}.md"
        if path.exists():
            results.append(path.read_text())
    return results


@mcp.resource("standards://all")
def get_all_standards() -> str:
    """Full text of all team coding standards."""
    return "\n\n---\n\n".join(p.read_text() for p in sorted(STANDARDS_DIR.glob("*.md")))


def main() -> None:
    mcp.run(transport="sse")


if __name__ == "__main__":
    main()
