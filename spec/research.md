# Research — Agentic PR Review Pipeline

> Generated at the spec.plan stage. Records tech stack decisions, assumptions, and risk factors before implementation begins.

---

## Tech Stack

| Layer | Choice | Rationale |
|---|---|---|
| Language | Python 3.11+ | Course standard; Pydantic v2 requires 3.10+ |
| Package manager | `uv` | Course standard; fast, lockfile-based, reproducible |
| Orchestration | Agno 1.0+ | Sequential multi-agent pipeline; explicit agent roles; `response_model` for typed I/O |
| Data validation | Pydantic v2 | Type-safe inter-agent contracts; used as `response_model` on each Agno agent |
| LLM client | `litellm` | Provider-agnostic gateway; routes `anthropic/model-name` IDs to Anthropic API; single abstraction for all three model tiers |
| Team Brain server | FastMCP | Decorator-based MCP server; `stdio` transport; covered in Module 4 |
| GitHub client | `PyGithub` | Thin wrapper over GitHub REST API; handles auth and pagination cleanly |
| Observability | `langfuse` SDK | Spans + cost tracking; direct SDK (not LangChain callback) for maximum control |
| Eval | `deepeval` | pytest-style; `HallucinationMetric` + custom metrics; CI-friendly |
| Env management | `python-dotenv` | `load_dotenv()` at startup; all secrets from `.env` |

---

## Key Assumptions

1. **GitHub token scope**: The operator has a GitHub personal access token with `repo` scope. For comment-only use, `pull_requests: write` suffices — document this clearly.

2. **LangFuse account**: A free LangFuse cloud account is available. `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and `LANGFUSE_HOST=https://cloud.langfuse.com` are set in `.env`. No self-hosting required.

3. **Model access**: The `ANTHROPIC_API_KEY` in `.env` has access to all three model tiers (Haiku, Sonnet, Opus). The pipeline will work with Sonnet-only if Opus is unavailable — Reviewer falls back to Sonnet for high-risk PRs.

4. **Diff size**: PRs up to 100KB diff size are supported. Beyond that, the Analyzer rejects with a clear error. Most real PRs are well under this limit.

5. **MCP subprocess**: The Team Brain MCP server is launched as a subprocess by the workflow at startup and torn down on exit. No persistent daemon required.

6. **Single repo per run**: The pipeline processes one PR at a time. No batch mode, no queue.

7. **Terminal operator**: Someone is watching the terminal when the HITL gate fires. The 60-second timeout-to-abort is a safety net, not the normal flow.

---

## Directory Structure

```
pr-review-agent/
├── pyproject.toml
├── .env.example
├── README.md
│
├── src/
│   ├── models.py          # All Pydantic data models
│   ├── pipeline.py        # Agno sequential pipeline (entry point)
│   │
│   ├── agents/
│   │   ├── analyzer.py    # Agent 1: risk classification
│   │   ├── reviewer.py    # Agent 2: code review via MCP
│   │   └── reporter.py    # Agent 3: format + HITL + post
│   │
│   ├── tools/
│   │   ├── github.py      # get_pr_metadata, validate_diff, post_pr_comment
│   │   └── trace.py       # log_structured_trace (JSONL + LangFuse)
│   │
│   └── team_brain/
│       ├── server.py      # FastMCP server definition
│       └── standards/
│           ├── python.md
│           ├── security.md
│           ├── testing.md
│           └── git.md
│
├── evals/
│   ├── dataset/           # 10 synthetic PR diffs + expected classifications
│   └── test_pipeline.py   # DeepEval test suite
│
└── traces/                # JSONL structured trace log (gitignored)
```

---

## Dependencies (`pyproject.toml`)

```toml
[project]
name = "pr-review-agent"
version = "0.1.0"
requires-python = ">=3.11"

dependencies = [
    "agno>=1.0",
    "litellm>=1.0",
    "langfuse>=2.0",
    "pydantic>=2.0",
    "fastmcp>=0.4",
    "PyGithub>=2.0",
    "python-dotenv>=1.0",
    "deepeval>=1.0",
    "rich>=13.0",          # terminal formatting for HITL display
]
```

---

## Risk Factors

| Risk | Likelihood | Mitigation |
|---|---|---|
| GitHub token insufficient scope | Low | Document exact scope in README; fail fast with clear error message |
| Reviewer hallucinates file paths | Medium | Reflection self-review step + Reporter output validator checks all paths against diff |
| MCP subprocess fails to start | Low | Pipeline raises `RuntimeError` at startup with instructions before any LLM calls |
| LangFuse API unavailable | Low | Wrap all `langfuse` calls in try/except; pipeline continues, logs warning |
| High-risk PR costs exceed $0.25 | Low | Log cost per run; Opus is only used for `high` risk classification; add token pre-check |
| Prompt injection via PR diff | Medium | `validate_diff` strips injection patterns before diff enters any LLM context |
| HITL gate timing (custom implementation) | Low | HITL is a plain Python gate in the pipeline entry point; 60-second timeout handled with `sys.stdin` + `select`; add integration test |
