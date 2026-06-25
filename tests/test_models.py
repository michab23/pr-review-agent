"""Unit tests for src/models.py — Pydantic validation."""
import pytest
from pydantic import ValidationError

from src.models import (
    ChangeType,
    PRClassification,
    PRMetadata,
    PipelineState,
    ReviewFinding,
    ReviewFindings,
    RiskLevel,
)


class TestRiskLevel:
    def test_values(self):
        assert RiskLevel.LOW.value == "low"
        assert RiskLevel.MEDIUM.value == "medium"
        assert RiskLevel.HIGH.value == "high"

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            RiskLevel("critical")


class TestChangeType:
    def test_all_values(self):
        expected = {"feature", "bug_fix", "refactor", "security", "docs", "config", "dependency"}
        assert {ct.value for ct in ChangeType} == expected


class TestPRMetadata:
    def test_valid_construction(self):
        m = PRMetadata(
            url="https://github.com/a/b/pull/1",
            repo="a/b",
            pr_number=1,
            title="feat: add thing",
            description="desc",
            diff="@@ -1 +1 @@\n+x=1",
            files_changed=["a.py"],
            lines_added=1,
            lines_removed=0,
        )
        assert m.pr_number == 1

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            PRMetadata(url="x", repo="a/b", pr_number=1, title="t")  # missing fields


class TestPRClassification:
    def test_valid(self):
        c = PRClassification(
            risk_level=RiskLevel.HIGH,
            change_types=[ChangeType.SECURITY],
            risk_rationale="uses MD5",
            model_to_use="anthropic/claude-opus-4-8",
            files_of_concern=["auth.py"],
        )
        assert c.risk_level == RiskLevel.HIGH

    def test_invalid_risk_level_raises(self):
        with pytest.raises(ValidationError):
            PRClassification(
                risk_level="extreme",
                change_types=[],
                risk_rationale="x",
                model_to_use="m",
                files_of_concern=[],
            )


class TestReviewFinding:
    def test_valid_severities(self):
        for sev in ("critical", "warning", "suggestion"):
            f = ReviewFinding(severity=sev, file="f.py", issue="x", suggestion="fix it")
            assert f.severity == sev

    def test_invalid_severity_raises(self):
        with pytest.raises(ValidationError):
            ReviewFinding(severity="blocker", file="f.py", issue="x", suggestion="y")

    def test_optional_fields_default_none(self):
        f = ReviewFinding(severity="warning", file="x.py", issue="iss", suggestion="sug")
        assert f.line_range is None
        assert f.standard_cited is None


class TestReviewFindings:
    def test_valid_verdicts(self):
        for verdict in ("approve", "request_changes", "comment"):
            rf = ReviewFindings(summary="s", findings=[], verdict=verdict, confidence=0.8)
            assert rf.verdict == verdict

    def test_invalid_verdict_raises(self):
        with pytest.raises(ValidationError):
            ReviewFindings(summary="s", findings=[], verdict="reject", confidence=0.8)

    def test_confidence_stored_as_float(self):
        rf = ReviewFindings(summary="s", findings=[], verdict="approve", confidence=0.95)
        assert rf.confidence == pytest.approx(0.95)


class TestPipelineState:
    def test_defaults(self):
        state = PipelineState(pr_url="https://github.com/a/b/pull/1", run_id="abc")
        assert state.metadata is None
        assert state.classification is None
        assert state.findings is None
        assert state.draft_comment is None
        assert state.human_approved is None
        assert state.posted_comment_url is None
        assert state.total_cost_usd == 0.0
        assert state.error is None

    def test_error_can_be_set(self):
        state = PipelineState(pr_url="x", run_id="r", error="boom")
        assert state.error == "boom"
