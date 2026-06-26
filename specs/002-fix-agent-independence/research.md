# Research: Fix Agent Independence Constraint

**Phase**: 0 — Outline & Research
**Date**: 2026-06-26

## Research Question

What is the correct wording for the architectural constraint on agent independence, grounded in the course's multi-agent design principles?

---

## Finding 1 — Multi-Agent Pattern: Fault Isolation

**Source**: `/home/michael/dev/agentic-sdlc-wiki/wiki/concepts/multi-agent-pattern.md`

**Relevant excerpt**:
> **Fault Isolation**: one agent failing doesn't necessarily fail the whole system

> **Compositional Flexibility**: combine agents in new ways for new tasks

**Decision**: The correct constraint is *fault isolation* — not hard coupling. The pipeline must tolerate the absence of any single agent.

**Alternatives considered**:
- Keep original constraint ("must break") — rejected: contradicts Fault Isolation principle
- Soft language ("should work standalone") — rejected: too weak; must be a requirement, not a suggestion
- No constraint at all — rejected: we still need the minimum agent count requirement

---

## Finding 2 — Sequential Workflow Pattern: Reusable Components

**Source**: `/home/michael/dev/agentic-sdlc-wiki/wiki/concepts/sequential-workflow-pattern.md`

**Relevant excerpt**:
> **Reusable components** — Clear separation of concerns. Easy to debug (each step is isolated).

**Decision**: Each step (agent) must be independently testable and debuggable. This supports the "standalone executable" requirement.

---

## Finding 3 — Lesson 6: Multi-Agent Pitfalls

**Source**: `/home/michael/dev/agentic-sdlc-wiki/wiki/lessons/06-agentic-workflows.md`

**Relevant excerpt**:
> **Multi-agent pitfalls**: Complexity Explosion, Cascading Failures, Context Fragmentation, Runaway Costs, Non-Determinism, Latency Chains, Orchestration Deadlocks. Principle: *"Start with the simplest architecture that could work."*

**Decision**: The original constraint actively invited **Cascading Failures** (one agent removal → whole pipeline down). The corrected constraint eliminates this pitfall by design.

---

## Resolved Wording

**Original (incorrect)**:
> Minimum 3 agents, each with a single defined role; removing any one agent must break the pipeline

**Corrected**:
> Minimum 3 agents, each with a single defined role; every agent must be independently executable as a standalone component — removing any single agent must cause graceful degradation, not complete pipeline failure

**Rationale**:
- Preserves the minimum agent count requirement (3 agents, single defined role)
- Explicitly requires standalone executability
- Uses "graceful degradation" (standard fault-tolerance term) vs. "complete pipeline failure"
- Directly inverts the original error without ambiguity
- Consistent with Fault Isolation (multi-agent-pattern) and Reusable Components (sequential-workflow-pattern)
