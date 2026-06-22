# Data Model — Agentic PR Review Pipeline

> Canonical schema definitions with field constraints, validation rules, and example payloads.
> Source of truth: `src/models.py`. If this file and the code diverge, fix this file first.

---

## Enum Types

```python
class RiskLevel(str, Enum):
    LOW = "low"        # docs, config, trivial one-liners
    MEDIUM = "medium"  # features, refactors, non-auth logic
    HIGH = "high"      # auth, payments, data migrations, dependency bumps, security patches
```

```python
class ChangeType(str, Enum):
    FEATURE = "feature"
    BUG_FIX = "bug_fix"
    REFACTOR = "refactor"
    SECURITY = "security"       # always forces HIGH risk
    DOCS = "docs"
    CONFIG = "config"
    DEPENDENCY = "dependency"   # always forces at least MEDIUM risk
```

---

## Model: `PRMetadata`

Populated by `get_pr_metadata()` from the GitHub API. Passed unmodified to Analyzer and Reviewer.

```python
class PRMetadata(BaseModel):
    url: str                    # canonical PR URL (e.g. https://github.com/owner/repo/pull/42)
    repo: str                   # "owner/repo" — used for all subsequent API calls
    pr_number: int              # positive integer
    title: str                  # max 256 chars
    description: str            # PR body; may be empty string
    diff: str                   # raw unified diff; max 100KB enforced before this model is created
    files_changed: list[str]    # list of file paths present in the diff
    lines_added: int            # ≥ 0
    lines_removed: int          # ≥ 0
```

**Validation rules**:
- `diff` must not be empty string (reject PRs with no diff — nothing to review)
- `len(diff.encode()) <= 102_400` — enforced in `get_pr_metadata()` before model creation
- `files_changed` must be non-empty and must be derivable from the diff header lines

**Example payload**:
```json
{
  "url": "https://github.com/acme/api/pull/88",
  "repo": "acme/api",
  "pr_number": 88,
  "title": "Add user login endpoint",
  "description": "Implements POST /auth/login with JWT response.",
  "diff": "diff --git a/src/auth.py b/src/auth.py\n...",
  "files_changed": ["src/auth.py", "tests/test_auth.py"],
  "lines_added": 74,
  "lines_removed": 3
}
```

---

## Model: `PRClassification`

Output of the Analyzer agent. Drives model tier selection for the Reviewer.

```python
class PRClassification(BaseModel):
    risk_level: RiskLevel
    change_types: list[ChangeType]   # non-empty; may contain multiple
    risk_rationale: str              # one sentence; max 200 chars
    model_to_use: str                # one of the three Claude model IDs
    files_of_concern: list[str]      # subset of PRMetadata.files_changed that drove risk rating
```

**Risk → model routing** (enforced by Analyzer, validated by pipeline before Reviewer runs):

| `risk_level` | `model_to_use` (LiteLLM ID) |
|---|---|
| `low` | `anthropic/claude-haiku-4-5-20251001` |
| `medium` | `anthropic/claude-sonnet-4-6` |
| `high` | `anthropic/claude-opus-4-8` |

**Validation rules**:
- `model_to_use` must be one of the three values above — pipeline validates before calling Reviewer
- `change_types` must be non-empty
- `files_of_concern` must be a subset of `PRMetadata.files_changed`; any path not in the diff is rejected

**Example payload**:
```json
{
  "risk_level": "high",
  "change_types": ["feature", "security"],
  "risk_rationale": "New authentication endpoint in src/auth.py handles credentials and issues JWTs.",
  "model_to_use": "claude-opus-4-8",
  "files_of_concern": ["src/auth.py"]
}
```

---

## Model: `ReviewFinding`

A single issue found by the Reviewer. One entry per distinct problem.

```python
class ReviewFinding(BaseModel):
    severity: Literal["critical", "warning", "suggestion"]
    file: str                        # must exist in PRMetadata.files_changed
    line_range: Optional[str]        # "42-51" | "88" | None (for file-level findings)
    issue: str                       # what's wrong; max 500 chars; must be specific
    standard_cited: Optional[str]    # which team standard is violated; None if no standard applies
    suggestion: str                  # concrete fix; max 500 chars; must be actionable
```

**Severity definitions**:
- `critical` — must be fixed before merge (security flaw, data corruption risk, broken test)
- `warning` — should be fixed (standards violation, maintainability concern)
- `suggestion` — optional improvement (style, readability, minor efficiency)

**Validation rules**:
- `file` must appear in `PRMetadata.files_changed` — Reporter rejects any finding that doesn't
- `issue` and `suggestion` must be non-empty strings (no vague entries)
- `line_range` format: `"\d+"` or `"\d+-\d+"` if provided

