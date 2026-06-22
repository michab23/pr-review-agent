# Software Design Document — Agentic PR Review Pipeline

> Generated from `mission-brief.md`. This is the engineering contract. Fix the spec before fixing code.

---

## 1. System Overview

The Agentic PR Review Pipeline is a three-agent sequential system that takes a GitHub PR URL as input and produces a structured code review comment as output. It is not a linter or static analysis tool — it applies judgment against team coding standards retrieved at runtime from a Team Brain MCP server.

```
Input: GitHub PR URL
  │
  ▼
[Agent 1: Analyzer]  ──── GitHub API (read diff + metadata)
  │  PRClassification
  ▼
[Agent 2: Reviewer]  ──── FastMCP Team Brain (coding standards RAG)
  │  ReviewFindings
  ▼
[Agent 3: Reporter]  ──── Terminal HITL gate
  │  (approved)
  ▼
GitHub API (post comment) + LangFuse trace
```

Every LLM call is instrumented via LangFuse. Three Agno agents run sequentially — each reads from and writes to a shared `PipelineState` object. All LLM calls are routed through LiteLLM using `anthropic/model-name` IDs.

---

## 2. Data Models

```python
from pydantic import BaseModel
from enum import Enum
from typing import Optional

class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

class ChangeType(str, Enum):
    FEATURE = "feature"
    BUG_FIX = "bug_fix"
    REFACTOR = "refactor"
    SECURITY = "security"
    DOCS = "docs"
    CONFIG = "config"
    DEPENDENCY = "dependency"

class PRMetadata(BaseModel):
    url: str
    repo: str          # "owner/repo"
    pr_number: int
    title: str
    description: str
    diff: str          # raw unified diff
    files_changed: list[str]
    lines_added: int
    lines_removed: int

class PRClassification(BaseModel):
    risk_level: RiskLevel
    change_types: list[ChangeType]
    risk_rationale: str        # one sentence explaining the risk rating
    model_to_use: str          # resolved model ID for Reviewer
    files_of_concern: list[str]  # files that drove the risk rating

class ReviewFinding(BaseModel):
    severity: str              # "critical" | "warning" | "suggestion"
    file: str
    line_range: Optional[str]  # e.g. "42-51" or None for file-level
    issue: str                 # what's wrong
    standard_cited: Optional[str]  # which team standard this violates
    suggestion: str            # concrete fix

class ReviewFindings(BaseModel):
    summary: str               # 1-2 sentence overall assessment
    findings: list[ReviewFinding]
    verdict: str               # "approve" | "request_changes" | "comment"
    confidence: float          # 0.0–1.0; low confidence triggers HITL note

class PipelineState(BaseModel):
    # Input
    pr_url: str

    # Set by Analyzer
    metadata: Optional[PRMetadata] = None
    classification: Optional[PRClassification] = None

    # Set by Reviewer
    findings: Optional[ReviewFindings] = None

    # Set by Reporter
    draft_comment: Optional[str] = None
    human_approved: Optional[bool] = None
    posted_comment_url: Optional[str] = None

    # Observability
    run_id: str
    total_cost_usd: float = 0.0
    error: Optional[str] = None
```

---

## 3. Agent Specifications

### Agent 1: Analyzer

**Role**: Fetches the PR from GitHub and classifies its risk level. Routes to the correct model tier for the Reviewer.

**Input**: `pr_url: str`

**Output**: `PRClassification`

**Model**: `anthropic/claude-haiku-4-5-20251001` via LiteLLM (cheap tier — classification only)

**Tools**:
- `get_pr_metadata(url: str) -> PRMetadata` — calls GitHub REST API, extracts diff and metadata
- `validate_diff(diff: str) -> str` — strips any prompt-injection payloads from the diff before it reaches an LLM (security boundary)

