# Evaluation test suite — see spec/spec.md §9 and plan.md tasks 10-11
# Run (structural only, no LLM calls): uv run pytest evals/ -v -m "not llm_eval"
# Run (full LLM evaluation, costs money): uv run pytest evals/ -v
import json
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

DATASET_DIR = Path(__file__).parent / "dataset"


def load_dataset() -> list[dict[str, Any]]:
    entries = []
    for path in sorted(DATASET_DIR.glob("*.json")):
        entries.append(json.loads(path.read_text()))
    return entries


def make_fake_pr_metadata(entry: dict[str, Any]):
    """Build a PRMetadata-like dict from a dataset entry for use in agent tests."""
    from src.models import PRMetadata

    return PRMetadata(
        url=f"https://github.com/acme/test-repo/pull/{entry['id']}",
        repo="acme/test-repo",
        pr_number=int(entry["id"].split("-")[1]),
        title=entry["description"],
        description="",
        diff=entry["pr_diff"],
        files_changed=entry["files_changed"],
        lines_added=entry["pr_diff"].count("\n+"),
        lines_removed=entry["pr_diff"].count("\n-"),
    )


# ---------------------------------------------------------------------------
# Structural tests — no LLM calls, always run
# ---------------------------------------------------------------------------

class TestDatasetIntegrity:
    """Verify the eval dataset is well-formed before running any LLM tests."""

    DATASET = load_dataset()

    def test_dataset_has_10_entries(self):
        assert len(self.DATASET) == 10, f"Expected 10 dataset entries, got {len(self.DATASET)}"

    def test_risk_distribution(self):
        by_risk = {}
        for entry in self.DATASET:
            r = entry["expected_risk_level"]
            by_risk[r] = by_risk.get(r, 0) + 1
        assert by_risk.get("low", 0) == 3
        assert by_risk.get("medium", 0) == 4
        assert by_risk.get("high", 0) == 3

    @pytest.mark.parametrize("entry", load_dataset(), ids=[e["id"] for e in load_dataset()])
    def test_entry_schema(self, entry: dict[str, Any]):
        required = {"id", "description", "pr_diff", "files_changed",
                    "expected_risk_level", "expected_change_types", "planted_issues"}
        assert required.issubset(entry.keys()), f"Missing keys in {entry.get('id')}"
        assert entry["expected_risk_level"] in ("low", "medium", "high")
        assert isinstance(entry["files_changed"], list) and len(entry["files_changed"]) > 0
        assert isinstance(entry["pr_diff"], str) and len(entry["pr_diff"]) > 10

    @pytest.mark.parametrize("entry", load_dataset(), ids=[e["id"] for e in load_dataset()])
    def test_high_risk_has_planted_issues(self, entry: dict[str, Any]):
        if entry["expected_risk_level"] == "high":
            assert len(entry["planted_issues"]) >= 2, (
                f"High-risk entry {entry['id']} should have ≥2 planted issues"
            )


# ---------------------------------------------------------------------------
# LLM Evaluation tests — marked @pytest.mark.llm_eval, cost money
# ---------------------------------------------------------------------------

@pytest.mark.llm_eval
class TestAnalyzerClassification:
    """Analyzer must classify risk level correctly for ≥85% of dataset entries."""

    DATASET = load_dataset()

    @pytest.mark.parametrize("entry", load_dataset(), ids=[e["id"] for e in load_dataset()])
    def test_risk_level_correct(self, entry: dict[str, Any]):
        from dotenv import load_dotenv
        load_dotenv()

        from src.agents.analyzer import analyzer_agent
        from src.models import PRClassification
        from src.tools.github import validate_diff

        metadata = make_fake_pr_metadata(entry)
        cleaned_diff = validate_diff(metadata.diff)
        metadata = metadata.model_copy(update={"diff": cleaned_diff})

        result = analyzer_agent.run(str(metadata.model_dump()))
        classification: PRClassification = result.content

        assert classification.risk_level.value == entry["expected_risk_level"], (
            f"[{entry['id']}] Expected {entry['expected_risk_level']}, "
            f"got {classification.risk_level.value}. "
            f"Rationale: {classification.risk_rationale}"
        )


@pytest.mark.llm_eval
class TestReviewerHallucination:
    """Reviewer must never cite file paths that don't exist in the diff (0 violations)."""

    HIGH_RISK_ENTRIES = [e for e in load_dataset() if e["expected_risk_level"] == "high"]

    @pytest.mark.parametrize(
        "entry",
        HIGH_RISK_ENTRIES,
        ids=[e["id"] for e in HIGH_RISK_ENTRIES],
    )
    def test_no_hallucinated_file_paths(self, entry: dict[str, Any]):
        from dotenv import load_dotenv
        load_dotenv()

        from src.agents.analyzer import analyzer_agent, RISK_MODEL_MAP
        from src.agents.reviewer import reviewer_agent
        from agno.models.litellm import LiteLLM
        from src.tools.github import validate_diff

        metadata = make_fake_pr_metadata(entry)
        cleaned_diff = validate_diff(metadata.diff)
        metadata = metadata.model_copy(update={"diff": cleaned_diff})

        # Classify first to get model tier
        classification = analyzer_agent.run(str(metadata.model_dump())).content

        # Override model using RISK_MODEL_MAP (same as pipeline) to guarantee valid LiteLLM model IDs
        reviewer_agent.model = LiteLLM(id=RISK_MODEL_MAP[classification.risk_level.value], top_p=None, temperature=1)
        findings = reviewer_agent.run(
            f"Metadata: {metadata.model_dump_json()}\n"
            f"Classification: {classification.model_dump_json()}"
        ).content

        files_in_diff = set(entry["files_changed"])
        for finding in findings.findings:
            assert finding.file in files_in_diff, (
                f"[{entry['id']}] Hallucinated file path: '{finding.file}' "
                f"not in diff. Valid files: {files_in_diff}"
            )


@pytest.mark.llm_eval
class TestCostBounds:
    """Cost per run must stay within budget: low ≤ $0.05, high ≤ $0.25."""

    DATASET = load_dataset()

    @pytest.mark.parametrize(
        "entry",
        [e for e in load_dataset() if e["expected_risk_level"] in ("low", "high")],
        ids=[e["id"] for e in load_dataset() if e["expected_risk_level"] in ("low", "high")],
    )
    def test_cost_within_budget(self, entry: dict[str, Any]):
        from dotenv import load_dotenv
        load_dotenv()

        from src.pipeline import run
        from src.models import PipelineState
        from unittest.mock import patch

        metadata = make_fake_pr_metadata(entry)

        # Patch GitHub fetch and HITL gate so we don't need real credentials or terminal input
        with (
            patch("src.pipeline.get_pr_metadata", return_value=metadata),
            patch("src.pipeline.validate_diff", side_effect=lambda d: d),
            patch("src.pipeline.human_approval_gate", return_value=False),
            patch("src.pipeline.post_pr_comment", return_value="https://github.com/mock/comment"),
            patch("src.pipeline.log_structured_trace"),
        ):
            state: PipelineState = run(f"https://github.com/acme/test-repo/pull/{entry['id']}")

        limit = 0.05 if entry["expected_risk_level"] == "low" else 0.25
        assert state.total_cost_usd <= limit, (
            f"[{entry['id']}] Cost ${state.total_cost_usd:.4f} exceeds "
            f"${limit:.2f} limit for {entry['expected_risk_level']}-risk PR"
        )
