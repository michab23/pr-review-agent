# Implementation Plan: Fix Agent Independence Constraint

**Branch**: `002-fix-agent-independence` | **Date**: 2026-06-26 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/002-fix-agent-independence/spec.md`

## Summary

The project mission brief (`spec/mission-brief.md`) contains an incorrect architectural constraint that requires tight coupling between agents: *"removing any one agent must break the pipeline."* This is the opposite of the intended design. The correct constraint — grounded in the course's Multi-Agent Pattern wiki (Fault Isolation + Compositional Flexibility) — is that every agent must be independently executable as a standalone component, and removing any single agent must cause graceful degradation, not complete pipeline failure.

The implementation is a single targeted edit to one bullet point in `spec/mission-brief.md`. No code changes, no schema changes, no dependency updates.

## Technical Context

**Language/Version**: N/A — documentation correction only
**Primary Dependencies**: N/A
**Storage**: N/A — single markdown file edit
**Testing**: Manual diff verification against SC-001–SC-004 in spec
**Target Platform**: N/A
**Project Type**: Documentation correction
**Performance Goals**: N/A
**Constraints**: Only the Architecture bullet covering agent removal behavior is changed; all other lines in `spec/mission-brief.md` are unchanged (SC-004)
**Scale/Scope**: One file, one bullet point

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| Simplicity First | ✅ PASS | Change is one bullet point — cannot be simpler |
| Surgical Changes | ✅ PASS | Only the incorrect constraint line is touched; all adjacent text preserved |
| Think Before Coding | ✅ PASS | Wiki evidence reviewed; wording derived from Fault Isolation principle |
| Goal-Driven Execution | ✅ PASS | Success criteria SC-001–SC-004 are concrete and verifiable |
| Human Oversight | ✅ PASS | Mission brief is foundational — change classified [SYNC] for human review |
| Security by Default | N/A | No code or credentials involved |

*Note: `.specify/memory/constitution.md` is a placeholder template (project constitution not yet ratified). Evaluation performed against team-ai-directives constitution and team principles.*

**POST-DESIGN RE-CHECK**: No design artifacts introduce new violations. ✅

## Project Structure

### Documentation (this feature)

```text
specs/002-fix-agent-independence/
├── plan.md              # This file
├── research.md          # Phase 0 output (wording rationale)
├── checklists/
│   └── requirements.md  # Spec quality checklist
└── tasks.md             # Phase 2 output (via /spec-tasks)
```

### Source (only file touched)

```text
spec/
└── mission-brief.md     # Single bullet edit — Architecture section, line 17
```

## Triage Framework: [SYNC] vs [ASYNC] Classification

**Execution Strategy**: Single [SYNC] task — the mission brief is the foundational specification document for the entire project; even a trivial edit warrants human review before commit.

### Preliminary Task Classification

| Task Category | Estimated [SYNC] Tasks | Estimated [ASYNC] Tasks | Rationale |
|---------------|----------------------|----------------------|-----------|
| Documentation edit | 1 | 0 | High-visibility foundational doc; human sign-off required |

### Triage Audit Trail

| Task | Classification | Primary Criteria | Risk Level | Rationale |
|------|----------------|------------------|------------|-----------|
| Edit mission-brief.md constraint bullet | [SYNC] | High-visibility foundational document | Low | Change is trivial but the document it touches sets the entire project architecture — human must verify wording is correct before commit |