**System Prompt**:
```
You are a PR risk classifier. Given a pull request diff and metadata, your job is to:
1. Identify the type(s) of change (feature, bug_fix, refactor, security, docs, config, dependency)
2. Assign a risk level: low (docs/config/trivial fixes), medium (features/refactors), high (security-sensitive/auth/payments/data migrations/dependency bumps)
3. List the specific files that drove your risk rating
4. Choose the review model: low→haiku, medium→sonnet, high→opus

Return a valid PRClassification. Be conservative: when in doubt, rate higher.
```

**Risk Routing Table**:
| Risk | LiteLLM model ID |
|---|---|
| low | `anthropic/claude-haiku-4-5-20251001` |
| medium | `anthropic/claude-sonnet-4-6` |
| high | `anthropic/claude-opus-4-8` |

---

### Agent 2: Reviewer

**Role**: Reviews the PR diff against team coding standards retrieved from the Team Brain MCP. Produces structured findings.

**Input**: `PRMetadata` + `PRClassification`

**Output**: `ReviewFindings`

**Model**: Resolved from `PRClassification.model_to_use` at runtime; set on the Agno agent via `LiteLLM(id=state.classification.model_to_use)`

**Tools**:
- `get_team_standards(topics: list[str]) -> list[str]` — MCP tool call to Team Brain server; retrieves relevant standard excerpts based on change types and files
- `search_diff_context(file: str, line: int, window: int) -> str` — returns surrounding diff context for a specific finding

**System Prompt**:
```
You are a senior code reviewer. You review pull requests against the team's coding standards.

Your job:
1. Read the diff carefully — only comment on what is actually in the diff
2. Retrieve relevant team standards using get_team_standards
3. For each issue found, cite the specific standard it violates
4. Do NOT invent file paths or function names — only reference what is in the diff
5. Be specific: "line 42 in auth.py uses MD5 for password hashing" not "security concerns exist"

Produce a ReviewFindings with severity levels: critical (must fix before merge), warning (should fix), suggestion (optional improvement).

If the diff is clean and meets standards, say so — an empty findings list with verdict "approve" is a valid and valued output.
```

**Reflection Step** (Reviewer internal loop):
After generating findings, the Reviewer performs one self-review pass:
- Are all cited file paths present in the diff?
- Are all cited standards real (retrieved, not hallucinated)?
- Is any finding vague or non-actionable?

If self-review flags issues, the Reviewer revises before emitting.

---

### Agent 3: Reporter

**Role**: Formats the findings into a GitHub PR comment, presents it to the human operator for approval, and posts it on approval.

**Input**: `PRMetadata` + `ReviewFindings`

**Output**: `draft_comment: str` → HITL gate → `posted_comment_url: str`

**Model**: `anthropic/claude-sonnet-4-6` via LiteLLM (balanced — formatting and synthesis)

**Tools**:
- `format_as_github_markdown(findings: ReviewFindings) -> str` — deterministic formatter, no LLM call needed. Output structure: opening summary paragraph (from `findings.summary` + verdict), then one markdown block per `ReviewFinding` (severity badge, file + line range, issue, standard cited, suggestion)
- `post_pr_comment(repo: str, pr_number: int, body: str) -> str` — GitHub API write; only called after human approval
- `log_structured_trace(state: PipelineState) -> None` — writes Factor IX structured trace to LangFuse

**HITL Behavior**:
```
--- DRAFT REVIEW COMMENT ---
[formatted comment shown here]
---
Post this comment to PR #{pr_number}? [y/n]: 
```
- `y` → calls `post_pr_comment`, logs success
- `n` → logs cancellation, exits cleanly with `human_approved=False`
- Timeout (60s with no input) → treats as `n`

---

## 4. Agno Pipeline

Agent definitions (`src/agents/`):

