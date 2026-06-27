# Agentic PR Review Pipeline

Multi-agent system that reviews GitHub pull requests against team coding standards
and posts a structured comment — with a human-in-the-loop approval gate before anything
is posted.

Built for the Tikal LLM Engineering Course · Capstone Project

---

## Architecture

```
 GitHub PR URL
      │
      ▼  get_pr_metadata()
 ┌─────────────────────────────────────────────────────────────┐
 │  AGENT 1 · Analyzer  [Haiku]                               │
 │  Classifies risk level (low / medium / high)               │
 │  Routes to the appropriate model tier for review           │
 │  ↳ absent/crash → medium-risk fallback, pipeline continues │
 └────────────────────────┬────────────────────────────────────┘
                          │
                          ▼  model selection by risk
 ┌─────────────────────────────────────────────────────────────┐
 │  AGENT 2 · Reviewer  [Haiku | Sonnet | Opus]               │
 │  Tool: get_team_standards() via Team Brain MCP (SSE)       │
 │  Produces ReviewFindings grounded in retrieved standards   │
 │  Self-review step strips hallucinated file paths           │
 │  ↳ absent/crash → placeholder findings, pipeline continues │
 └────────────────────────┬────────────────────────────────────┘
                          │
                          ▼  findings
 ┌─────────────────────────────────────────────────────────────┐
 │  AGENT 3 · Reporter  [Sonnet]                              │
 │  Formats findings into a GitHub markdown comment           │
 │  ↳ absent/crash → raw findings shown as fallback draft     │
 └────────────────────────┬────────────────────────────────────┘
                          │
                          ▼  HITL gate (y/n, 60 s timeout)
                    post_pr_comment()
```

Each agent is **independently executable** (`python -m src.agents.<name>`) and the
pipeline **degrades gracefully** — removing or crashing any single agent produces a
warning and a defined fallback; the HITL gate always fires before anything is posted.

**Risk → Model routing**

| Risk level | Reviewer model         |
|------------|------------------------|
| low        | claude-haiku-4-5       |
| medium     | claude-sonnet-4-6      |
| high       | claude-opus-4-8        |

**Observability:** every run is traced with LangFuse (`@observe`) and written to
`traces/YYYY-MM-DD.jsonl`. Degraded runs include `degraded: true` and `agents_failed`
in the trace so they are distinguishable from clean runs.

---

## Prerequisites

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/) package manager
- Anthropic API key (for running agents)
- GitHub token with `repo` scope (for live mode)
- LangFuse keys (optional — traces are skipped gracefully if absent)

---

## Setup

```bash
# Install dependencies
uv sync

# Copy and fill in credentials
cp .env.example .env
# edit .env: ANTHROPIC_API_KEY, GITHUB_TOKEN, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY
```

`.env.example`:
```
ANTHROPIC_API_KEY=sk-ant-...
GITHUB_TOKEN=ghp_...
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com
```

---

## Running

### Team Brain MCP server (start once, keep running)

The pipeline retrieves team coding standards from the Team Brain MCP server. Start it in a
dedicated terminal before running the pipeline:

```bash
# Terminal 1 — start once, leave running
uv run team-brain
```

The server is ready when you see:
```
Starting MCP server 'team-brain' with transport 'sse'
```

If the server is not running, the pipeline falls back to reading standards files directly
and prints a warning — reviews still complete.

> **Non-default address**: Override with `TEAM_BRAIN_URL=http://host:port/sse` in both terminals.

---

### Demo (offline, no GitHub token needed)

Runs the full 3-agent pipeline against a canned high-risk PR from the eval dataset.
Nothing is posted — the draft comment is printed but HITL is skipped.

```bash
uv run python demo.py
```

### Demo (live GitHub PR)

```bash
uv run python demo.py --live https://github.com/michab23/pr-review-agent/pull/8
```

### Production pipeline

```bash
uv run python -m src.pipeline https://github.com/michab23/pr-review-agent/pull/8
```

Prompts for approval before posting. Times out after 60 s.

### Run a single agent in isolation

Each agent accepts JSON on stdin and writes its output to stdout — no pipeline or
other agents required:

