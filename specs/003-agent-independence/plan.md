# Implementation Plan: Agent Independence and Graceful Degradation

**Branch**: `003-agent-independence` | **Date**: 2026-06-26 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/003-agent-independence/spec.md`

## Summary

Implement the agent-independence constraint from `spec/mission-brief.md`: each of the three pipeline agents (Analyzer, Reviewer, Reporter) must be independently invocable as a standalone component, and the pipeline must degrade gracefully rather than crash when any single agent is unavailable. This requires: (1) lazy/guarded imports in `pipeline.py`, (2) per-step try/except with defined fallbacks, (3) `PipelineState` extended with degradation metadata, and (4) standalone `run_standalone` entrypoints in each agent module.

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: Agno (agent orchestration), LiteLLM, Pydantic v2, LangFuse, Rich
**Storage**: N/A — no database; trace log is file-based JSON
**Testing**: pytest, unittest.mock; subprocess for standalone entrypoint tests
**Target Platform**: Linux/macOS terminal
**Project Type**: CLI pipeline
**Performance Goals**: No degradation path should add >100ms latency
**Constraints**: HITL gate must never be bypassed; existing Pydantic model shapes preserved; no new dependencies
**Scale/Scope**: 3 agents, ~300 LOC change across 5 files

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| Simplicity First | ✅ PASS | Lazy imports + try/except + fallback constants — no new abstractions |
| Surgical Changes | ✅ PASS | Touch only `models.py`, `pipeline.py`, the three agent files, and two test files |
| Human Oversight | ✅ PASS | HITL gate preserved; degraded draft shown to operator before any post |
| Security by Default | ✅ PASS | No new credentials, no new trust boundaries introduced |
| Tests Drive Confidence | ✅ PASS | Three degradation test classes + standalone subprocess tests required |
| Build for Observability | ✅ PASS | `degraded` + `agents_failed` flow into LangFuse trace automatically |
| Immutability by Default | ✅ PASS | Fallback values are module-level constants, never mutated |
| Goal-Driven Execution | ✅ PASS | SC-001–SC-005 are concrete and verifiable |

*Note: `.specify/memory/constitution.md` is an unfilled placeholder. Evaluation performed against team-ai-directives constitution.*

**POST-DESIGN RE-CHECK**: Data model adds two optional fields with defaults — no violations. ✅

## Project Structure

### Documentation (this feature)

```text
specs/003-agent-independence/
├── plan.md              ← This file
├── research.md          ← Phase 0 output
├── data-model.md        ← Phase 1 output
├── checklists/
│   └── requirements.md
└── tasks.md             ← Phase 2 output (via /spec-tasks)
```

### Source Code (files touched)

```text
src/
├── models.py                  ← +2 fields on PipelineState
├── pipeline.py                ← lazy imports, try/except wrappers, fallback constants
└── agents/
    ├── analyzer.py            ← +run_standalone(), +__main__ block
    ├── reviewer.py            ← +run_standalone(), +__main__ block
    └── reporter.py            ← +run_standalone(), +__main__ block

tests/
├── test_pipeline.py           ← +3 degradation test classes
└── test_agents_standalone.py  ← new file, subprocess-based standalone tests
```

## Triage Framework: [SYNC] vs [ASYNC] Classification

**Execution Strategy**: Hybrid — structural/safety-critical changes are [SYNC]; boilerplate standalone entrypoints and tests are [ASYNC].

### Preliminary Task Classification

| Task Category | Estimated [SYNC] Tasks | Estimated [ASYNC] Tasks | Rationale |
|---------------|----------------------|----------------------|-----------|
| Model changes | 1 | 0 | Pydantic schema is foundational — human verification required |
| Pipeline degradation logic | 1 | 0 | Try/except + fallback constants are safety-critical; HITL path must be preserved |
| Agent standalone entrypoints | 0 | 3 | Well-defined pattern: validate input, build prompt, run agent, emit JSON |
| Degradation tests | 1 | 0 | Test design for degradation paths requires thought; execution is mechanical |
| Standalone subprocess tests | 0 | 1 | Pattern is uniform across all three agents |

### Triage Audit Trail

| Task | Classification | Primary Criteria | Risk Level | Rationale |
|------|----------------|------------------|------------|-----------|
| T-01: Extend PipelineState | [SYNC] | Schema change, affects trace log | Low | Model shape change; ensures downstream trace consumers don't break |
| T-02: Pipeline lazy imports + fallbacks | [SYNC] | Safety-critical — HITL path preservation | Medium | Core degradation logic; wrong fallback could post misleading comment to GitHub |
| T-03: Analyzer standalone entrypoint | [ASYNC] | Well-defined CRUD + standard pattern | Low | Pattern: validate PRMetadata → build prompt → run agent → emit PRClassification JSON |
| T-04: Reviewer standalone entrypoint | [ASYNC] | Well-defined CRUD + standard pattern | Low | Pattern: validate {metadata, classification, standards} → build prompt → run agent → emit ReviewFindings JSON |
| T-05: Reporter standalone entrypoint | [ASYNC] | Well-defined CRUD + standard pattern | Low | Pattern: validate {metadata, findings, run_id, cost} → build prompt → run agent → emit string |
| T-06: Degradation tests | [SYNC] | Test design for safety paths | Medium | Verifies HITL is reached, degraded flag set, no unhandled exception — logic must be correct |
| T-07: Standalone subprocess tests | [ASYNC] | Standard subprocess test pattern | Low | Uniform across all three agents; fixtures are simple JSON blobs |

## Implementation Tasks

### T-01 — Extend `PipelineState` [SYNC]

**File**: `src/models.py`

Add two fields at the end of `PipelineState`:

```python
degraded: bool = False
agents_failed: list[str] = []
```

No other changes. All existing tests pass unchanged because the new fields have defaults.

---

### T-02 — Pipeline lazy imports, fallback constants, and per-step try/except [SYNC]

**File**: `src/pipeline.py`

**Step 1** — Replace the three top-level agent imports with guarded imports:

```python
try:
    from src.agents.analyzer import analyzer_agent, RISK_MODEL_MAP as _RISK_MODEL_MAP
