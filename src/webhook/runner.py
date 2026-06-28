import asyncio
import functools
import logging
import os
import threading

from github import Auth, GithubIntegration

from src.pipeline import run

logger = logging.getLogger(__name__)

_tasks: dict[str, asyncio.Task] = {}
_stop_flags: dict[str, threading.Event] = {}


def _get_gh_client(installation_id: int):
    app_id = os.environ["GITHUB_APP_ID"]
    private_key = os.environ["GITHUB_APP_PRIVATE_KEY"]
    app_auth = Auth.AppAuth(app_id, private_key)
    gi = GithubIntegration(auth=app_auth)
    return gi.get_github_for_installation(installation_id)


async def launch_run(pr_key: str, pr_url: str, installation_id: int) -> None:
    """Cancel any in-flight run for pr_key, then start a fresh pipeline run."""
    if pr_key in _tasks and not _tasks[pr_key].done():
        logger.info("cancelling in-flight run for %s", pr_key)
        _stop_flags[pr_key].set()
        _tasks[pr_key].cancel()
        await asyncio.sleep(0)

    repo_name, pr_number_str = pr_key.rsplit("#", 1)
    pr_number = int(pr_number_str)

    gh = _get_gh_client(installation_id)
    repo = gh.get_repo(repo_name)
    pr = repo.get_pull(pr_number)

    interim_comment = pr.create_issue_comment("🤖 AI review in progress…")
    logger.info("posted interim comment on %s", pr_key)

    stop = threading.Event()
    _stop_flags[pr_key] = stop

    task = asyncio.create_task(
        _run_task(pr_key, pr_url, stop, pr, interim_comment)
    )
    _tasks[pr_key] = task
    logger.info("launched pipeline task for %s", pr_key)


async def _run_task(pr_key, pr_url, stop, pr, interim_comment) -> None:
    loop = asyncio.get_running_loop()
    try:
        state = await loop.run_in_executor(
            None,
            functools.partial(run, pr_url, skip_hitl=True, stop_event=stop),
        )

        if state.error == "cancelled":
            logger.info("run cancelled for %s — leaving interim comment", pr_key)
            return

        pr.create_issue_comment(state.draft_comment)
        logger.info("posted review comment on %s", pr_key)

    except asyncio.CancelledError:
        logger.info("task cancelled for %s", pr_key)
        raise

    except Exception as exc:
        logger.error("pipeline failed for %s: %s", pr_key, exc)
        try:
            pr.create_issue_comment(f"⚠️ AI review failed: {exc}")
        except Exception:
            pass

    finally:
        try:
            interim_comment.delete()
        except Exception:
            pass