```bash
# Analyzer — input: PRMetadata JSON → output: PRClassification JSON
echo '{"url":"https://github.com/owner/repo/pull/1","repo":"owner/repo","pr_number":1,"title":"fix","description":"","diff":"--- a/x.py\n+++ b/x.py\n+x=1","files_changed":["x.py"],"lines_added":1,"lines_removed":0}' | uv run python -m src.agents.analyzer

# Reviewer — input: {metadata, classification, standards} JSON → output: ReviewFindings JSON
echo '{"metadata":{"url":"https://github.com/owner/repo/pull/1","repo":"owner/repo","pr_number":1,"title":"fix","description":"","diff":"--- a/x.py\n+++ b/x.py\n+x=1","files_changed":["x.py"],"lines_added":1,"lines_removed":0},"classification":{"risk_level":"low","change_types":["bug_fix"],"risk_rationale":"Trivial single-line fix","model_to_use":"anthropic/claude-haiku-4-5-20251001","files_of_concern":["x.py"]},"standards":"(none)"}' | uv run python -m src.agents.reviewer

# Reporter — input: {metadata, findings, run_id, cost_usd} JSON → output: markdown comment
echo '{"metadata":{"url":"https://github.com/owner/repo/pull/1","repo":"owner/repo","pr_number":1,"title":"fix","description":"","diff":"--- a/x.py\n+++ b/x.py\n+x=1","files_changed":["x.py"],"lines_added":1,"lines_removed":0},"findings":{"summary":"No issues found.","findings":[],"verdict":"approve","confidence":0.9},"run_id":"debug-001","cost_usd":0.0}' | uv run python -m src.agents.reporter
```

Invalid input exits with code 1 and a message on stderr.

---

## Tests

```bash
# Unit tests — no LLM calls, always fast (~7 s)
uv run pytest tests/ -v

# LLM evaluation suite — costs money, tests pipeline quality
uv run pytest evals/ -v -m "not llm_eval"   # structural only
uv run pytest evals/ -v                      # full suite

# Standalone-agent integration tests — make real LLM calls, excluded by default
uv run pytest tests/ -v -m integration
```

The `tests/` directory covers pipeline logic, graceful-degradation scenarios, trace
serialization, and standalone agent entrypoints. The `evals/` dataset contains 10
synthetic PRs (3 low / 4 medium / 3 high risk) with planted issues for grading
Analyzer accuracy and Reviewer hallucination rate.

---

## Project structure

```
src/
  agents/
    analyzer.py       # Agent 1 — risk classification (+ standalone entrypoint)
    reviewer.py       # Agent 2 — standards-grounded review (+ standalone entrypoint)
    reporter.py       # Agent 3 — markdown comment formatter (+ standalone entrypoint)
  tools/
    github.py         # PR fetch, diff validation, comment posting
    team_brain.py     # MCP client for Team Brain standards server
    trace.py          # Structured JSONL trace writer (degraded flag included)
  team_brain/
    standards/        # security.md, python.md, testing.md, git.md
  models.py           # Pydantic data models (PRMetadata, ReviewFindings, PipelineState, …)
  pipeline.py         # Entry point — wires agents, graceful degradation, HITL gate
tests/
  test_pipeline.py    # Unit tests — pipeline logic, degradation scenarios, trace
  test_agents_standalone.py  # Integration tests for standalone agent entrypoints
  test_github.py / test_models.py / test_trace.py / test_utils.py
evals/
  dataset/            # 10 synthetic PR JSON entries
  test_pipeline.py    # Structural + LLM eval tests
demo.py               # Presentation demo script
traces/               # Per-run JSONL trace output (git-ignored)
spec/                 # Architecture decision records + data model spec
specs/                # Feature specs, plans, and task lists
```

---

## Key design decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Framework | Agno v2.6 | Native `output_schema` + LiteLLM backend |
| Model routing | risk-tiered | Cost control — haiku for low-risk PRs |
| Standards delivery | MCP SSE | Reviewer gets live standards from persistent server, not baked-in prompt text |
| GitHub I/O | pipeline level only | Agents never touch GitHub — cleaner separation |
| Reflection | system prompt self-check | Reduces hallucinated file paths without a second LLM call |
| Observability | LangFuse `@observe` | Full trace tree per run, human approval score |
| Agent independence | guarded imports + per-agent try/except | Removing any agent causes graceful degradation, not a crash; each agent is also independently invocable via `python -m` |