**Example payload**:
```json
{
  "severity": "critical",
  "file": "src/auth.py",
  "line_range": "34-36",
  "issue": "Password is hashed with MD5 (line 35), which is cryptographically broken and trivially reversible with rainbow tables.",
  "standard_cited": "security.md § Password Handling: Use bcrypt or argon2 with a work factor ≥ 12.",
  "suggestion": "Replace `hashlib.md5(password).hexdigest()` with `bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12))`."
}
```

---

## Model: `ReviewFindings`

Full output of the Reviewer agent. Contains the summary, all findings, and an overall verdict.

```python
class ReviewFindings(BaseModel):
    summary: str              # 1–3 sentences; overall assessment of the PR
    findings: list[ReviewFinding]   # may be empty (clean PR → approve)
    verdict: Literal["approve", "request_changes", "comment"]
    confidence: float         # 0.0–1.0; < 0.7 adds a HITL note to the draft comment
```

**Verdict rules** (enforced by Reviewer system prompt + Reporter validation):
- `approve` → `findings` must be empty or contain only `suggestion` severity items
- `request_changes` → `findings` must contain at least one `critical` or `warning`
- `comment` → findings present but Reviewer is uncertain; defers full judgment to human

**Example payload**:
```json
{
  "summary": "This PR adds a login endpoint but has a critical security flaw in password hashing and missing input validation. Approve after fixes.",
  "findings": [
    {
      "severity": "critical",
      "file": "src/auth.py",
      "line_range": "34-36",
      "issue": "Password hashed with MD5...",
      "standard_cited": "security.md § Password Handling",
      "suggestion": "Use bcrypt..."
    }
  ],
  "verdict": "request_changes",
  "confidence": 0.95
}
```

---

## Model: `PipelineState`

Plain Pydantic model — not a LangGraph state dict. Created at pipeline entry and passed to each Agno agent in sequence. Each agent reads what it needs and writes its output field.

```python
class PipelineState(BaseModel):
    # ── Input (set at pipeline entry) ──────────────────────────────
    pr_url: str
    run_id: str                          # uuid4, generated at startup

    # ── Set by Analyzer ────────────────────────────────────────────
    metadata: Optional[PRMetadata] = None
    classification: Optional[PRClassification] = None

    # ── Set by Reviewer ────────────────────────────────────────────
    findings: Optional[ReviewFindings] = None

    # ── Set by Reporter ────────────────────────────────────────────
    draft_comment: Optional[str] = None
    human_approved: Optional[bool] = None
    posted_comment_url: Optional[str] = None

    # ── Observability (updated by each agent) ──────────────────────
    total_cost_usd: float = 0.0
    error: Optional[str] = None          # first error message if pipeline aborts
```

**Field ownership** (no agent writes another agent's fields):

| Field | Written by | Read by |
|---|---|---|
| `pr_url` | Pipeline entry | Analyzer |
| `run_id` | Pipeline entry | All agents (for LangFuse span tagging) |
| `metadata` | Analyzer | Reviewer, Reporter |
| `classification` | Analyzer | Reviewer, Reporter |
| `findings` | Reviewer | Reporter |
| `draft_comment` | Reporter | HITL gate |
| `human_approved` | HITL gate | Poster node |
| `posted_comment_url` | Poster node | Trace log |
| `total_cost_usd` | Each agent (+=) | Trace log |
| `error` | Any agent on failure | Trace log |

---

## GitHub Comment Format

Output of `format_as_github_markdown(findings: ReviewFindings) -> str`.
This is a deterministic function — no LLM involved.

```markdown
## 🤖 Agentic PR Review

> **Verdict**: `request_changes` · **Risk**: `high` · **Confidence**: 95%

This PR adds a login endpoint but has a critical security flaw in password
hashing and missing input validation. Approve after fixes.

---

### 🔴 Critical — `src/auth.py` (lines 34–36)

**Issue**: Password is hashed with MD5, which is cryptographically broken.

**Standard**: `security.md § Password Handling`

**Fix**: Replace `hashlib.md5(...)` with `bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12))`.

---

<sub>Run ID: `abc-123` · Cost: $0.0412 · [Trace](https://cloud.langfuse.com/...)</sub>
```

**Severity badge mapping**:
- `critical` → 🔴 Critical
- `warning` → 🟡 Warning
- `suggestion` → 🔵 Suggestion

If `confidence < 0.7`, append to the header block:
> ⚠️ Low confidence — the Reviewer flagged uncertainty. Human review recommended before acting on these findings.