```python
from agno.agent import Agent
from agno.models.litellm import LiteLLM

analyzer_agent = Agent(
    name="analyzer",
    model=LiteLLM(id="anthropic/claude-haiku-4-5-20251001"),
    tools=[get_pr_metadata, validate_diff],
    response_model=PRClassification,
    instructions=ANALYZER_SYSTEM_PROMPT,
)

reviewer_agent = Agent(
    name="reviewer",
    model=LiteLLM(id="anthropic/claude-sonnet-4-6"),  # overridden at runtime
    tools=[get_team_standards, search_diff_context],
    response_model=ReviewFindings,
    instructions=REVIEWER_SYSTEM_PROMPT,
)

reporter_agent = Agent(
    name="reporter",
    model=LiteLLM(id="anthropic/claude-sonnet-4-6"),
    tools=[format_as_github_markdown, post_pr_comment, log_structured_trace],
    instructions=REPORTER_SYSTEM_PROMPT,
)
```

Pipeline entry point (`src/pipeline.py`):

```python
from uuid import uuid4
from langfuse import observe, get_client
from utils import setup_langfuse_tracing

langfuse = get_client()

@observe(name="pr_review_pipeline")
def run(pr_url: str) -> PipelineState:
    state = PipelineState(pr_url=pr_url, run_id=str(uuid4()))

    # Agent 1: Analyzer — each agent's run() auto-becomes a child span via @observe nesting
    result = analyzer_agent.run(pr_url)
    state.metadata = result.metadata
    state.classification = result.classification

    # Agent 2: Reviewer — model resolved from risk level at runtime
    reviewer_agent.model = LiteLLM(id=state.classification.model_to_use)
    state.findings = reviewer_agent.run(
        metadata=state.metadata,
        classification=state.classification,
    ).content

    # Agent 3: Reporter — produces draft comment
    state.draft_comment = reporter_agent.run(
        metadata=state.metadata,
        findings=state.findings,
    ).content

    # HITL gate — implemented in pipeline entry point (not Agno-native)
    approved = human_approval_gate(state)
    langfuse.score_current_trace(name="human-approval", value=1 if approved else 0)

    if not approved:
        state.human_approved = False
        log_structured_trace(state)
        langfuse.flush()
        return state

    state.posted_comment_url = post_pr_comment(
        state.metadata.repo, state.metadata.pr_number, state.draft_comment
    )
    state.human_approved = True
    log_structured_trace(state)
    langfuse.flush()
    return state

if __name__ == "__main__":
    setup_langfuse_tracing()
    import sys
    run(sys.argv[1])
```

---

## 5. Team Brain MCP Server

A `FastMCP` server wrapping a **minimal stub** of team coding standards — a small set of markdown files written specifically for this project. No external repo dependency.

**Standards stub structure** (`team_brain/standards/`):
```
team_brain/standards/
  python.md       — naming, type hints, docstring rules
  security.md     — auth patterns, secret handling, injection prevention
  testing.md      — test coverage expectations, pytest conventions
  git.md          — commit hygiene, PR size, branch naming
```

**Server definition** (`team_brain/server.py`):
```python
from fastmcp import FastMCP
from pathlib import Path

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
    return "\n\n---\n\n".join(p.read_text() for p in STANDARDS_DIR.glob("*.md"))
```

**Transport**: `stdio` only. The Reviewer connects via `mcp.run(transport="stdio")`. No network port, no auth config required.

**Launch**: `python -m team_brain.server` — started as a subprocess by the LangGraph workflow before the Reviewer node runs.

---

## 6. External Integrations

### GitHub API
- **Auth**: `GITHUB_TOKEN` env var (personal access token, scoped to `repo` write for comments)
- **Endpoints used**:
  - `GET /repos/{owner}/{repo}/pulls/{pull_number}` — fetch PR metadata
  - `GET /repos/{owner}/{repo}/pulls/{pull_number}/files` — fetch diff
  - `POST /repos/{owner}/{repo}/issues/{issue_number}/comments` — post review comment
- **Client**: `PyGithub` or raw `httpx` calls

