# Data models — see spec/data-model.md for full schema and validation rules
from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ChangeType(str, Enum):
    FEATURE = "feature"
    BUG_FIX = "bug_fix"
    REFACTOR = "refactor"
    SECURITY = "security"
    DOCS = "docs"
    CONFIG = "config"
    DEPENDENCY = "dependency"


class PRMetadata(BaseModel):
    url: str
    repo: str
    pr_number: int
    title: str
    description: str
    diff: str
    files_changed: list[str]
    lines_added: int
    lines_removed: int


class PRClassification(BaseModel):
    risk_level: RiskLevel
    change_types: list[ChangeType]
    risk_rationale: str
    model_to_use: str
    files_of_concern: list[str]


class ReviewFinding(BaseModel):
    severity: Literal["critical", "warning", "suggestion"]
    file: str
    line_range: Optional[str] = None
    issue: str
    standard_cited: Optional[str] = None
    suggestion: str


class ReviewFindings(BaseModel):
    summary: str
    findings: list[ReviewFinding]
    verdict: Literal["approve", "request_changes", "comment"]
    confidence: float


class PipelineState(BaseModel):
    pr_url: str
    run_id: str

    metadata: Optional[PRMetadata] = None
    classification: Optional[PRClassification] = None
    findings: Optional[ReviewFindings] = None

    draft_comment: Optional[str] = None
    human_approved: Optional[bool] = None
    posted_comment_url: Optional[str] = None

    total_cost_usd: float = 0.0
    error: Optional[str] = None

    degraded: bool = False
    agents_failed: list[str] = []
