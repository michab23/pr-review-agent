# Implementation Plan — Agentic PR Review Pipeline

> Generated from `spec.md` + `research.md`. This is the execution checklist.
> Triage key: **[SYNC]** = pair with AI (high risk/complexity) · **[ASYNC]** = delegate to AI (low risk/toil)
> Rule: fix `spec.md` when a task reveals a gap — never patch code to work around a missing spec.

---

## Task List

### Phase 1 — Scaffold

- [ ] **[ASYNC] 1. Project scaffold**
  Set up `pr-review-agent/` with the directory structure from `research.md`. Create `pyproject.toml` with all dependencies, `.env.example` with required keys, and a stub `README.md`.
  - Output: installable project (`uv sync` succeeds, `uv run python -c "import agno, litellm"` passes)
  - Keys in `.env.example`: `ANTHROPIC_API_KEY`, `GITHUB_TOKEN`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`

- [ ] **[ASYNC] 2. Implement Pydantic data models**
  Implement all models from `data-model.md` in `src/models.py`. Include field validators where specified (diff size cap, file path subset check, verdict consistency).
  - Output: `uv run python -c "from src.models import PipelineState"` succeeds with no errors

---

### Phase 2 — Infrastructure

- [ ] **[ASYNC] 3. Write Team Brain standards stub**
  Create the four standards files in `src/team_brain/standards/` with realistic, specific rules (not placeholder text). Then implement `src/team_brain/server.py` with the FastMCP server and `get_team_standards` tool.
  - Standards content: at least 5 concrete rules per file (e.g. `security.md` must include: no MD5/SHA1 for passwords, no hardcoded secrets, parameterized queries, JWT expiry, HTTPS enforcement)
  - Output: `uv run python -m src.team_brain.server` starts without error

- [ ] **[SYNC] 4. GitHub API integration**
  Implement `src/tools/github.py`: `get_pr_metadata()` and `validate_diff()` and `post_pr_comment()`.
  - `get_pr_metadata` must: parse PR URL to extract owner/repo/number, call GitHub API, build `PRMetadata`, reject diffs > 100KB
  - `validate_diff` must: strip prompt injection patterns before returning cleaned diff
  - `post_pr_comment` must: only post, never mutate or delete; log the resulting comment URL
  - Test manually against a real or mock PR before marking done
  - **Why SYNC**: external API + security boundary; prompt injection sanitization must be reviewed by a human

---

### Phase 3 — Agents

- [ ] **[SYNC] 5. Analyzer agent**
  Implement `src/agents/analyzer.py` as a LangGraph node function. Wire `get_pr_metadata` and `validate_diff` as tools. Use the system prompt from `spec.md`. Output must be a valid `PRClassification`.
  - Model: `claude-haiku-4-5-20251001`
  - Validate `model_to_use` maps correctly to the risk routing table
  - Add LangFuse span: `name="analyzer"`, tag `risk_level` and token costs
  - **Why SYNC**: routing logic is the foundation everything else depends on; a wrong risk rating cascades

- [ ] **[SYNC] 6. Reviewer agent**
  Implement `src/agents/reviewer.py`. Launch the Team Brain MCP subprocess, connect via `stdio`, expose `get_team_standards` as a tool. Implement the Reflection self-review pass after initial findings are generated.
  - Model: resolved from `state.classification.model_to_use` at runtime
  - Reflection pass must reject: cited file paths not in diff, vague findings with no suggestion, standard citations not matching retrieved content
  - Add LangFuse span: `name="reviewer"`, tag `model_used`, `findings_count`, token costs
  - **Why SYNC**: most complex agent; dynamic model selection + MCP subprocess + reflection loop = highest risk of subtle bugs

- [ ] **[SYNC] 7. Reporter agent**
  Implement `src/agents/reporter.py`. Implement `format_as_github_markdown()` as a deterministic formatter (no LLM call). Implement the HITL terminal display with 60-second timeout. Wire `post_pr_comment` for the approval path.
  - Comment format must match the template in `data-model.md` exactly (summary paragraph, per-finding blocks, run metadata footer)
  - `confidence < 0.7` must append the low-confidence warning header
  - Add LangFuse span: `name="reporter"`, tag `human_approved`, `posted_comment_url`
  - **Why SYNC**: HITL gate is a trust boundary — the exact display and approval flow must be human-reviewed

---

### Phase 4 — Orchestration

- [ ] **[SYNC] 8. Agno pipeline wiring**
  Implement `src/pipeline.py`. Instantiate the three Agno agents, wire them sequentially in `run(pr_url: str)`, implement the HITL gate as a plain Python step between Reporter and the poster call (60-second timeout via `select`).
  - Sequential flow must match the diagram in `spec.md` exactly: Analyzer → Reviewer → Reporter → HITL → poster
  - Override `reviewer_agent.model` with `LiteLLM(id=state.classification.model_to_use)` before the Reviewer runs
  - HITL gate: `y` → call `post_pr_comment`, `n` or timeout → set `human_approved=False`, exit cleanly
  - Print the terminal summary line on completion: `✓ Run {run_id} | Risk: {risk_level} | Findings: {n} | Cost: ${cost:.4f} | Status: {posted|aborted}`
  - **Why SYNC**: dynamic model override + HITL gate wiring = highest risk of silent mis-routing

---

### Phase 5 — Observability

- [ ] **[ASYNC] 9. LangFuse instrumentation**
  Instrument the pipeline using the canonical agno + LangFuse pattern. Call `setup_langfuse_tracing()` in `__main__`. Decorate `run()` with `@observe(name="pr_review_pipeline")`; each agent's internal run automatically becomes a child span. At the HITL gate, call `langfuse.score_current_trace(name="human-approval", value=1|0)`. Call `langfuse.flush()` at the end of every `run()`. Write the JSONL structured trace to `traces/YYYY-MM-DD.jsonl` at the end of each run.
  - Wrap all `langfuse` calls in try/except so a LangFuse outage never aborts the pipeline
  - JSONL schema must match the example in `spec.md §8`

---

### Phase 6 — Evaluation

- [ ] **[ASYNC] 10. Create synthetic golden dataset**
  Create 10 synthetic PR diffs in `evals/dataset/` with pre-planted issues and expected classifications:
  - 3 low-risk: docs-only change, config tweak, README fix
  - 4 medium-risk: new feature without auth, refactor of business logic, adding a dependency, bug fix
  - 3 high-risk: new auth endpoint with MD5 passwords, hardcoded API key, SQL string concatenation
  - Each entry: `{pr_diff, expected_risk_level, expected_change_types, planted_issues: [...]}`

- [ ] **[ASYNC] 11. DeepEval test suite**
  Implement `evals/test_pipeline.py` with three test classes:
  - `TestAnalyzerClassification`: assert risk level matches expected for all 10 PRs (target ≥ 85%)
  - `TestReviewerHallucination`: assert every `ReviewFinding.file` exists in the PR's `files_changed` (target: 0 violations)
  - `TestCostBounds`: assert `total_cost_usd ≤ 0.05` for low-risk, `≤ 0.25` for high-risk
  - Run with: `uv run pytest evals/ -v`

---

### Phase 7 — Integration & Demo

- [ ] **[SYNC] 12. End-to-end integration test**
  Run the full pipeline against one real GitHub PR (can be a test PR in a personal repo). Verify:
  - LangFuse trace appears with all three agent spans
  - HITL gate fires and displays the draft comment in the terminal
  - Approving posts the comment to GitHub successfully
  - JSONL trace entry is written to `traces/`
  - **Why SYNC**: first real end-to-end run; multiple systems in play; human must watch for failures

- [ ] **[ASYNC] 13. Demo prep**
  Write the final `README.md` with: quickstart (5 steps from clone to first review), architecture diagram (ASCII), `.env.example` documentation, and the "removing one agent breaks it" explanation for the demo.

---

## Triage Summary

| Mode | Tasks | Rationale |
|---|---|---|
| ASYNC (delegate) | 1, 2, 3, 9, 10, 11, 13 | Mechanical/structural work; clear spec; low blast radius |
| SYNC (pair) | 4, 5, 6, 7, 8, 12 | External API calls, security boundaries, agent logic, graph wiring |

---

## Definition of Done

The pipeline is complete when:
- [ ] `uv run python -m src.pipeline "https://github.com/owner/repo/pull/N"` runs end-to-end
- [ ] All three agent spans appear in LangFuse
- [ ] A comment is posted to GitHub after `y` approval
- [ ] `uv run pytest evals/ -v` passes all tests
- [ ] The demo can be walked in 15 minutes: live run → architecture explanation → lessons learned
