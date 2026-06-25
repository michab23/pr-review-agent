"""Unit tests for src/tools/trace.py."""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from src.models import (
    ChangeType,
    PRClassification,
    PRMetadata,
    PipelineState,
    ReviewFinding,
    ReviewFindings,
    RiskLevel,
)


def _make_full_state() -> PipelineState:
    meta = PRMetadata(
        url="https://github.com/acme/repo/pull/1",
        repo="acme/repo",
        pr_number=1,
        title="Test PR",
        description="desc",
        diff="--- a/f.py\n+++ b/f.py\n+x=1",
        files_changed=["f.py"],
        lines_added=1,
        lines_removed=0,
    )
    clf = PRClassification(
        risk_level=RiskLevel.MEDIUM,
        change_types=[ChangeType.FEATURE],
        risk_rationale="adds new feature",
        model_to_use="anthropic/claude-sonnet-4-6",
        files_of_concern=["f.py"],
    )
    findings = ReviewFindings(
        summary="Looks good",
        findings=[
            ReviewFinding(
                severity="warning",
                file="f.py",
                line_range="5-7",
                issue="Missing type hint",
                suggestion="Add -> None",
            )
        ],
        verdict="request_changes",
        confidence=0.9,
    )
    state = PipelineState(pr_url=meta.url, run_id="test-run-001")
    state.metadata = meta
    state.classification = clf
    state.findings = findings
    state.draft_comment = "## Review\nWarning found."
    state.human_approved = True
    state.posted_comment_url = "https://github.com/acme/repo/issues/1#issuecomment-1"
    state.total_cost_usd = 0.0042
    return state


class TestLogStructuredTrace:
    def test_writes_jsonl_entry(self, tmp_path):
        from src.tools.trace import log_structured_trace

        with patch("src.tools.trace.TRACES_DIR", tmp_path):
            state = _make_full_state()
            log_structured_trace(state)

        files = list(tmp_path.glob("*.jsonl"))
        assert len(files) == 1
        entry = json.loads(files[0].read_text())
        assert entry["run_id"] == "test-run-001"
        assert entry["pr_url"] == "https://github.com/acme/repo/pull/1"
        assert entry["risk_level"] == "medium"
        assert entry["findings_count"] == 1
        assert entry["verdict"] == "request_changes"
        assert entry["human_approved"] is True
        assert entry["total_cost_usd"] == pytest.approx(0.0042)
        assert entry["error"] is None

    def test_appends_multiple_entries(self, tmp_path):
        from src.tools.trace import log_structured_trace

        with patch("src.tools.trace.TRACES_DIR", tmp_path):
            for _ in range(3):
                log_structured_trace(_make_full_state())

        files = list(tmp_path.glob("*.jsonl"))
        lines = files[0].read_text().strip().split("\n")
        assert len(lines) == 3
        for line in lines:
            json.loads(line)  # must be valid JSON

    def test_error_state_recorded(self, tmp_path):
        from src.tools.trace import log_structured_trace

        state = PipelineState(pr_url="https://github.com/x/y/pull/9", run_id="err-run")
        state.error = "GitHub API error 404: Not Found"

        with patch("src.tools.trace.TRACES_DIR", tmp_path):
            log_structured_trace(state)

        files = list(tmp_path.glob("*.jsonl"))
        entry = json.loads(files[0].read_text())
        assert entry["risk_level"] is None
        assert entry["findings_count"] == 0
        assert entry["verdict"] is None
        assert entry["error"] == "GitHub API error 404: Not Found"

    def test_creates_traces_dir_if_missing(self, tmp_path):
        from src.tools.trace import log_structured_trace

        nested = tmp_path / "new_traces"
        assert not nested.exists()

        with patch("src.tools.trace.TRACES_DIR", nested):
            log_structured_trace(_make_full_state())

        assert nested.exists()

    def test_models_used_from_classification(self, tmp_path):
        from src.tools.trace import log_structured_trace

        with patch("src.tools.trace.TRACES_DIR", tmp_path):
            log_structured_trace(_make_full_state())

        entry = json.loads(list(tmp_path.glob("*.jsonl"))[0].read_text())
        assert entry["models_used"] == ["anthropic/claude-sonnet-4-6"]
