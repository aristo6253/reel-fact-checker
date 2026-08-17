import asyncio
import json
import logging
import uuid
from typing import Any

import anthropic
import httpx
from pywebpush import WebPushException, webpush

from app.pipeline import run_pipeline

logger = logging.getLogger(__name__)

# ponytail: in-memory, not persisted — job status is lost on server restart. Acceptable
# for now since the final result is also saved to history.db by run_pipeline itself;
# only the "still running" polling state would be lost, not the actual check result.
_jobs: dict[str, dict[str, Any]] = {}

# Holds strong references to in-flight background tasks — asyncio only weakly tracks
# tasks internally, so a task with no other reference can be garbage-collected mid-run.
_running_tasks: set[asyncio.Task] = set()


def create_job() -> str:
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "running", "result": None}
    return job_id


def get_job(job_id: str) -> dict[str, Any] | None:
    return _jobs.get(job_id)


def start_job(
    job_id: str,
    url: str,
    anthropic_client: anthropic.Anthropic,
    history_db_path: str,
    force: bool,
    subscription: dict | None,
    vapid_private_key: str | None,
    vapid_claims_sub: str,
) -> None:
    task = asyncio.create_task(
        _run_job(job_id, url, anthropic_client, history_db_path, force, subscription, vapid_private_key, vapid_claims_sub)
    )
    _running_tasks.add(task)
    task.add_done_callback(_running_tasks.discard)


async def _run_job(
    job_id: str,
    url: str,
    anthropic_client: anthropic.Anthropic,
    history_db_path: str,
    force: bool,
    subscription: dict | None,
    vapid_private_key: str | None,
    vapid_claims_sub: str,
) -> None:
    final_event = {"event": "failed", "data": {"message": "Something went wrong while checking this reel."}}
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as http_client:
            async for event in run_pipeline(url, anthropic_client, http_client, history_db_path, force=force):
                if event["event"] in ("done", "cached", "failed"):
                    final_event = event
    except Exception:
        logger.exception("background job %s crashed for %s", job_id, url)

    _jobs[job_id] = {"status": final_event["event"], "result": final_event["data"]}

    if subscription and vapid_private_key:
        await asyncio.to_thread(_send_push, subscription, final_event, vapid_private_key, vapid_claims_sub)


def _send_push(subscription: dict, final_event: dict, vapid_private_key: str, vapid_claims_sub: str) -> None:
    data = final_event["data"]
    if final_event["event"] == "failed":
        title = "Reel check failed"
        body = data.get("message", "Something went wrong.")
    else:
        score = data.get("trustworthiness_score")
        title = f"Reel checked — {score}/100" if score is not None else "Reel checked"
        body = data.get("headline_verdict", "Your check is ready.")

    try:
        webpush(
            subscription_info=subscription,
            data=json.dumps({"title": title, "body": body}),
            vapid_private_key=vapid_private_key,
            vapid_claims={"sub": vapid_claims_sub},
        )
    except WebPushException:
        logger.exception("failed to send push notification")
