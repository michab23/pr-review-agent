# Tasks: Fix Agent Independence Constraint

**Input**: Design documents from `specs/002-fix-agent-independence/`

**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅

**Organization**: Three user stories all resolved by a single targeted edit to `spec/mission-brief.md`. Tasks are grouped accordingly.

## Format: `[ID] [P?] [SYNC/ASYNC] [Story?] Description`

- **[SYNC]**: Requires human review
- **[ASYNC]**: Can be delegated to async agent
- **[P]**: Can run in parallel (no file conflicts)
- **[US1/US2/US3]**: User story label from spec.md

---

## Phase 1: Apply the Correction (US1 · US2 · US3)

**Goal**: Replace the incorrect architectural constraint in `spec/mission-brief.md`

**All three user stories are satisfied by this single edit:**
- US1 (Architect reads corrected constraint): text is now accurate
- US2 (Developer runs single agent standalone): requirement is now explicit
- US3 (QA validates fault isolation): graceful degradation is now mandated

**Independent Test**: Read `spec/mission-brief.md` Architecture section — the bullet must contain "independently executable" and "graceful degradation", and must NOT contain "must break the pipeline"

- [x] T001 [SYNC] [US1][US2][US3] Edit `spec/mission-brief.md` — in the Architecture section, replace the bullet:
  - **FROM**: `removing any one agent must break the pipeline`
  - **TO**: `every agent must be independently executable as a standalone component — removing any single agent must cause graceful degradation, not complete pipeline failure`
  - Full bullet after change: `Minimum 3 agents, each with a single defined role; every agent must be independently executable as a standalone component — removing any single agent must cause graceful degradation, not complete pipeline failure`

**Checkpoint**: Single edit applied — proceed to validation

---

## Phase 2: Validate Against Success Criteria

**Goal**: Confirm all four success criteria from spec.md are met

- [x] T002 [SYNC] [US1] Verify SC-001 — a developer reading the Architecture section can answer "can each agent run standalone?" with "yes" without additional context (`spec/mission-brief.md`)
- [x] T003 [SYNC] [US1] Verify SC-002 — confirm the phrase "removing any one agent must break the pipeline" (or logical equivalent) no longer appears anywhere in `spec/mission-brief.md`
- [x] T004 [SYNC] [US2] Verify SC-003 — confirm the updated bullet contains "independently executable" and "graceful degradation" (`spec/mission-brief.md`)
- [x] T005 [SYNC] [US3] Verify SC-004 — run `diff` of updated file against original; confirm only the single constraint bullet differs and all other lines are byte-for-byte identical

**Checkpoint**: All SC-001 through SC-004 verified ✅ — feature complete

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1**: No dependencies — can start immediately
- **Phase 2**: Depends on T001 completion

### Within Phase 1

- T001 is the only task — no parallelism needed

### Within Phase 2

- T002–T005 are independent validations — all can run in parallel after T001

---

## Parallel Opportunities

```bash
# After T001 completes, run all validations simultaneously:
Task T002: Verify SC-001 (standalone readability check)
Task T003: Verify SC-002 (absence of original text)
Task T004: Verify SC-003 (presence of new terms)
Task T005: Verify SC-004 (diff check)
```

---

## Implementation Strategy

### MVP (only story P1)

1. Complete T001 — the single edit
2. Complete T002–T003 — verify SC-001 and SC-002 (core correctness)
3. **STOP and VALIDATE**: mission brief is correct

### Full delivery

1. T001 → T002 + T003 + T004 + T005 (all in parallel)
2. All three user stories verified ✅

---

## Notes

- No setup or foundational phase needed — this is a documentation correction
- All tasks are [SYNC] because the mission brief is a foundational project document requiring human sign-off on wording
- T002–T005 can be run in parallel (different validation checks, same read-only file)
- Exact corrected wording is in `research.md` (Finding 1 & 2 + Resolved Wording section)
