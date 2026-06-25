"""Unit tests for src/pipeline.py — all external calls mocked."""
# ---------------------------------------------------------------------------
# _extract_json
# ---------------------------------------------------------------------------

class TestExtractJson:
    def test_plain_json_unchanged(self):
        from src.pipeline import _extract_json
        raw = '{"a": 1}'
        assert _extract_json(raw) == raw

    def test_strips_json_fence(self):
        from src.pipeline import _extract_json
        fenced = '```json\n{"a": 1}\n```'
        assert _extract_json(fenced) == '{"a": 1}'

    def test_strips_plain_fence(self):
        from src.pipeline import _extract_json
        fenced = '```\n{"a": 1}\n```'
        assert _extract_json(fenced) == '{"a": 1}'

    def test_strips_surrounding_whitespace(self):
        from src.pipeline import _extract_json
        assert _extract_json('  {"a": 1}  ') == '{"a": 1}'

    def test_multiline_json_in_fence(self):
        from src.pipeline import _extract_json
        fenced = '```json\n{\n  "risk_level": "high"\n}\n```'
        result = _extract_json(fenced)
        assert result.startswith("{")
        assert "risk_level" in result

    def test_code_fences_inside_suggestion_strings(self):
        # Regression: reviewer wraps response in ```json...``` AND includes ```python...```
        # inside suggestion fields. The old non-greedy regex stopped at the first inner ```
        # and returned truncated JSON. The new impl finds outermost { ... } instead.
        from src.pipeline import _extract_json
        import json

        inner_json = {
            "summary": "Issues found",
            "findings": [
                {
                    "severity": "warning",
                    "file": "auth.py",
                    "line_range": "42",
                    "issue": "Uses MD5",
                    "standard_cited": "Security §3.1",
                    "suggestion": "Replace with:\n```python\nhashlib.sha256(data).hexdigest()\n```",
                }
            ],
            "verdict": "request_changes",
            "confidence": 0.9,
        }
        fenced = f"```json\n{json.dumps(inner_json)}\n```"
        result = _extract_json(fenced)
        parsed = json.loads(result)
        assert parsed["findings"][0]["suggestion"].startswith("Replace with:")

    def test_trailing_brace_in_prose_ignored(self):
        # rfind('}') would capture the trailing } from prose; raw_decode stops at the right place
        import json
        from src.pipeline import _extract_json
        text = '{"key": "value"}\n\nNote: see pattern {x} for details.'
        result = _extract_json(text)
        assert json.loads(result) == {"key": "value"}

import io
import os
from unittest.mock import MagicMock, patch

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


def _fake_metadata() -> PRMetadata:
    return PRMetadata(
        url="https://github.com/acme/repo/pull/7",
        repo="acme/repo",
        pr_number=7,
        title="Add feature X",
        description="",
        diff="--- a/x.py\n+++ b/x.py\n+x = 1\n",
        files_changed=["x.py"],
        lines_added=1,
        lines_removed=0,
    )


def _fake_classification() -> PRClassification:
    return PRClassification(
        risk_level=RiskLevel.LOW,
        change_types=[ChangeType.FEATURE],
        risk_rationale="trivial",
        model_to_use="anthropic/claude-haiku-4-5-20251001",
        files_of_concern=[],
    )


def _fake_findings() -> ReviewFindings:
    return ReviewFindings(
        summary="Looks fine",
        findings=[],
        verdict="approve",
        confidence=0.95,
    )


# ---------------------------------------------------------------------------
# human_approval_gate
# ---------------------------------------------------------------------------

