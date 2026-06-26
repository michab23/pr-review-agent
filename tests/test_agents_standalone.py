"""Subprocess tests for standalone agent entrypoints.

Marked @pytest.mark.integration — these make real LLM calls and are excluded
from the default test run. Execute with: pytest -m integration
"""
import json
import subprocess
import sys

import pytest

_METADATA = {
    "url": "https://github.com/acme/repo/pull/1",
    "repo": "acme/repo",
    "pr_number": 1,
    "title": "Add feature X",
    "description": "Adds a small helper",
    "diff": "--- a/x.py\n+++ b/x.py\n@@ -0,0 +1 @@\n+x = 1\n",
    "files_changed": ["x.py"],
    "lines_added": 1,
    "lines_removed": 0,
}

_CLASSIFICATION = {
    "risk_level": "low",
    "change_types": ["feature"],
    "risk_rationale": "trivial one-liner",
    "model_to_use": "anthropic/claude-haiku-4-5-20251001",
    "files_of_concern": [],
}

_FINDINGS = {
    "summary": "Looks fine",
    "findings": [],
    "verdict": "approve",
    "confidence": 0.95,
}


def _run_agent(module: str, payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", module],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )


@pytest.mark.integration
class TestAnalyzerStandalone:
    def test_valid_input_returns_classification(self):
        result = _run_agent("src.agents.analyzer", _METADATA)
        assert result.returncode == 0, result.stderr
        output = json.loads(result.stdout)
        assert "risk_level" in output
        assert output["risk_level"] in ("low", "medium", "high")

    def test_invalid_input_exits_with_error(self):
        result = _run_agent("src.agents.analyzer", {})
        assert result.returncode == 1
        assert result.stderr.strip() != ""


@pytest.mark.integration
class TestReviewerStandalone:
    def test_valid_input_returns_findings(self):
        payload = {
            "metadata": _METADATA,
            "classification": _CLASSIFICATION,
            "standards": "(none)",
        }
        result = _run_agent("src.agents.reviewer", payload)
        assert result.returncode == 0, result.stderr
        output = json.loads(result.stdout)
        assert "verdict" in output
        assert output["verdict"] in ("approve", "request_changes", "comment")

    def test_invalid_input_exits_with_error(self):
        result = _run_agent("src.agents.reviewer", {})
        assert result.returncode == 1
        assert result.stderr.strip() != ""


@pytest.mark.integration
class TestReporterStandalone:
    def test_valid_input_returns_comment_string(self):
        payload = {
            "metadata": _METADATA,
            "findings": _FINDINGS,
            "run_id": "test-standalone-001",
            "cost_usd": 0.001,
        }
        result = _run_agent("src.agents.reporter", payload)
        assert result.returncode == 0, result.stderr
        assert len(result.stdout.strip()) > 0

    def test_invalid_input_exits_with_error(self):
        result = _run_agent("src.agents.reporter", {})
        assert result.returncode == 1
        assert result.stderr.strip() != ""