### LangFuse
- **Auth**: `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY` + `LANGFUSE_HOST` env vars
- **Instrumentation pattern**: `@observe(name="...")` decorator (canonical agno + LangFuse pattern); nested `@observe` functions automatically become child spans — no extra wiring
- **Startup**: `setup_langfuse_tracing()` called once in `__main__` before any agent runs; `langfuse.flush()` called at the end of every `run()`
- **What gets traced**:
  - Parent trace: `pr_review_pipeline` — top-level `@observe` on `run()`
  - Child spans: one per agent (`analyzer`, `reviewer`, `reporter`) via nested `@observe`
  - Each span: model, prompt tokens, completion tokens, latency ms, cost USD
  - HITL outcome: `langfuse.score_current_trace(name="human-approval", value=1|0)`

---

## 7. Security Requirements

### Input Validation (before any LLM call)
- PR diff is passed through a sanitization step that strips common prompt injection patterns
- Maximum diff size: 100KB — larger PRs are rejected with a clear error (not silently truncated)
- GitHub token never appears in any log, trace, or LLM prompt

### Least Privilege
- The GitHub token only needs `pull_requests: write` — document this in the README
- The MCP server runs locally; no external network exposure required

### Prompt Injection (Confused Deputy Defense)
- The `validate_diff` tool strips content matching injection patterns (`Ignore previous instructions`, `<|im_start|>`, etc.) before it reaches the Reviewer's context
- Any finding that cites a file path not present in the original diff is rejected by the Reporter's output validator

---

## 8. Observability Requirements

Every run must produce:
1. A LangFuse trace visible at `https://cloud.langfuse.com`
2. A terminal summary line: `✓ Run {run_id} | Risk: {risk_level} | Findings: {n} | Cost: ${cost:.4f} | Status: {posted|aborted}`
3. A structured trace entry (Factor IX) appended to `traces/YYYY-MM-DD.jsonl`:

```json
{
  "run_id": "...",
  "timestamp": "...",
  "pr_url": "...",
  "risk_level": "medium",
  "findings_count": 3,
  "verdict": "request_changes",
  "human_approved": true,
  "total_cost_usd": 0.0312,
  "models_used": ["anthropic/claude-haiku-4-5-20251001", "anthropic/claude-sonnet-4-6"],
  "langfuse_trace_url": "..."
}
```

---

## 9. Evaluation Plan

| What | Method | Threshold |
|---|---|---|
| Analyzer risk classification | Code-based: compare against labeled test PRs | ≥ 85% accuracy |
| Reviewer hallucination (fake file paths) | Code-based: assert all cited paths exist in diff | 0 hallucinations |
| Review usefulness | LLM-as-judge: GPT-4 rates findings on a 1–5 scale | Mean ≥ 3.5 |
| Cost per run | Code-based: sum from LangFuse | Low ≤ $0.05, High ≤ $0.25 |
| End-to-end latency | Code-based: wall-clock from input to HITL prompt | Low ≤ 30s, High ≤ 90s |

Golden dataset: 10 **synthetic** PRs (3 low-risk, 4 medium, 3 high) — crafted with known issues pre-planted (e.g. MD5 password hashing, missing type hints, hardcoded secrets). Safe to commit, fully controlled, no real codebase dependency.

---

## 10. Non-Goals

The following are explicitly out of scope for the capstone:
- Auto-merging or auto-approving PRs
- Multi-repository orchestration
- Web UI or Slack integration
- CI/CD pipeline integration (GitHub Actions trigger)
- Support for non-GitHub providers (GitLab, Bitbucket)
- Fine-tuning any model on review data

These are valid future extensions but must not inflate the capstone scope.

---

## 11. Clarify — Resolved Decisions

All open questions resolved before planning began.

| Question | Decision | Rationale |
|---|---|---|
| Team Brain source | Minimal stub (`team_brain/standards/*.md`) | No external repo dependency; fully controlled for demo |
| MCP transport | `stdio` only | Simpler local setup; no port/auth config; sufficient for capstone |
| Golden dataset | Synthetic PRs with pre-planted issues | Safe to commit publicly; fast to create; fully controlled |
| Comment format | Summary paragraph + inline findings | More readable for PR author; aligns with `ReviewFindings.summary` field |
