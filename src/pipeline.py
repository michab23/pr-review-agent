# Pipeline entry point — see specs/003-agent-independence/plan.md for agent wiring, HITL, and graceful-degradation behavior
import json
import select
import sys
from uuid import uuid4

from dotenv import load_dotenv
from langfuse import get_client, observe
from rich.console import Console
from rich.panel import Panel

try:
    from src.agents.analyzer import RISK_MODEL_MAP as _RISK_MODEL_MAP, analyzer_agent
except ImportError:
    _RISK_MODEL_MAP = None
    analyzer_agent = None

try:
    from src.agents.reviewer import reviewer_agent
except ImportError:
    reviewer_agent = None

try:
    from src.agents.reporter import reporter_agent
except ImportError:
    reporter_agent = None

from src.models import ChangeType, PRClassification, PipelineState, ReviewFindings, RiskLevel
from src.tools.github import get_pr_metadata, post_pr_comment, validate_diff
from src.tools.team_brain import get_team_standards
from src.tools.trace import log_structured_trace
from src.utils import extract_json as _extract_json, setup_langfuse_tracing

load_dotenv()

console = Console()
langfuse = get_client()

HITL_TIMEOUT_SECONDS = 60


_JSON_RETRY_SUFFIX = (
    "\n\nCRITICAL: Your entire response must be a single valid JSON object. "
    "No markdown fences, no prose, no explanation — just the JSON."
)


def _run_agent_json(agent, prompt: str, name: str):
    """Run agent and extract JSON from string content, retrying once on parse failure."""
    result = agent.run(prompt)
    content = result.content
    if not isinstance(content, str):
        return content
    try:
        return _extract_json(content)
    except ValueError:
        retry = agent.run(prompt + _JSON_RETRY_SUFFIX)
        content = retry.content
        if not isinstance(content, str):
            return content
        try:
            return _extract_json(content)
        except ValueError as exc:
            raise ValueError(f"[{name}] failed to return valid JSON after retry: {exc}") from exc


_FALLBACK_CLASSIFICATION = PRClassification(
    risk_level=RiskLevel.MEDIUM,
    change_types=[ChangeType.FEATURE],
    risk_rationale="Analyzer unavailable — defaulting to medium risk",
    model_to_use="anthropic/claude-sonnet-4-6",
    files_of_concern=[],
)

_FALLBACK_FINDINGS = ReviewFindings(
    summary="Reviewer unavailable — automated review could not be completed.",
    findings=[],
    verdict="comment",
    confidence=0.0,
)


def _reporter_fallback(findings: ReviewFindings) -> str:
    return (
        "## ⚠️ Reporter Unavailable\n\n"
        "The Reporter agent failed. Raw findings are shown below.\n\n"
        f"```json\n{findings.model_dump_json(indent=2)}\n```"
    )


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
        metadata = None
        try:
            metadata = get_pr_metadata(pr_url)
            metadata = metadata.model_copy(update={"diff": validate_diff(metadata.diff)})
            if analyzer_agent is None:
                raise ImportError("analyzer module not available")
            raw = _run_agent_json(analyzer_agent, str(metadata.model_dump()), "analyzer")
            classification = raw if not isinstance(raw, str) else PRClassification.model_validate_json(raw)
        except Exception as exc:
            if metadata is None:
                raise
            console.print(f"[yellow]⚠ Analyzer unavailable ({exc}); using medium-risk fallback.[/yellow]")
            classification = _FALLBACK_CLASSIFICATION
            state.degraded = True
            state.agents_failed.append("analyzer")
        state.metadata = metadata
        state.classification = classification

        # Agent 2: Reviewer — model tier resolved from risk level at runtime
        try:
            from agno.models.litellm import LiteLLM
            risk_map = _RISK_MODEL_MAP or {
                "low": "anthropic/claude-haiku-4-5-20251001",
                "medium": "anthropic/claude-sonnet-4-6",
                "high": "anthropic/claude-opus-4-8",
            }
            model_id = risk_map[state.classification.risk_level.value]
            if reviewer_agent is None:
                raise ImportError("reviewer module not available")
            reviewer_agent.model = LiteLLM(id=model_id, top_p=None, temperature=1)
            # Pre-fetch standards so reviewer gets them in-prompt (avoids Agno tool-call conflicts
            # between output_schema structured-output machinery and user-registered tools).
            topics = {t for ct in state.classification.change_types
                      for t in _CHANGE_TYPE_TOPICS.get(ct.value, [])}
            standards = get_team_standards(sorted(topics)) if topics else []
            standards_text = "\n\n---\n\n".join(standards) if standards else "(none)"
            raw_findings = _run_agent_json(
                reviewer_agent,
                f"Metadata: {state.metadata.model_dump_json()}\n"
                f"Classification: {state.classification.model_dump_json()}\n"
                f"Applicable Standards:\n{standards_text}",
                "reviewer",
            )
            findings = raw_findings if not isinstance(raw_findings, str) else ReviewFindings.model_validate_json(raw_findings)
        except Exception as exc:
            console.print(f"[yellow]⚠ Reviewer unavailable ({exc}); using placeholder findings.[/yellow]")
            findings = _FALLBACK_FINDINGS
            state.degraded = True
            if "reviewer" not in state.agents_failed:
                state.agents_failed.append("reviewer")
        state.findings = findings

        # Agent 3: Reporter — produces draft comment
        try:
            if reporter_agent is None:
                raise ImportError("reporter module not available")
            draft_result = reporter_agent.run(
                f"Metadata: {state.metadata.model_dump_json()}\n"
                f"Findings: {state.findings.model_dump_json()}\n"
                f"Run ID: {state.run_id}\n"
                f"Cost USD: {state.total_cost_usd:.4f}"
            )
            state.draft_comment = draft_result.content
        except Exception as exc:
            console.print(f"[yellow]⚠ Reporter unavailable ({exc}); showing raw findings.[/yellow]")
            state.draft_comment = _reporter_fallback(state.findings)
            state.degraded = True
            if "reporter" not in state.agents_failed:
                state.agents_failed.append("reporter")

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
