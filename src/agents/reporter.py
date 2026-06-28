# Agent 3: Reporter — see spec/spec.md §3 for role, HITL behavior, and comment format
import json

from agno.agent import Agent
from agno.models.litellm import LiteLLM
from langfuse import get_client, observe
from src.utils import configure_model_backend, setup_langfuse_tracing

REPORTER_SYSTEM_PROMPT = """\
You are a technical writer formatting a code review for a GitHub PR comment.

Given the review findings, produce a clear, structured markdown comment that:
1. Opens with a one-sentence verdict summary
2. Lists each finding with its severity, file, line range, issue, cited standard, and fix
3. Closes with run metadata (run ID, cost, LangFuse trace link)

Follow the comment template in spec/data-model.md exactly.\
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
        f"Findings: {findings.model_dump_json()}\n"
        f"Run ID: {run_id}\n"
        f"Cost USD: {cost_usd:.4f}"
    )
    result = reporter_agent.run(prompt)
    content = result.content
    if isinstance(content, str):
        return content
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
    configure_model_backend()
    tracing_enabled = False
    try:
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
