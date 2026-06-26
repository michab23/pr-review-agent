# Research: Agent Independence and Graceful Degradation

**Feature**: 003-agent-independence | **Date**: 2026-06-26

## Decision 1: Lazy Import Strategy

**Decision**: Use module-level `try/except ImportError` guards for each agent import in `pipeline.py`, assigning `None` as the sentinel when the module is absent.

```python
try:
    from src.agents.analyzer import analyzer_agent, RISK_MODEL_MAP
except ImportError:
    analyzer_agent = None
    RISK_MODEL_MAP = None
```

**Rationale**: This is the minimum change that satisfies FR-010 ("import-time crash must not occur when a module is removed"). It keeps the import structure readable and lets IDEs/type checkers still resolve the symbols in normal operation. The sentinel `None` is explicit and forces the per-step `try/except` to handle the missing-agent case.

**Alternatives considered**:
- `importlib.import_module` inside each pipeline step — more flexible, but verbose and unusual for this codebase's style.
- Dependency injection / registry pattern — architecturally cleaner but introduces an abstraction that the codebase does not yet need (Simplicity First principle).

---

## Decision 2: Per-Step `try/except` with Explicit Fallbacks

**Decision**: Wrap each of the three agent invocations in `pipeline.py` in a `try/except Exception` block that catches both `ImportError` (agent removed) and runtime errors (agent throws). On failure, set a pre-defined fallback value and append the agent name to `state.agents_failed`.

**Fallback values**:
| Agent | Fallback value |
|-------|---------------|
| Analyzer | `PRClassification(risk_level=RiskLevel.MEDIUM, change_types=[ChangeType.FEATURE], risk_rationale="Analyzer unavailable — defaulting to medium risk", model_to_use="anthropic/claude-sonnet-4-6", files_of_concern=[])` |
| Reviewer | `ReviewFindings(summary="Reviewer unavailable — automated review could not be completed.", findings=[], verdict="comment", confidence=0.0)` |
| Reporter | Raw `state.findings.model_dump_json(indent=2)` wrapped in a markdown code block as the draft comment |

**Rationale**: Each fallback is conservative (medium risk, no findings, raw dump) so the operator always sees the worst-case assumption. The HITL gate still fires, giving the operator the chance to abort before posting a degraded comment.

**Alternatives considered**:
- Re-raising after logging — violates the graceful-degradation requirement.
- Returning early without HITL — violates FR-009 (HITL must not be bypassed).

---

## Decision 3: Standalone Entrypoint Pattern

**Decision**: Add a `run_standalone(payload: dict) -> dict` function to each agent module, plus a `if __name__ == "__main__":` block that reads JSON from `stdin`, calls `run_standalone`, and writes JSON to `stdout`.

`run_standalone` in each module:
1. Validates the input payload against the expected Pydantic input model
2. Constructs the agent prompt (identical logic to what `pipeline.py` uses)
3. Runs the agent
4. Returns the output as a dict

**Rationale**: Co-locating the standalone entrypoint with the agent keeps each module self-contained. The `run_standalone` function also serves as the canonical "how to call this agent" reference, removing duplication between the pipeline and any future test or replay harness.

**Alternatives considered**:
- Separate `src/cli/` entry scripts — adds indirection without benefit for a three-agent project.
- `argparse`-based CLI with file paths — more ergonomic for operators, but stdin/stdout JSON is simpler and pipeline-friendly (can be piped). A `--file` flag can be added later if needed.

---

## Decision 4: `PipelineState` Extension

**Decision**: Add two optional fields to `PipelineState`:
- `degraded: bool = False`
- `agents_failed: list[str] = []`

These are set by the pipeline when any agent step falls back. `log_structured_trace` already serializes the whole `PipelineState`, so degradation info flows into the trace automatically.

**Rationale**: Minimal change; no existing fields modified; Pydantic defaults ensure backward compatibility with all existing tests. The `degraded` flag gives LangFuse a single boolean to filter degraded runs.

**Alternatives considered**:
- Separate `DegradedResult` wrapper type — adds a layer of indirection with no benefit; `agents_failed: list[str]` is sufficient to capture which agents failed.

---

## Decision 5: Test Strategy

**Decision**: Add three new test classes to `tests/test_pipeline.py` (one per degradation scenario). Each uses `patch` to inject a side-effect exception into the relevant agent's `.run()` method (or set the agent sentinel to `None`), then asserts:
1. `state.degraded is True`
2. The failed agent's name appears in `state.agents_failed`
3. `state.error is None` (pipeline completed without unhandled exception)
4. The HITL gate was reached (mock is called)

Standalone entrypoint tests live in `tests/test_agents_standalone.py`, using `subprocess` to call `python -m src.agents.analyzer` etc. with a JSON fixture on stdin, and asserting the output parses to the expected Pydantic model.

**Rationale**: Using `subprocess` for standalone tests mirrors real usage and catches import/path issues that in-process patching would miss. The degradation tests stay in the existing `test_pipeline.py` file to keep all pipeline behavior in one place.
