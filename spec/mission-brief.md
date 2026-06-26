# Mission Brief — Agentic PR Review Pipeline

> Factor III of the Twelve-Factor Agentic SDLC. Written before any planning or implementation begins.

---

## Goal

Build a multi-agent system that automatically reviews GitHub pull requests — classifying each PR's risk level, retrieving relevant coding standards from a Team Brain knowledge base, generating a structured review with findings, and posting the final comment to GitHub only after explicit human approval.

---

## Constraints

### Architecture
- Minimum 3 agents, each with a single defined role; every agent must be independently executable as a standalone component — removing any single agent must cause graceful degradation, not complete pipeline failure
- Orchestration via **Agno** (sequential multi-agent pipeline, explicit agent roles, typed I/O)
- All LLM calls routed via **LiteLLM** (provider-agnostic; model IDs use `anthropic/model-name` format)
- Agent I/O validated via **Pydantic** models — no untyped dicts passed between agents
- Coding standards retrieved via **FastMCP** Team Brain server (directives-as-code, Factor XI)
- All LLM calls instrumented via **LangFuse** — every agent span must appear in the trace

### Model Economics
- Analyzer: cheap tier (Haiku) — classification only
- Reviewer: tiered by risk level — low → Haiku, medium → Sonnet, high → Opus
- Reporter: balanced tier (Sonnet)
- Each run must log its total token cost to the LangFuse trace

### External Integration
- GitHub API is the mandatory external integration (fetch diff, post comment)
- All secrets loaded from environment variables — no hardcoded credentials anywhere

### HITL
- A human approval gate must exist between the Reviewer's findings and the Reporter posting to GitHub
- The draft comment is shown in the terminal; the operator types `y` to approve or `n` to abort
- If aborted, the run is logged but nothing is posted

### Security
- PR diffs are untrusted external input — apply input validation and prompt injection guardrails before passing to any LLM
- GitHub token must be scoped to the minimum required permission (PR comments only)

### Scope
- Python 3.11+
- Single repository at a time (no cross-repo orchestration)
- The system reviews code quality and adherence to team standards — it does not auto-merge or modify code
- No UI; terminal-first for the capstone demo

---

## Success Criteria

### Functional
- [ ] Given a GitHub PR URL, the pipeline produces a structured review comment in the terminal within 90 seconds for low-risk PRs
- [ ] The Analyzer correctly classifies PR risk as `low`, `medium`, or `high` and routes to the appropriate model tier
- [ ] The Reviewer cites at least one specific coding standard from the Team Brain MCP in every non-trivial review
- [ ] The Reporter presents a formatted draft in the terminal and waits for `y/n` approval before any GitHub API write
- [ ] On approval, the comment posts successfully to the correct PR on GitHub
- [ ] On abort, nothing is posted and a cancellation entry is written to the structured trace log

### Observability
- [ ] LangFuse shows a parent trace per pipeline run with one child span per agent
- [ ] Each span includes: model used, tokens in/out, latency, risk level (for Analyzer span), and cost
- [ ] A run can be replayed for debugging from the LangFuse trace alone

### Quality
- [ ] A real engineer, shown a sample review output, finds it more useful than "looks good" — i.e., it flags at least one specific, actionable issue on a PR that has known problems
- [ ] The Reviewer's output does not hallucinate file paths or function names that don't exist in the diff

### Demo
- [ ] The full pipeline can be demonstrated live on a real (or realistic mock) PR within a 15-minute presentation slot
- [ ] The architecture diagram can be walked in under 3 minutes, with each agent's role explained in one sentence

### Economics
- [ ] Cost per low-risk PR review ≤ $0.05
- [ ] Cost per high-risk PR review ≤ $0.25
