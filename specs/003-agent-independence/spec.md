# Feature Specification: Agent Independence and Graceful Degradation

**Feature Branch**: `003-agent-independence`

**Created**: 2026-06-26

**Status**: Draft

**Input**: Each agent in the PR review pipeline must be independently executable as a standalone component — removing any single agent must cause graceful degradation, not complete pipeline failure.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Run a Single Agent in Isolation (Priority: P1)

An operator wants to test or debug one specific agent (Analyzer, Reviewer, or Reporter) without running the full pipeline. They invoke the agent directly with a JSON input file and receive the agent's structured output, without needing the other agents to be present or functioning.

**Why this priority**: This is the foundation for all graceful-degradation behavior and is also the most valuable developer tool — enabling rapid iteration, unit-level debugging, and the ability to replay a specific agent step from a LangFuse trace.

**Independent Test**: Invoke each agent as a standalone command with a valid input payload and verify it returns its expected output structure — with no other agent or pipeline component required.

**Acceptance Scenarios**:

1. **Given** a valid PR metadata JSON payload, **When** the Analyzer is invoked standalone, **Then** it returns a valid risk classification with `risk_level`, `change_types`, and `risk_rationale` fields.
2. **Given** a valid classification and metadata payload, **When** the Reviewer is invoked standalone, **Then** it returns a valid `ReviewFindings` structure with at least one finding.
3. **Given** valid findings and metadata, **When** the Reporter is invoked standalone, **Then** it returns a formatted draft comment string ready for terminal display.

---

### User Story 2 - Pipeline Continues When Analyzer is Unavailable (Priority: P2)

An operator runs the full pipeline, but the Analyzer agent fails (crashes, returns malformed output, or is removed from the codebase). Instead of the entire pipeline crashing, the system falls back to a default risk level (`medium`), logs a clear warning, and continues to the Reviewer step.

**Why this priority**: The Analyzer performs classification only — if it fails, the pipeline can still produce a useful review using a conservative default, preserving the core value of the system.

**Independent Test**: Trigger an Analyzer failure (e.g., by injecting a mock that raises an exception) and verify the pipeline emits a warning, uses `medium` risk, and delivers a complete review.

**Acceptance Scenarios**:

1. **Given** the Analyzer fails with an exception, **When** the pipeline runs, **Then** it logs a warning identifying the Analyzer as unavailable and proceeds with default risk `medium`.
2. **Given** the Analyzer returns malformed output, **When** the pipeline runs, **Then** it treats it as a failure, falls back to `medium`, and does not crash.

---

### User Story 3 - Pipeline Continues When Reviewer is Unavailable (Priority: P2)

An operator runs the pipeline, but the Reviewer agent fails. Instead of crashing, the pipeline produces a minimal placeholder review (stating that detailed review was unavailable), passes it to the Reporter, and completes the HITL gate normally.

**Why this priority**: The Reviewer is the core value-generator, so its absence degrades quality significantly — but the operator should still be able to see partial output and decide whether to post a caveat comment or abort.

**Independent Test**: Trigger a Reviewer failure (e.g., by injecting a mock that raises an exception) and verify a degraded-but-complete pipeline run that surfaces the fallback to the operator.

**Acceptance Scenarios**:

1. **Given** the Reviewer fails, **When** the pipeline runs, **Then** the Reporter receives a minimal placeholder `ReviewFindings` and generates a comment that notes the review was unavailable.
2. **Given** the Reviewer fails, **When** the HITL gate is reached, **Then** the operator sees the degraded draft and can choose to abort, preventing a misleading comment from being posted.

---

### User Story 4 - Pipeline Completes When Reporter is Unavailable (Priority: P3)

An operator runs the pipeline, but the Reporter agent fails. Instead of crashing, the pipeline prints the raw findings to the terminal as a fallback, presents them for HITL approval, and still allows the operator to post the unformatted output to GitHub.

**Why this priority**: The Reporter handles formatting only — losing it should degrade presentation quality, not prevent the review from reaching the operator.

