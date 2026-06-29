# Pipeline entry point — see specs/004-github-app-trigger/plan.md for agent wiring, HITL, and graceful-degradation behavior
import json
import select
import sys
import threading
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

from src.constants import CHANGE_TYPE_TOPICS as _CHANGE_TYPE_TOPICS
from src.guardrails.validators import OutputValidator
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


def _reporter_fallback(findings: ReviewFindings) -> str:
    return (
        "## ⚠️ Reporter Unavailable\n\n"
        "The Reporter agent failed. Raw findings are shown below.\n\n"
        f"```json\n{findings.model_dump_json(indent=2)}\n```"
    )


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
def run(
    pr_url: str,
    *,
    skip_hitl: bool = False,
    stop_event: threading.Event | None = None,
) -> PipelineState:
    """Run the three-agent PR review pipeline.

    skip_hitl: when True, bypasses the human approval gate and skips
        post_pr_comment() — the caller (runner.py) is responsible for posting
        state.draft_comment via the GitHub App installation token.
    stop_event: cooperative cancellation flag checked after each agent block;
        sets state.error='cancelled' and returns early when set.
    """
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
            if isinstance(raw, str):
                classification = PRClassification.model_validate_json(raw)
            elif isinstance(raw, dict):
                classification = PRClassification.model_validate(raw)
            elif isinstance(raw, PRClassification):
                classification = raw
            else:
                raise TypeError(f"Unexpected analyzer output type: {type(raw).__name__}")
        except Exception as exc:
            if metadata is None:
                raise
            console.print(f"[yellow]⚠ Analyzer unavailable ({exc}); using medium-risk fallback.[/yellow]")
            classification = _FALLBACK_CLASSIFICATION
            state.degraded = True
            state.agents_failed.append("analyzer")
        state.metadata = metadata
        state.classification = classification
        if stop_event and stop_event.is_set():
            state.error = "cancelled"
            return state

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
            if isinstance(raw_findings, str):
                data = json.loads(raw_findings)
            elif isinstance(raw_findings, dict):
                data = raw_findings
            elif isinstance(raw_findings, ReviewFindings):
                data = raw_findings.model_dump()
            else:
                raise TypeError(f"Unexpected reviewer output type: {type(raw_findings).__name__}")
            findings = ReviewFindings.model_validate(OutputValidator.clamp_confidence(data))
        except Exception as exc:
            console.print(f"[yellow]⚠ Reviewer unavailable ({exc}); using placeholder findings.[/yellow]")
            findings = _FALLBACK_FINDINGS
            state.degraded = True
            if "reviewer" not in state.agents_failed:
                state.agents_failed.append("reviewer")
        state.findings = findings
        if stop_event and stop_event.is_set():
            state.error = "cancelled"
            return state

        # Agent 3: Reporter — produces draft comment
        try:
            if reporter_agent is None:
                raise ImportError("reporter module not available")
            draft_result = reporter_agent.run(
                f"Metadata: {state.metadata.model_dump_json()}\n"
                f"Findings: {state.findings.model_dump_json()}"
            )
            content = draft_result.content
            if not isinstance(content, str):
                raise TypeError(f"Reporter returned {type(content).__name__} instead of markdown string")
            state.draft_comment = _strip_footer(_strip_preamble(content))
        except Exception as exc:
            console.print(f"[yellow]⚠ Reporter unavailable ({exc}); showing raw findings.[/yellow]")
            state.draft_comment = _reporter_fallback(state.findings)
            state.degraded = True
            if "reporter" not in state.agents_failed:
                state.agents_failed.append("reporter")

        if stop_event and stop_event.is_set():
            state.error = "cancelled"
            return state

        # HITL gate (CLI path only; bypassed when skip_hitl=True)
        if not skip_hitl:
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
        else:
            # Automated path: skip HITL and skip posting.
            # Caller (runner.py) posts draft_comment via the GitHub App installation token.
            state.human_approved = True
            log_structured_trace(state)

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