except ImportError:
    analyzer_agent = None
    _RISK_MODEL_MAP = None

try:
    from src.agents.reviewer import reviewer_agent
except ImportError:
    reviewer_agent = None

try:
    from src.agents.reporter import reporter_agent
except ImportError:
    reporter_agent = None
```

**Step 2** — Add fallback constants after the import block:

```python
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
```

**Step 3** — Wrap the Analyzer step:

```python
# Agent 1: Analyzer
try:
    metadata = get_pr_metadata(pr_url)
    metadata = metadata.model_copy(update={"diff": validate_diff(metadata.diff)})
    if analyzer_agent is None:
        raise ImportError("analyzer module not available")
    raw = _run_agent_json(analyzer_agent, str(metadata.model_dump()), "analyzer")
    classification = raw if not isinstance(raw, str) else PRClassification.model_validate_json(raw)
except Exception as exc:
    console.print(f"[yellow]⚠ Analyzer unavailable ({exc}); using medium-risk fallback.[/yellow]")
    if metadata is None:
        raise  # can't continue without metadata
    classification = _FALLBACK_CLASSIFICATION
    state.degraded = True
    state.agents_failed.append("analyzer")
state.metadata = metadata
state.classification = classification
```

Note: if `get_pr_metadata` itself fails (no metadata at all), we still re-raise — the pipeline cannot proceed without any PR content.

**Step 4** — Wrap the Reviewer step:

```python
# Agent 2: Reviewer
try:
    from agno.models.litellm import LiteLLM
    risk_map = _RISK_MODEL_MAP or {"low": "anthropic/claude-haiku-4-5-20251001",
                                   "medium": "anthropic/claude-sonnet-4-6",
                                   "high": "anthropic/claude-opus-4-8"}
    model_id = risk_map[state.classification.risk_level.value]
    if reviewer_agent is None:
        raise ImportError("reviewer module not available")
    reviewer_agent.model = LiteLLM(id=model_id, top_p=None, temperature=1)
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
```

**Step 5** — Wrap the Reporter step:

```python
# Agent 3: Reporter
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
```

The HITL gate and GitHub post remain entirely unchanged.

---

### T-03 — Analyzer standalone entrypoint [ASYNC]

**File**: `src/agents/analyzer.py`

Add at the bottom of the file:

```python
def run_standalone(payload: dict) -> dict:
    from src.models import PRMetadata
    metadata = PRMetadata.model_validate(payload)
    result = _agent_singleton.run(str(metadata.model_dump()))
    content = result.content
    if isinstance(content, str):
        import json
        return json.loads(content)
    return content.model_dump()


