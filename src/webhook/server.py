import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from src.webhook.event_filter import parse_event
from src.webhook.runner import _tasks, launch_run
from src.webhook.signature import verify_signature

logger = logging.getLogger(__name__)

_WEBHOOK_SECRET: str = ""
_MAX_BODY_BYTES = 10 * 1024 * 1024  # 10 MB


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _WEBHOOK_SECRET
    missing = [v for v in ("GITHUB_APP_ID", "GITHUB_APP_PRIVATE_KEY", "GITHUB_WEBHOOK_SECRET")
               if not os.environ.get(v)]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
    _WEBHOOK_SECRET = os.environ["GITHUB_WEBHOOK_SECRET"]
    logger.info("webhook server started")
    yield


app = FastAPI(title="PR Review Webhook", lifespan=lifespan)


@app.post("/webhook")
async def webhook(request: Request) -> dict:
    body_bytes = await request.body()
    if len(body_bytes) > _MAX_BODY_BYTES:
        logger.warning("rejected oversized webhook payload (%d bytes)", len(body_bytes))
        return Response(content='{"error":"payload too large"}', status_code=413,
                        media_type="application/json")
    sig_header = request.headers.get("x-hub-signature-256")

    if not verify_signature(body_bytes, _WEBHOOK_SECRET, sig_header):
        logger.warning("invalid webhook signature — rejected")
        return Response(content='{"error":"invalid signature"}', status_code=401,
                        media_type="application/json")

    event_type = request.headers.get("x-github-event", "")
    if event_type in ("installation", "installation_repositories"):
        logger.info("ignoring installation event")
        return {"status": "ignored", "reason": "installation event"}

    if event_type != "pull_request":
        logger.info("ignoring non-pull_request event: %s", event_type)
        return {"status": "ignored", "reason": f"event type {event_type!r} not handled"}

    delivery_id = request.headers.get("x-github-delivery", "")
    try:
        body = json.loads(body_bytes)
    except Exception:
        return {"status": "ignored", "reason": "invalid JSON body"}

    headers = dict(request.headers)
    result = parse_event(headers, body)
    if result is None:
        action = body.get("action", "unknown")
        logger.info("ignoring event delivery=%s action=%s", delivery_id, action)
        return {"status": "ignored", "reason": f"action {action!r} or draft/dedup filter"}

    pr_url, pr_key, installation_id, head_sha = result
    logger.info("accepted event delivery=%s pr_key=%s action=%s", delivery_id, pr_key, body.get("action"))

    asyncio.create_task(launch_run(pr_key, pr_url, installation_id))

    return {"status": "accepted", "pr_key": pr_key}


@app.get("/health")
async def health() -> dict:
    active = sum(1 for t in _tasks.values() if not t.done())
    return {"status": "ok", "active_runs": active}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
