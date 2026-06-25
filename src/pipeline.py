# Pipeline entry point — see spec/spec.md §4 for full agent wiring and HITL behavior
import select
import sys
from uuid import uuid4

from dotenv import load_dotenv
from langfuse import get_client, observe
from rich.console import Console
from rich.panel import Panel

from src.agents.analyzer import RISK_MODEL_MAP, analyzer_agent
from src.agents.reporter import reporter_agent
from src.agents.reviewer import reviewer_agent
from src.models import PRClassification, PipelineState, ReviewFindings
from src.tools.github import get_pr_metadata, post_pr_comment, validate_diff
from src.tools.team_brain import get_team_standards
from src.tools.trace import log_structured_trace
from src.utils import setup_langfuse_tracing

load_dotenv()

console = Console()
langfuse = get_client()

HITL_TIMEOUT_SECONDS = 60


def _extract_json(text: str) -> str:
    """Extract the outermost JSON object from text, ignoring code-fence markers."""
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text.strip()

_CHANGE_TYPE_TOPICS = {
    "feature": ["python", "testing"],
    "bug_fix": ["python", "testing"],
    "refactor": ["python"],
    "security": ["security", "python"],
    "docs": [],
    "config": ["git"],
    "dependency": ["security"],
}


def human_approval_gate(state: PipelineState) -> bool:
    console.print(Panel(state.draft_comment, title="DRAFT REVIEW COMMENT", border_style="yellow"))
    console.print(f"\nPost this comment to PR #{state.metadata.pr_number}? [y/n] ", end="")

    ready, _, _ = select.select([sys.stdin], [], [], HITL_TIMEOUT_SECONDS)
    if not ready:
        console.print("\n[yellow]Timeout — treating as abort.[/yellow]")
        return False

    answer = sys.stdin.readline().strip().lower()
    return answer == "y"


@observe(name="pr_review_pipeline")
def run(pr_url: str) -> PipelineState:
    state = PipelineState(pr_url=pr_url, run_id=str(uuid4()))

    try:
        # Agent 1: Analyzer
        metadata = get_pr_metadata(pr_url)
        metadata = metadata.model_copy(update={"diff": validate_diff(metadata.diff)})
        result = analyzer_agent.run(str(metadata.model_dump()))
        state.metadata = metadata
        classification = result.content
        if isinstance(classification, str):
            classification = PRClassification.model_validate_json(_extract_json(classification))
        state.classification = classification

        # Agent 2: Reviewer — model resolved from risk level at runtime
        from agno.models.litellm import LiteLLM
        model_id = RISK_MODEL_MAP[state.classification.risk_level.value]
        reviewer_agent.model = LiteLLM(id=model_id, top_p=None, temperature=1)

        # Pre-fetch standards so reviewer gets them in-prompt (avoids Agno tool-call conflicts
        # between output_schema structured-output machinery and user-registered tools).
        topics = {t for ct in state.classification.change_types
                  for t in _CHANGE_TYPE_TOPICS.get(ct.value, [])}
        standards = get_team_standards(sorted(topics)) if topics else []
        standards_text = "\n\n---\n\n".join(standards) if standards else "(none)"

        findings_result = reviewer_agent.run(
            f"Metadata: {state.metadata.model_dump_json()}\n"
            f"Classification: {state.classification.model_dump_json()}\n"
            f"Applicable Standards:\n{standards_text}"
        )
        findings = findings_result.content
        if isinstance(findings, str):
            findings = ReviewFindings.model_validate_json(_extract_json(findings))
        state.findings = findings

        # Agent 3: Reporter — produces draft comment
        draft_result = reporter_agent.run(
            f"Metadata: {state.metadata.model_dump_json()}\n"
            f"Findings: {state.findings.model_dump_json()}\n"
            f"Run ID: {state.run_id}\n"
            f"Cost USD: {state.total_cost_usd:.4f}"
        )
        state.draft_comment = draft_result.content

        # HITL gate
        approved = human_approval_gate(state)
        try:
            langfuse.score_current_trace(name="human-approval", value=1 if approved else 0)
        except Exception:
            pass

        if not approved:
            state.human_approved = False
            log_structured_trace(state)
            console.print("[red]Aborted — nothing posted.[/red]")
            langfuse.flush()
            return state

        state.posted_comment_url = post_pr_comment(
            state.metadata.repo, state.metadata.pr_number, state.draft_comment
        )
        state.human_approved = True
        log_structured_trace(state)

        risk = state.classification.risk_level.value
        n = len(state.findings.findings)
        cost = state.total_cost_usd
        console.print(
            f"✓ Run {state.run_id} | Risk: {risk} | Findings: {n} | "
            f"Cost: ${cost:.4f} | Status: posted"
        )
        langfuse.flush()

    except Exception as e:
        state.error = str(e)
        log_structured_trace(state)
        langfuse.flush()
        raise

    return state


if __name__ == "__main__":
    if len(sys.argv) != 2:
        console.print("Usage: uv run python -m src.pipeline <github-pr-url>")
        sys.exit(1)
    setup_langfuse_tracing()
    try:
        run(sys.argv[1])
    except (RuntimeError, ValueError) as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Unexpected error:[/red] {e}")
        sys.exit(1)
