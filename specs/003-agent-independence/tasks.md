# Tasks: Agent Independence and Graceful Degradation

**Input**: Design documents from `specs/003-agent-independence/`

**Branch**: `003-agent-independence` | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

**Organization**: Tasks grouped by user story to enable independent implementation and testing.

## Format: `[ID] [P?] [SYNC/ASYNC] [Story?] Description`

- **[P]**: Can run in parallel (different files, no blocking dependencies)
- **[SYNC]**: Requires human review (safety-critical, multi-component, design decisions)
- **[ASYNC]**: Well-defined and delegatable (clear spec, isolated file, standard pattern)
- **[USx]**: Maps to user story from spec.md

---

## Phase 1: Setup

**Purpose**: No new project infrastructure needed — this feature adds to an existing project.

*(No tasks — project is already initialized with Python, pytest, Pydantic, and all dependencies.)*

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Data model extension that ALL user stories depend on.

**⚠️ CRITICAL**: Phase 3 and Phase 4 cannot start until T001 is complete.

- [ ] T001 [SYNC] Extend `PipelineState` in `src/models.py`: add `degraded: bool = False` and `agents_failed: list[str] = []` fields at the end of the class (plan.md T-01)

**Checkpoint**: `PipelineState` carries degradation metadata. All downstream phases can proceed.

---

## Phase 3: User Story 1 — Standalone Agent Entrypoints (Priority: P1) 🎯 MVP

**Goal**: Each of the three agents can be invoked in isolation, reading JSON from stdin and writing JSON/text to stdout, with no dependency on the pipeline or other agents.

**Independent Test**: Run `echo '<PRMetadata JSON>' | python -m src.agents.analyzer` and verify a valid `PRClassification` JSON is printed to stdout; repeat for reviewer and reporter.

### Implementation

- [ ] T002 [P] [ASYNC] [US1] Add `run_standalone(payload: dict) -> dict` function and `if __name__ == "__main__":` entrypoint to `src/agents/analyzer.py` — reads `PRMetadata` JSON from stdin, emits `PRClassification` JSON to stdout (plan.md T-03)

- [ ] T003 [P] [ASYNC] [US1] Add `run_standalone(payload: dict) -> dict` function and `if __name__ == "__main__":` entrypoint to `src/agents/reviewer.py` — reads `{"metadata": {...}, "classification": {...}, "standards": "..."}` JSON from stdin, emits `ReviewFindings` JSON to stdout (plan.md T-04)

- [ ] T004 [P] [ASYNC] [US1] Add `run_standalone(payload: dict) -> str` function and `if __name__ == "__main__":` entrypoint to `src/agents/reporter.py` — reads `{"metadata": {...}, "findings": {...}, "run_id": "...", "cost_usd": 0.0}` JSON from stdin, emits formatted markdown comment string to stdout (plan.md T-05)

- [ ] T005 [ASYNC] [US1] Create `tests/test_agents_standalone.py` with three `@pytest.mark.integration` test classes (`TestAnalyzerStandalone`, `TestReviewerStandalone`, `TestReporterStandalone`) that use `subprocess.run` to invoke each agent via `python -m src.agents.<name>` with a JSON fixture on stdin. Each class must contain **two** test methods: (1) `test_valid_input_returns_output` — feed a valid fixture, assert exit code 0 and stdout parses to the expected Pydantic model; (2) `test_invalid_input_exits_with_error` — feed `"{}"` (empty JSON object, fails Pydantic validation), assert exit code 1 and stderr is non-empty. (plan.md T-07; covers FR-001 and FR-002). Depends on T002, T003, T004.

**Checkpoint**: Each agent independently executable. Verify with `echo '<fixture>' | python -m src.agents.analyzer`.

---

## Phase 4: User Stories 2, 3, 4 — Pipeline Graceful Degradation (Priority: P2/P3)

**Goal**: The pipeline catches agent failures, falls back to defined defaults, warns the operator, and always reaches the HITL gate — never raising an unhandled exception.

**Independent Test**: Inject a `RuntimeError` into each agent's `.run()` mock and assert the pipeline returns a `PipelineState` with `degraded=True`, the failed agent in `agents_failed`, and `error=None`.

> Note: T006–T009 all modify `src/pipeline.py` and must run sequentially.

### Implementation

- [ ] T006 [SYNC] [US2] Replace the three top-level agent imports in `src/pipeline.py` with guarded `try/except ImportError` imports (sentinel `None` on failure) and add module-level fallback constants `_FALLBACK_CLASSIFICATION`, `_FALLBACK_FINDINGS`, and helper `_reporter_fallback()` — see plan.md T-02 Step 1 and Step 2. Depends on T001.

- [ ] T007 [SYNC] [US2] Wrap the Analyzer step in `src/pipeline.py` in `try/except Exception`: on failure emit a Rich warning, set `classification = _FALLBACK_CLASSIFICATION`, append `"analyzer"` to `state.agents_failed`, set `state.degraded = True`; re-raise only if `metadata` is `None` (cannot continue without PR content) — see plan.md T-02 Step 3. Depends on T006.

- [ ] T008 [SYNC] [US3] Wrap the Reviewer step in `src/pipeline.py` in `try/except Exception`: on failure emit a Rich warning, set `findings = _FALLBACK_FINDINGS`, append `"reviewer"` to `state.agents_failed`, set `state.degraded = True` — see plan.md T-02 Step 4. Depends on T007.

