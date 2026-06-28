# Agent 3: Reporter — see spec/spec.md §3 for role, HITL behavior, and comment format
import json

from agno.agent import Agent
from agno.models.litellm import LiteLLM
from langfuse import get_client, observe

def _strip_preamble(content: str) -> str:
    """Drop any model preamble before the first markdown heading or horizontal rule."""
    for i, line in enumerate(content.splitlines()):
        stripped = line.strip()
        if stripped.startswith("#") or stripped == "---":
            return "\n".join(content.splitlines()[i:])
    return content


_FOOTER_MARKERS = ("run id", "langfuse", "### run metadata", "<sub>")


def _strip_footer(content: str) -> str:
    """Remove run-metadata footer lines the model appends despite instructions."""
    lines = content.splitlines()
    for i in range(len(lines) - 1, -1, -1):
        low = lines[i].strip().lower()
        if any(marker in low for marker in _FOOTER_MARKERS):
            lines = lines[:i]
        else:
            break
    return "\n".join(lines).rstrip()


REPORTER_SYSTEM_PROMPT = """\
You are a technical writer formatting a code review for a GitHub PR comment.

Given the review findings, produce a clear, structured markdown comment that:
1. Opens with a one-sentence verdict summary
2. Lists each finding with its severity, file, line range, issue, cited standard, and fix

Rules:
- Output ONLY the markdown comment — no preamble, no explanation before the first line of markdown
- Do NOT include run metadata, run IDs, cost figures, LangFuse trace links, or any footer section\
"""

reporter_agent = Agent(
    name="reporter",
    model=LiteLLM(id="anthropic/claude-sonnet-4-6", top_p=None, temperature=1),
    instructions=REPORTER_SYSTEM_PROMPT,
)


@observe(name="reporter")
def run_standalone(payload: dict) -> str:
    """Run the Reporter against {metadata, findings, run_id, cost_usd} payload; return formatted comment."""
    from src.models import PRMetadata, ReviewFindings
    metadata = PRMetadata.model_validate(payload["metadata"])
    findings = ReviewFindings.model_validate(payload["findings"])
    run_id = payload.get("run_id", "standalone")
    cost_usd = float(payload.get("cost_usd", 0.0))
    prompt = (
        f"Metadata: {metadata.model_dump_json()}\n"
        f"Findings: {findings.model_dump_json()}"
    )
    result = reporter_agent.run(prompt)
    content = result.content
    if isinstance(content, str):
        return _strip_footer(_strip_preamble(content))
    if isinstance(content, dict):
        return json.dumps(content, indent=2)
    if hasattr(content, "model_dump_json"):
        return content.model_dump_json(indent=2)
    raise TypeError(f"Unexpected reporter output type: {type(content).__name__}")


if __name__ == "__main__":
    import json
    import sys
    from dotenv import load_dotenv
    load_dotenv()
    tracing_enabled = False
    try:
        from src.utils import setup_langfuse_tracing
        setup_langfuse_tracing()
        tracing_enabled = True
    except RuntimeError:
        pass  # Langfuse env vars not set; run without tracing
    try:
        payload = json.load(sys.stdin)
        print(run_standalone(payload))
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        if tracing_enabled:
            get_client().flush()
