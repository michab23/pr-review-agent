"""
Demo script for the Agentic PR Review Pipeline.

Offline mode (default): runs the 3-agent pipeline against a canned high-risk dataset
entry — no GitHub token required, nothing is posted.

Live mode: runs against a real GitHub PR URL.
  uv run python demo.py --live https://github.com/owner/repo/pull/N

In both modes the HITL gate is skipped; the draft comment is printed but not posted.
"""
import argparse
import json
import sys
import time
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

load_dotenv()

console = Console()

DATASET_DIR = Path(__file__).parent / "evals" / "dataset"


# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------

BANNER = """
╔══════════════════════════════════════════════════════════════╗
║          Agentic PR Review Pipeline — Team 4 Demo           ║
║   Najeeb · Amir · Erez · Avichay · Michael  |  June 2026   ║
╚══════════════════════════════════════════════════════════════╝
"""

ARCHITECTURE = """\
 ┌─────────────────────────────────────────────────────────────┐
 │                      GitHub PR URL                         │
 └────────────────────────┬────────────────────────────────────┘
                          │  get_pr_metadata()
                          ▼
 ┌─────────────────────────────────────────────────────────────┐
 │  AGENT 1 · Analyzer  [Haiku]                               │
 │  Input : PR diff + metadata                                │
 │  Output: PRClassification (risk=low/medium/high)           │
 │  Action: routes model tier for Reviewer                    │
 └────────────────────────┬────────────────────────────────────┘
                          │  risk → model selection
                          ▼
 ┌─────────────────────────────────────────────────────────────┐
 │  AGENT 2 · Reviewer  [Haiku | Sonnet | Opus by risk]       │
 │  Tool  : get_team_standards(topics) via Team Brain MCP     │
 │  Input : diff + classification                             │
 │  Output: ReviewFindings (findings + verdict)               │
 │  Self-review: validates file paths and cited standards     │
 └────────────────────────┬────────────────────────────────────┘
                          │  findings
                          ▼
 ┌─────────────────────────────────────────────────────────────┐
 │  AGENT 3 · Reporter  [Sonnet]                              │
 │  Input : findings                                          │
 │  Output: Formatted GitHub markdown comment                 │
 └────────────────────────┬────────────────────────────────────┘
                          │
                          ▼
 ┌─────────────────────────────────────────────────────────────┐
 │  HITL Gate  (human approval — skipped in demo)             │
 └────────────────────────┬────────────────────────────────────┘
                          │  post_pr_comment()
                          ▼
                    GitHub PR comment
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _risk_color(risk: str) -> str:
    return {"low": "green", "medium": "yellow", "high": "red"}.get(risk, "white")


def _verdict_color(verdict: str) -> str:
    return {"approve": "green", "request_changes": "red", "comment": "yellow"}.get(verdict, "white")


def _load_offline_pr():
    """Return (PRMetadata, dataset_entry) for the high-003 SQL-injection example."""
    from src.models import PRMetadata

    path = DATASET_DIR / "high-003-sql-injection.json"
    entry = json.loads(path.read_text())
    meta = PRMetadata(
        url="https://github.com/acme/demo-repo/pull/42",
        repo="acme/demo-repo",
        pr_number=42,
        title=entry["description"],
        description="",
        diff=entry["pr_diff"],
        files_changed=entry["files_changed"],
        lines_added=entry["pr_diff"].count("\n+"),
        lines_removed=entry["pr_diff"].count("\n-"),
    )
    return meta, entry


# ---------------------------------------------------------------------------
# Step renderers
# ---------------------------------------------------------------------------

def _show_pr(meta, *, offline: bool):
    mode_tag = "[dim](offline dataset)[/dim]" if offline else ""
    console.print(Panel(
        f"[bold]{meta.title}[/bold]\n"
        f"Repo: [cyan]{meta.repo}[/cyan]  PR: [cyan]#{meta.pr_number}[/cyan]  {mode_tag}\n"
        f"Files: {', '.join(meta.files_changed)}\n"
        f"+{meta.lines_added} / -{meta.lines_removed} lines",
        title="PR Under Review",
        border_style="blue",
    ))


def _show_classification(classification, elapsed: float):
    risk = classification.risk_level.value
    color = _risk_color(risk)
    t = Table.grid(padding=(0, 2))
    t.add_column(style="dim")
    t.add_column()
    t.add_row("Risk level:", f"[bold {color}]{risk.upper()}[/bold {color}]")
    t.add_row("Change types:", ", ".join(c.value for c in classification.change_types))
    t.add_row("Model selected:", classification.model_to_use)
    t.add_row("Files of concern:", ", ".join(classification.files_of_concern) or "—")
    t.add_row("Rationale:", classification.risk_rationale)
    t.add_row("Elapsed:", f"{elapsed:.1f}s")
    console.print(Panel(t, title="Agent 1 · Analyzer", border_style=color))


def _show_findings(findings, elapsed: float):
    verdict = findings.verdict
    color = _verdict_color(verdict)

    t = Table("Severity", "File", "Issue", "Standard", box=None, padding=(0, 1))
    severity_colors = {"critical": "red", "warning": "yellow", "suggestion": "cyan"}
    for f in findings.findings:
        sc = severity_colors.get(f.severity, "white")
        t.add_row(
            f"[{sc}]{f.severity}[/{sc}]",
            f.file,
            f.issue,
            f.standard_cited or "—",
        )

    summary_panel = Panel(
        f"[bold]Summary:[/bold] {findings.summary}\n"
        f"[bold]Verdict:[/bold] [{color}]{verdict}[/{color}]  "
        f"[bold]Confidence:[/bold] {findings.confidence:.0%}  "
        f"[bold]Findings:[/bold] {len(findings.findings)}  "
        f"[bold]Elapsed:[/bold] {elapsed:.1f}s",
        title="Agent 2 · Reviewer",
        border_style=color,
    )
    console.print(summary_panel)
    if findings.findings:
        console.print(t)
        console.print()


def _show_draft(draft: str, elapsed: float):
    console.print(Panel(
        draft,
        title=f"Agent 3 · Reporter — Draft Comment  ({elapsed:.1f}s)",
        border_style="magenta",
    ))
    console.print("[dim italic]HITL gate skipped in demo — nothing posted to GitHub.[/dim italic]\n")


def _show_summary(state, total_elapsed: float):
    risk = state.classification.risk_level.value if state.classification else "—"
    n = len(state.findings.findings) if state.findings else 0
    verdict = state.findings.verdict if state.findings else "—"
    console.print(Rule("Run Summary"))
    t = Table.grid(padding=(0, 2))
    t.add_column(style="dim")
    t.add_column()
    t.add_row("Run ID:", state.run_id)
    t.add_row("Risk:", f"[{_risk_color(risk)}]{risk.upper()}[/{_risk_color(risk)}]")
    t.add_row("Verdict:", f"[{_verdict_color(verdict)}]{verdict}[/{_verdict_color(verdict)}]")
    t.add_row("Findings:", str(n))
    t.add_row("Total time:", f"{total_elapsed:.1f}s")
    console.print(t)


# ---------------------------------------------------------------------------
# Main demo runner
# ---------------------------------------------------------------------------

def run_demo(pr_url: str | None = None) -> None:
    offline = pr_url is None

    console.print(BANNER, style="bold cyan")
    console.print(Panel(ARCHITECTURE, title="Architecture", border_style="dim"))

    # ── Load PR ──────────────────────────────────────────────────────────────
    if offline:
        meta, _ = _load_offline_pr()
    else:
        console.print(f"\n[bold]Fetching PR metadata from GitHub…[/bold] {pr_url}")
        from src.tools.github import get_pr_metadata, validate_diff
        meta = get_pr_metadata(pr_url)
        meta = meta.model_copy(update={"diff": validate_diff(meta.diff)})

    _show_pr(meta, offline=offline)

    from src.agents.analyzer import RISK_MODEL_MAP, analyzer_agent
    from src.agents.reviewer import reviewer_agent
    from src.agents.reporter import reporter_agent
    from src.models import PRClassification, PipelineState, ReviewFindings
    from src.tools.github import validate_diff

    if offline:
        diff = validate_diff(meta.diff)
        meta = meta.model_copy(update={"diff": diff})

    state = PipelineState(pr_url=meta.url, run_id=str(uuid4()))
    state.metadata = meta
    total_start = time.perf_counter()

    # ── Agent 1: Analyzer ────────────────────────────────────────────────────
    console.print("\n[bold dim]▶ Running Agent 1 · Analyzer…[/bold dim]")
    t0 = time.perf_counter()
    result = analyzer_agent.run(str(meta.model_dump()))
    classification = result.content
    if isinstance(classification, str):
        classification = PRClassification.model_validate_json(classification)
    state.classification = classification
    _show_classification(classification, time.perf_counter() - t0)

    # ── Agent 2: Reviewer ────────────────────────────────────────────────────
    from agno.models.litellm import LiteLLM
    model_id = RISK_MODEL_MAP[classification.risk_level.value]
    reviewer_agent.model = LiteLLM(id=model_id, top_p=None)

    console.print(f"\n[bold dim]▶ Running Agent 2 · Reviewer  [{model_id}]…[/bold dim]")
    t0 = time.perf_counter()
    findings_result = reviewer_agent.run(
        f"Metadata: {meta.model_dump_json()}\n"
        f"Classification: {classification.model_dump_json()}"
    )
    findings = findings_result.content
    if isinstance(findings, str):
        findings = ReviewFindings.model_validate_json(findings)
    state.findings = findings
    _show_findings(findings, time.perf_counter() - t0)

    # ── Agent 3: Reporter ────────────────────────────────────────────────────
    console.print("[bold dim]▶ Running Agent 3 · Reporter…[/bold dim]")
    t0 = time.perf_counter()
    draft_result = reporter_agent.run(
        f"Metadata: {meta.model_dump_json()}\n"
        f"Findings: {findings.model_dump_json()}"
    )
    state.draft_comment = draft_result.content
    _show_draft(state.draft_comment, time.perf_counter() - t0)

    _show_summary(state, time.perf_counter() - total_start)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PR Review Agent demo")
    parser.add_argument(
        "--live",
        metavar="PR_URL",
        default=None,
        help="Run against a real GitHub PR URL (requires GITHUB_TOKEN in .env)",
    )
    args = parser.parse_args()

    try:
        run_demo(pr_url=args.live)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        sys.exit(0)
    except Exception as e:
        console.print(f"\n[red]Error:[/red] {e}")
        raise
