# Data Model: Agent Independence and Graceful Degradation

**Feature**: 003-agent-independence | **Date**: 2026-06-26

## Changes to Existing Models

### `PipelineState` — Extended (`src/models.py`)

Two new fields added at the end; all existing fields unchanged.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `degraded` | `bool` | `False` | True if any agent step fell back to a default value |
| `agents_failed` | `list[str]` | `[]` | Names of agents that failed (e.g. `["analyzer"]`) |

No other model changes. `PRClassification`, `ReviewFindings`, `PRMetadata`, `ReviewFinding`, `RiskLevel`, `ChangeType` are all unchanged.

---

## Fallback Values (constants in `src/pipeline.py`)

These are not Pydantic models — they are module-level constants used as default return values when an agent fails.

### `_FALLBACK_CLASSIFICATION: PRClassification`

```
risk_level    = RiskLevel.MEDIUM
change_types  = [ChangeType.FEATURE]
risk_rationale = "Analyzer unavailable — defaulting to medium risk"
model_to_use  = "anthropic/claude-sonnet-4-6"
files_of_concern = []
```

### `_FALLBACK_FINDINGS: ReviewFindings`

```
summary   = "Reviewer unavailable — automated review could not be completed."
findings  = []
verdict   = "comment"
confidence = 0.0
```

### `_reporter_fallback(findings: ReviewFindings) -> str`

A function (not a constant) that formats the findings as a fenced JSON block for use as the draft comment when the Reporter fails:

```
## ⚠️ Reporter Unavailable

The Reporter agent failed. Raw findings are shown below.

```json
{findings.model_dump_json(indent=2)}
```
```

---

## Agent Standalone Input/Output Contracts

Each agent's `run_standalone` function accepts and returns plain Python dicts (JSON-serializable). Pydantic validation happens inside `run_standalone`.

### Analyzer (`src/agents/analyzer.py`)

**Input** (stdin JSON, validated against `PRMetadata`):
```json
{
  "url": "https://github.com/owner/repo/pull/N",
  "repo": "owner/repo",
  "pr_number": 1,
  "title": "...",
  "description": "...",
  "diff": "...",
  "files_changed": ["file.py"],
  "lines_added": 10,
  "lines_removed": 2
}
```

**Output** (stdout JSON, validated against `PRClassification`):
```json
{
  "risk_level": "low|medium|high",
  "change_types": ["feature"],
  "risk_rationale": "...",
  "model_to_use": "anthropic/...",
  "files_of_concern": []
}
```

---

### Reviewer (`src/agents/reviewer.py`)

**Input** (stdin JSON):
```json
{
  "metadata": { ...PRMetadata fields... },
  "classification": { ...PRClassification fields... },
  "standards": "...text of applicable standards..."
}
```

**Output** (stdout JSON, validated against `ReviewFindings`):
```json
{
  "summary": "...",
  "findings": [...],
  "verdict": "approve|request_changes|comment",
  "confidence": 0.9
}
```

---

### Reporter (`src/agents/reporter.py`)

**Input** (stdin JSON):
```json
{
  "metadata": { ...PRMetadata fields... },
  "findings": { ...ReviewFindings fields... },
  "run_id": "uuid",
  "cost_usd": 0.012
}
```

**Output** (stdout plain text — the formatted markdown comment string):
```
## PR Review: <title>
...
```

---

## Trace Log Schema (extended)

`log_structured_trace` serializes `PipelineState` as JSON. With the new fields, a degraded run trace entry will include:

```json
{
  "run_id": "...",
  "pr_url": "...",
  "degraded": true,
  "agents_failed": ["analyzer"],
  "classification": { "risk_level": "medium", "risk_rationale": "Analyzer unavailable..." },
  ...
}
```

A successful run will have `"degraded": false, "agents_failed": []`.