**Independent Test**: Trigger a Reporter failure and verify the pipeline falls back to printing raw findings, still reaches the HITL gate, and allows posting.

**Acceptance Scenarios**:

1. **Given** the Reporter fails, **When** the pipeline runs, **Then** the raw `ReviewFindings` JSON is displayed in the terminal as the draft comment.
2. **Given** the Reporter fails and the operator approves, **When** the HITL gate passes, **Then** the raw findings are posted to GitHub as the PR comment.

---

### Edge Cases

- What happens when two agents fail simultaneously? The pipeline falls back at each stage independently; the final output may be fully degraded but the run still completes without an unhandled exception.
- What happens when a standalone agent receives malformed input? It validates input at the boundary and exits with a clear error message rather than silently producing invalid output.
- What if the fallback output itself triggers a LangFuse tracing error? Tracing errors must never cause pipeline failure — they are swallowed and warned.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Each agent MUST be independently invocable with a self-contained input payload, producing its output without requiring the pipeline or other agents to be present.
- **FR-002**: Each agent's standalone entrypoint MUST validate its input and emit a human-readable error if the input is invalid, exiting cleanly rather than raising an unhandled exception.
- **FR-003**: The pipeline MUST catch any exception raised by the Analyzer and continue with a default risk level of `medium`, emitting a warning to the operator.
- **FR-004**: The pipeline MUST catch any exception raised by the Reviewer and continue with a minimal placeholder `ReviewFindings`, emitting a warning to the operator.
- **FR-005**: The pipeline MUST catch any exception raised by the Reporter and fall back to displaying raw findings as the draft comment, emitting a warning to the operator.
- **FR-006**: All degradation warnings MUST identify which agent was unavailable and what fallback behavior was applied.
- **FR-007**: A degraded pipeline run MUST still reach the HITL gate, giving the operator the opportunity to review the degraded output before anything is posted to GitHub.
- **FR-008**: A degraded run MUST be recorded in the structured trace log with a `degraded: true` flag and an `agents_failed` list.
- **FR-009**: The existing HITL approval gate MUST NOT be bypassed by any degradation path.
- **FR-010**: Removing an agent module from the codebase MUST NOT cause an import-time crash in the pipeline — agent availability MUST be resolved at runtime, not at import time.

### Key Entities

- **Agent**: One of Analyzer, Reviewer, or Reporter — each with a defined input type, output type, and standalone entrypoint.
- **DegradedResult**: A fallback value produced when an agent fails — carries the fallback payload plus metadata (which agent failed, the exception message).
- **PipelineState**: The existing shared state object — extended to carry degradation metadata (`degraded`, `agents_failed`).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Each of the three agents can be invoked standalone and produce valid output within 30 seconds on a low-risk input, with no dependency on the other agents.
- **SC-002**: When any single agent is injected with a failure, the pipeline run completes (reaches `return state`) rather than raising an unhandled exception, 100% of the time.
- **SC-003**: In a degraded run, the operator receives a terminal warning within 2 seconds of the failure point, identifying the unavailable agent and the fallback applied.
- **SC-004**: A degraded run's structured trace log entry includes `degraded: true` and lists the failed agent name, making it distinguishable from a successful run in LangFuse.
- **SC-005**: All three degradation scenarios (Analyzer, Reviewer, Reporter unavailable) are covered by automated tests that pass without network or LLM calls.

## Assumptions

- The three agents are Analyzer, Reviewer, and Reporter — the pipeline has exactly these three, matching the current codebase.
- Standalone invocation is terminal-first (CLI input/output), not an HTTP API — consistent with the project's "terminal-first" scope constraint.
- The fallback risk level when the Analyzer fails is `medium` (conservative but not maximally expensive) — this can be overridden via an environment variable in a future iteration.
- LangFuse tracing is treated as best-effort: tracing failures must never block pipeline execution or degradation paths.
- The existing Pydantic I/O models (`PRClassification`, `ReviewFindings`, `PipelineState`) are not changed in shape — only extended with optional degradation fields.