if __name__ == "__main__":
    import json, sys
    try:
        payload = json.load(sys.stdin)
        output = run_standalone(payload)
        print(json.dumps(output, indent=2))
    except (ValueError, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
```

Note: the existing module-level `analyzer_agent` is used (renamed `_agent_singleton` is not needed — `run_standalone` can reference `analyzer_agent` directly).

**Input**: `PRMetadata` JSON on stdin
**Output**: `PRClassification` JSON on stdout

---

### T-04 — Reviewer standalone entrypoint [ASYNC]

**File**: `src/agents/reviewer.py`

Add at the bottom:

```python
def run_standalone(payload: dict) -> dict:
    from src.models import PRClassification, PRMetadata
    metadata = PRMetadata.model_validate(payload["metadata"])
    classification = PRClassification.model_validate(payload["classification"])
    standards_text = payload.get("standards", "(none)")
    prompt = (
        f"Metadata: {metadata.model_dump_json()}\n"
        f"Classification: {classification.model_dump_json()}\n"
        f"Applicable Standards:\n{standards_text}"
    )
    result = reviewer_agent.run(prompt)
    content = result.content
    if isinstance(content, str):
        import json
        return json.loads(content)
    return content.model_dump()


if __name__ == "__main__":
    import json, sys
    try:
        payload = json.load(sys.stdin)
        output = run_standalone(payload)
        print(json.dumps(output, indent=2))
    except (ValueError, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
```

**Input**: `{"metadata": {...}, "classification": {...}, "standards": "..."}` JSON on stdin
**Output**: `ReviewFindings` JSON on stdout

---

### T-05 — Reporter standalone entrypoint [ASYNC]

**File**: `src/agents/reporter.py`

Add at the bottom:

```python
def run_standalone(payload: dict) -> str:
    from src.models import PRMetadata, ReviewFindings
    metadata = PRMetadata.model_validate(payload["metadata"])
    findings = ReviewFindings.model_validate(payload["findings"])
    run_id = payload.get("run_id", "standalone")
    cost_usd = float(payload.get("cost_usd", 0.0))
    prompt = (
        f"Metadata: {metadata.model_dump_json()}\n"
        f"Findings: {findings.model_dump_json()}\n"
        f"Run ID: {run_id}\n"
        f"Cost USD: {cost_usd:.4f}"
    )
    result = reporter_agent.run(prompt)
    return result.content


if __name__ == "__main__":
    import json, sys
    try:
        payload = json.load(sys.stdin)
        output = run_standalone(payload)
        print(output)
    except (ValueError, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
```

**Input**: `{"metadata": {...}, "findings": {...}, "run_id": "...", "cost_usd": 0.0}` JSON on stdin
**Output**: Formatted markdown comment string on stdout

---

### T-06 — Degradation tests [SYNC]

**File**: `tests/test_pipeline.py` — append three new test classes

**`TestAnalyzerDegradation`**:
- `test_analyzer_failure_uses_medium_fallback`: Mock `analyzer_agent.run` to raise `RuntimeError`. Assert `state.classification.risk_level == RiskLevel.MEDIUM`, `state.degraded is True`, `"analyzer" in state.agents_failed`, `state.error is None`.
- `test_analyzer_none_uses_medium_fallback`: Patch `src.pipeline.analyzer_agent` to `None`. Same assertions.
- `test_analyzer_failure_still_reaches_hitl`: Mock approval gate captures call. Assert it was called even after Analyzer failure.

**`TestReviewerDegradation`**:
- `test_reviewer_failure_uses_placeholder_findings`: Mock `reviewer_agent.run` to raise `RuntimeError`. Assert `state.findings.verdict == "comment"`, `state.findings.confidence == 0.0`, `state.degraded is True`, `"reviewer" in state.agents_failed`.
- `test_reviewer_failure_draft_comment_is_not_none`: Assert `state.draft_comment` is not None (Reporter still ran).
- `test_reviewer_failure_hitl_reached`: Assert approval gate was called.

**`TestReporterDegradation`**:
- `test_reporter_failure_uses_raw_findings`: Mock `reporter_agent.run` to raise `RuntimeError`. Assert `state.draft_comment` contains `"Reporter Unavailable"` and `state.degraded is True`.
- `test_reporter_failure_hitl_reached`: Assert approval gate was called with a non-None draft.
- `test_reporter_failure_can_post_fallback`: Set approval=True; assert `state.posted_comment_url` is not None (the fallback draft was posted).

---

### T-07 — Standalone subprocess tests [ASYNC]

**File**: `tests/test_agents_standalone.py` (new file)

Three test classes using `subprocess.run`:

```python
class TestAnalyzerStandalone:
    def test_valid_input_returns_classification(self):
        # Feed a PRMetadata JSON fixture to `python -m src.agents.analyzer`
        # Assert exit code 0 and stdout parses to PRClassification

class TestReviewerStandalone:
    def test_valid_input_returns_findings(self):
        # Feed {metadata, classification, standards} JSON to `python -m src.agents.reviewer`
        # Assert exit code 0 and stdout parses to ReviewFindings

class TestReporterStandalone:
    def test_valid_input_returns_comment_string(self):
        # Feed {metadata, findings, run_id, cost_usd} JSON to `python -m src.agents.reporter`
        # Assert exit code 0 and stdout is non-empty string
```

Note: these tests make real LLM calls. Mark with `@pytest.mark.integration` so they are excluded from the default `pytest` run (which only runs unit tests). They run in CI with `pytest -m integration`.