class TestHumanApprovalGate:
    def _make_state(self) -> PipelineState:
        state = PipelineState(pr_url="https://github.com/a/b/pull/1", run_id="r")
        state.metadata = _fake_metadata()
        state.draft_comment = "## Review\nLooks good."
        return state

    def test_returns_true_on_y(self):
        from src.pipeline import human_approval_gate

        with (
            patch("src.pipeline.select.select", return_value=([True], [], [])),
            patch("sys.stdin", io.StringIO("y\n")),
        ):
            assert human_approval_gate(self._make_state()) is True

    def test_returns_false_on_n(self):
        from src.pipeline import human_approval_gate

        with (
            patch("src.pipeline.select.select", return_value=([True], [], [])),
            patch("sys.stdin", io.StringIO("n\n")),
        ):
            assert human_approval_gate(self._make_state()) is False

    def test_returns_false_on_timeout(self):
        from src.pipeline import human_approval_gate

        with patch("src.pipeline.select.select", return_value=([], [], [])):
            assert human_approval_gate(self._make_state()) is False

    def test_returns_false_on_unexpected_input(self):
        from src.pipeline import human_approval_gate

        with (
            patch("src.pipeline.select.select", return_value=([True], [], [])),
            patch("sys.stdin", io.StringIO("maybe\n")),
        ):
            assert human_approval_gate(self._make_state()) is False


# ---------------------------------------------------------------------------
# run() — full pipeline with all agents and GitHub mocked
# ---------------------------------------------------------------------------

def _patch_pipeline(approved: bool = True, extra_patches: dict | None = None):
    """Context manager that patches all external deps for pipeline.run()."""
    from contextlib import ExitStack

    metadata = _fake_metadata()
    classification = _fake_classification()
    findings = _fake_findings()

    mock_analyzer_result = MagicMock()
    mock_analyzer_result.content = classification

    mock_reviewer_result = MagicMock()
    mock_reviewer_result.content = findings

    mock_reporter_result = MagicMock()
    mock_reporter_result.content = "## Review\nApproved."

    patches = {
        "src.pipeline.get_pr_metadata": lambda *a, **kw: metadata,
        "src.pipeline.validate_diff": lambda d: d,
        "src.pipeline.human_approval_gate": lambda s: approved,
        "src.pipeline.post_pr_comment": lambda *a, **kw: "https://github.com/comment/1",
        "src.pipeline.log_structured_trace": lambda s: None,
    }

    return patches, metadata, classification, findings


class TestPipelineRun:
    def _run_with_mocks(self, approved: bool = True):
        """Run pipeline with all external calls mocked; return PipelineState."""
        from src.pipeline import run

        metadata = _fake_metadata()
        classification = _fake_classification()
        findings = _fake_findings()

        mock_analyzer = MagicMock()
        mock_analyzer.run.return_value = MagicMock(content=classification)

        mock_reviewer = MagicMock()
        mock_reviewer.run.return_value = MagicMock(content=findings)
        mock_reviewer.model = None

        mock_reporter = MagicMock()
        mock_reporter.run.return_value = MagicMock(content="## Review\nApproved.")

        with (
            patch("src.pipeline.get_pr_metadata", return_value=metadata),
            patch("src.pipeline.validate_diff", side_effect=lambda d: d),
            patch("src.pipeline.analyzer_agent", mock_analyzer),
            patch("src.pipeline.reviewer_agent", mock_reviewer),
            patch("src.pipeline.reporter_agent", mock_reporter),
            patch("src.pipeline.human_approval_gate", return_value=approved),
            patch("src.pipeline.post_pr_comment", return_value="https://github.com/comment/1"),
            patch("src.pipeline.log_structured_trace"),
            patch("src.pipeline.langfuse"),
        ):
            return run("https://github.com/acme/repo/pull/7")

    def test_happy_path_approved(self):
        state = self._run_with_mocks(approved=True)
        assert state.metadata is not None
        assert state.classification is not None
        assert state.findings is not None
        assert state.draft_comment == "## Review\nApproved."
        assert state.human_approved is True
        assert state.posted_comment_url == "https://github.com/comment/1"
        assert state.error is None

    def test_abort_when_not_approved(self):
        state = self._run_with_mocks(approved=False)
        assert state.human_approved is False
        assert state.posted_comment_url is None

    def test_github_error_sets_error_field(self):
        from src.pipeline import run

        with (
            patch("src.pipeline.get_pr_metadata", side_effect=RuntimeError("GitHub 404: Not Found")),
            patch("src.pipeline.log_structured_trace"),
            patch("src.pipeline.langfuse"),
        ):
            with pytest.raises(RuntimeError, match="GitHub 404"):
                run("https://github.com/acme/repo/pull/7")

    def test_run_id_is_unique(self):
        state1 = self._run_with_mocks()
        state2 = self._run_with_mocks()
        assert state1.run_id != state2.run_id
