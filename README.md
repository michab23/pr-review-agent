# Agentic PR Review Pipeline

Multi-agent system that reviews GitHub pull requests against team coding standards
and posts a structured comment — with a human-in-the-loop approval gate before anything
is posted.

Built for the Tikal LLM Engineering Course · Capstone Project · Team 4
(Najeeb, Amir, Erez, Avichay, Michael)

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
 └────────────────────────┬────────────────────────────────────┘
                          │
                          ▼  model selection by risk
 ┌─────────────────────────────────────────────────────────────┐
 │  AGENT 2 · Reviewer  [Haiku | Sonnet | Opus]               │
 │  Tool: get_team_standards() via Team Brain MCP (SSE)       │
 │  Produces ReviewFindings grounded in retrieved standards   │
 │  Self-review step strips hallucinated file paths           │
 └────────────────────────┬────────────────────────────────────┘
                          │
                          ▼  findings
 ┌─────────────────────────────────────────────────────────────┐
 │  AGENT 3 · Reporter  [Sonnet]                              │
 │  Formats findings into a GitHub markdown comment           │
 └────────────────────────┬────────────────────────────────────┘
                          │
                          ▼  HITL gate (y/n, 60 s timeout)
                    post_pr_comment()
```

**Risk → Model routing**

| Risk level | Reviewer model         |
|------------|------------------------|
| low        | claude-haiku-4-5       |
| medium     | claude-sonnet-4-6      |
| high       | claude-opus-4-8        |

**Observability:** every run is traced with LangFuse (`@observe`) and written to
`traces/YYYY-MM-DD.jsonl`.

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
uv run python demo.py --live https://github.com/owner/repo/pull/123
```

### Production pipeline

```bash
uv run python -m src.pipeline https://github.com/owner/repo/pull/123
```

Prompts for approval before posting. Times out after 60 s.

---

## Tests

```bash
# Structural tests only — no LLM calls, always fast
uv run pytest evals/ -v -m "not llm_eval"

# Full LLM evaluation suite — costs money
uv run pytest evals/ -v
```

The eval dataset contains 10 synthetic PRs (3 low / 4 medium / 3 high risk) with
planted issues for grading Analyzer accuracy and Reviewer hallucination rate.

---

## Project structure

```
src/
  agents/
    analyzer.py       # Agent 1 — risk classification
    reviewer.py       # Agent 2 — standards-grounded review
    reporter.py       # Agent 3 — markdown comment formatter
  tools/
    github.py         # PR fetch, diff validation, comment posting
    team_brain.py     # MCP client for Team Brain standards server
    trace.py          # Structured JSONL trace writer
  team_brain/
    standards/        # security.md, python.md, testing.md, git.md
  models.py           # Pydantic data models (PRMetadata, ReviewFindings, …)
  pipeline.py         # Entry point — wires agents + HITL gate
evals/
  dataset/            # 10 synthetic PR JSON entries
  test_pipeline.py    # Structural + LLM eval tests
demo.py               # Presentation demo script
traces/               # Per-run JSONL trace output (git-ignored)
spec/                 # Architecture decision records + data model spec
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