- [ ] T009 [SYNC] [US4] Wrap the Reporter step in `src/pipeline.py` in `try/except Exception`: on failure emit a Rich warning, set `state.draft_comment = _reporter_fallback(state.findings)`, append `"reporter"` to `state.agents_failed`, set `state.degraded = True` — see plan.md T-02 Step 5. Depends on T008.

### Tests

> Note: T010–T012 all append to `tests/test_pipeline.py` and must run sequentially.

- [ ] T010 [SYNC] [US2] Add `TestAnalyzerDegradation` test class to `tests/test_pipeline.py` with **four** test methods: `test_analyzer_failure_uses_medium_fallback`, `test_analyzer_none_uses_medium_fallback`, `test_analyzer_failure_still_reaches_hitl`, `test_analyzer_failure_warning_identifies_agent` — the last method patches `src.pipeline.console.print` (or uses `capsys`) and asserts the warning string contains `"analyzer"` and `"medium"` (covers FR-006). See plan.md T-06. Depends on T007.

- [ ] T011 [SYNC] [US3] Add `TestReviewerDegradation` test class to `tests/test_pipeline.py` with **four** test methods: `test_reviewer_failure_uses_placeholder_findings`, `test_reviewer_failure_draft_comment_is_not_none`, `test_reviewer_failure_hitl_reached`, `test_reviewer_failure_warning_identifies_agent` — the last method asserts the warning string contains `"reviewer"` (covers FR-006). See plan.md T-06. Depends on T008, T010.

- [ ] T012 [SYNC] [US4] Add `TestReporterDegradation` test class to `tests/test_pipeline.py` with **four** test methods: `test_reporter_failure_uses_raw_findings`, `test_reporter_failure_hitl_reached`, `test_reporter_failure_can_post_fallback`, `test_reporter_failure_warning_identifies_agent` — the last method asserts the warning string contains `"reporter"` (covers FR-006). See plan.md T-06. Depends on T009, T011.

- [ ] T010b [SYNC] [US2] Add `TestDegradedTraceLog` test class to `tests/test_pipeline.py` that calls `log_structured_trace` directly with a `PipelineState` where `degraded=True` and `agents_failed=["analyzer"]`, then reads the written JSON and asserts both fields appear in the output (covers FR-008 / SC-004). Use the real `log_structured_trace` (no mock) against a tmp path. Depends on T010.

**Checkpoint**: Run `pytest tests/test_pipeline.py` — all existing tests plus 13 new tests (4+4+4+1) should pass.

---

## Phase 5: Polish & Cross-Cutting Concerns

**Purpose**: Final validation and cleanup after all user stories are complete.

- [ ] T013 [P] [ASYNC] Update the comment at the top of `src/pipeline.py` (line 1) to reference the new plan — change `spec/spec.md §4` reference to note graceful degradation behavior

- [ ] T014 [SYNC] Run full test suite (`uv run pytest`) and verify no regressions in existing tests (`TestExtractJson`, `TestRunAgentJson`, `TestHumanApprovalGate`, `TestPipelineRun`). Fix any failures before declaring the feature complete.

**Checkpoint**: All tests pass. Feature complete.

---

## Dependencies & Execution Order

### Phase Dependencies

```
Phase 2 (T001)
    └── Phase 3 (T002, T003, T004 in parallel → T005)
    └── Phase 4 (T006 → T007 → T008 → T009, tests T010 → T011 → T012)
        └── Phase 5 (T013 in parallel, T014 last)
```

### User Story Dependencies

- **US1 (P1)**: Depends only on Phase 2 (T001). T002/T003/T004 are independent of each other ([P]).
- **US2 (P2)**: Depends on Phase 2 (T001). T006 and T007 must run before T010.
- **US3 (P2)**: Depends on US2 completion (T007 must exist before T008 to avoid pipeline.py conflicts).
- **US4 (P3)**: Depends on US3 completion (same reason — all in pipeline.py).

### Within Phase 4

- T006 → T007 → T008 → T009 are sequential (all in `src/pipeline.py`)
- T010, T011, T012 are sequential (all append to `tests/test_pipeline.py`)
- T010 can start after T007, T011 after T008, T012 after T009

### Parallel Opportunities

```bash
# After T001 completes, start Phase 3 and Phase 4 in parallel:
# Phase 3 — US1 standalone entrypoints (entirely independent of pipeline.py changes):
Task T002: src/agents/analyzer.py
Task T003: src/agents/reviewer.py   # parallel with T002
Task T004: src/agents/reporter.py   # parallel with T002, T003

# Phase 4 — starts with T006 (pipeline.py) in parallel with Phase 3:
Task T006: lazy imports + fallback constants in src/pipeline.py
```

---

## Implementation Strategy

### MVP (User Story 1 Only)

1. Complete **Phase 2** (T001) — 5 min
2. Complete **Phase 3** (T002–T005) — standalone entrypoints for all 3 agents
3. **STOP and VALIDATE**: Run each agent with `echo '...' | python -m src.agents.<name>` — each should produce valid output
4. **Demo-ready**: Agents are independently executable ✓

### Full Feature (All User Stories)

1. Complete Phase 2 → Phase 3 → Phase 4 → Phase 5
2. Each phase has a checkpoint — validate before moving on
3. Phase 3 and Phase 4 can proceed in parallel after Phase 2 (different files)

---

## Notes

- All 9 degradation test cases (T010–T012) require no LLM calls — use mocks only
- The 3 standalone tests (T005) are marked `@pytest.mark.integration` — they make real LLM calls and are excluded from default `pytest` run
- `pipeline.py` changes (T006–T009) must be sequential — verify existing tests pass after each step
- The HITL gate code (`human_approval_gate`) is never modified — it must remain reachable from all degradation paths
