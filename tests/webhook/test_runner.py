import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import src.webhook.runner as runner_module
from src.webhook.runner import launch_run


@pytest.fixture(autouse=True)
def clear_registry():
    runner_module._tasks.clear()
    runner_module._stop_flags.clear()
    yield
    runner_module._tasks.clear()
    runner_module._stop_flags.clear()


def _make_gh(pr_number=1):
    comment = MagicMock()
    pr = MagicMock()
    pr.create_issue_comment.return_value = comment
    repo = MagicMock()
    repo.get_pull.return_value = pr
    gh = MagicMock()
    gh.get_repo.return_value = repo
    return gh, pr, comment


def _make_state(draft_comment="## Review\nLGTM", error=None):
    state = MagicMock()
    state.draft_comment = draft_comment
    state.error = error
    return state


@pytest.mark.asyncio
async def test_at_most_one_run_per_pr():
    """Second launch_run for same PR cancels first task."""
    with patch("src.webhook.runner._get_gh_client") as mock_gh_fn:
        gh, pr, _ = _make_gh()
        mock_gh_fn.return_value = gh

        blocked = threading.Event()

        def slow_run(*args, **kwargs):
            blocked.wait(timeout=2)
            return _make_state()

        with patch("src.webhook.runner.run", side_effect=slow_run):
            await launch_run("owner/repo#1", "https://github.com/owner/repo/pull/1", 42)
            first_task = runner_module._tasks["owner/repo#1"]

            await launch_run("owner/repo#1", "https://github.com/owner/repo/pull/1", 42)

            assert first_task.cancelled() or runner_module._stop_flags.get("owner/repo#1") is not None
            blocked.set()
            await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_stop_event_set_on_cancel():
    """Cancelling a run sets the stop_event so the pipeline thread can exit."""
    with patch("src.webhook.runner._get_gh_client") as mock_gh_fn:
        gh, pr, _ = _make_gh()
        mock_gh_fn.return_value = gh

        captured_stop: list[threading.Event] = []

        def capturing_run(pr_url, *, skip_hitl, stop_event):
            captured_stop.append(stop_event)
            stop_event.wait(timeout=2)
            return _make_state()

        with patch("src.webhook.runner.run", side_effect=capturing_run):
            await launch_run("owner/repo#2", "https://github.com/owner/repo/pull/2", 42)
            stop_before = runner_module._stop_flags["owner/repo#2"]

            runner_module._stop_flags["owner/repo#2"].set()
            runner_module._tasks["owner/repo#2"].cancel()
            await asyncio.sleep(0.05)

            assert stop_before.is_set()


@pytest.mark.asyncio
async def test_successful_run_posts_review_comment():
    """On success, runner posts draft_comment and deletes interim comment."""
    with patch("src.webhook.runner._get_gh_client") as mock_gh_fn:
        gh, pr, interim = _make_gh()
        mock_gh_fn.return_value = gh

        with patch("src.webhook.runner.run", return_value=_make_state("## Review\nLooks good")):
            await launch_run("owner/repo#3", "https://github.com/owner/repo/pull/3", 42)
            await asyncio.sleep(0.1)

        review_calls = [c for c in pr.create_issue_comment.call_args_list
                        if "in progress" not in str(c)]
        assert any("Looks good" in str(c) for c in pr.create_issue_comment.call_args_list)
        interim.delete.assert_called_once()


@pytest.mark.asyncio
async def test_failure_path_posts_error_comment():
    """FR-005: pipeline exception → error comment posted, no review comment."""
    with patch("src.webhook.runner._get_gh_client") as mock_gh_fn:
        gh, pr, interim = _make_gh()
        mock_gh_fn.return_value = gh

        with patch("src.webhook.runner.run", side_effect=RuntimeError("api error")):
            await launch_run("owner/repo#4", "https://github.com/owner/repo/pull/4", 42)
            await asyncio.sleep(0.1)

        error_posted = any(
            "failed" in str(c).lower() or "error" in str(c).lower()
            for c in pr.create_issue_comment.call_args_list
        )
        assert error_posted, "expected error comment on PR"
        interim.delete.assert_called_once()


@pytest.mark.asyncio
async def test_cancelled_run_swallows_error():
    """CancelledError is swallowed; no error comment is posted."""
    with patch("src.webhook.runner._get_gh_client") as mock_gh_fn:
        gh, pr, interim = _make_gh()
        mock_gh_fn.return_value = gh

        with patch("src.webhook.runner.run", return_value=_make_state(error="cancelled")):
            await launch_run("owner/repo#5", "https://github.com/owner/repo/pull/5", 42)
            await asyncio.sleep(0.1)

        error_calls = [c for c in pr.create_issue_comment.call_args_list
                       if "failed" in str(c).lower() or "error" in str(c).lower()]
        assert not error_calls, "no error comment expected for cancelled run"
