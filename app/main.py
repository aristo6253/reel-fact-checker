import json
import logging
import os
import re
from logging.handlers import RotatingFileHandler
from urllib.parse import quote

import anthropic
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.config import daily_cap, rate_limiter, settings
from app.history import list_all
from app.jobs import create_job, start_job
from app.pipeline import run_pipeline
from app.push_subscription import load_subscription, save_subscription

# Persistent per-run log: the uvicorn console output is ephemeral (lost on restart,
# hard to grep across sessions) — logs/app.log gives every check its own durable
# timeline (start/stage/outcome + full tracebacks) via the app.* logger hierarchy.
os.makedirs("logs", exist_ok=True)
_file_handler = RotatingFileHandler("logs/app.log", maxBytes=2_000_000, backupCount=5)
_file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
_app_logger = logging.getLogger("app")
_app_logger.setLevel(logging.INFO)
_app_logger.addHandler(_file_handler)

app = FastAPI()

templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

_INSTAGRAM_URL_RE = re.compile(r"https?://(?:www\.)?instagram\.com/\S+")


@app.get("/sw.js")
def service_worker():
    # Served from root (not /static/sw.js) so its default scope covers the whole
    # app rather than just /static/ — Service-Worker-Allowed header would be the
    # alternative, but StaticFiles doesn't expose a way to set that per-file.
    return FileResponse("app/static/sw.js", media_type="application/javascript")


@app.get("/share-target")
async def share_target(request: Request, title: str = "", text: str = "", url: str = ""):
    # Android's share sheet fills these loosely depending on the sharing app — Instagram
    # may put the reel link in any of the three, often mixed in with other text.
    matched_url = None
    for field in (url, text, title):
        match = _INSTAGRAM_URL_RE.search(field)
        if match:
            matched_url = match.group(0)
            break

    if not matched_url:
        return RedirectResponse("/")

    # Push notifications need a subscription registered ahead of time (via the
    # "Enable notifications" button) — a bare GET share-target request has no way to
    # create one itself. Without one, fall back to the old foreground live-check flow.
    subscription = load_subscription(settings.push_subscription_path)
    client_ip = request.client.host if request.client else "unknown"
    if not subscription or not rate_limiter.allow(client_ip) or not daily_cap.allow():
        return RedirectResponse(f"/?url={quote(matched_url, safe='')}")

    _start_background_job(matched_url, False, subscription)
    return templates.TemplateResponse(request, "share_confirmation.html")


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/")
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {"vapid_public_key": settings.vapid_public_key})


@app.get("/history")
def history(request: Request):
    entries = list_all(settings.history_db_path)
    return templates.TemplateResponse(request, "history.html", {"entries": entries})


@app.get("/api/v1/check")
async def check(url: str, request: Request, force: bool = False):
    client_ip = request.client.host if request.client else "unknown"
    if not rate_limiter.allow(client_ip):
        return StreamingResponse(
            iter([_sse({"event": "failed", "data": {"message": "Rate limit exceeded. Try again in a minute."}})]),
            media_type="text/event-stream",
        )
    if not daily_cap.allow():
        return StreamingResponse(
            iter([_sse({"event": "failed", "data": {"message": "Daily request limit reached. Try again tomorrow."}})]),
            media_type="text/event-stream",
        )

    daily_cap.record()
    anthropic_client = anthropic.Anthropic(
        api_key=settings.anthropic_api_key,
        auth_token=settings.anthropic_auth_token,
        base_url=settings.anthropic_base_url,
    )

    async def event_stream():
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as http_client:
            async for event in run_pipeline(
                url, anthropic_client, http_client, settings.history_db_path, force=force
            ):
                yield _sse(event)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _start_background_job(url: str, force: bool, subscription: dict) -> str:
    daily_cap.record()
    anthropic_client = anthropic.Anthropic(
        api_key=settings.anthropic_api_key,
        auth_token=settings.anthropic_auth_token,
        base_url=settings.anthropic_base_url,
    )
    job_id = create_job()
    start_job(
        job_id,
        url,
        anthropic_client,
        settings.history_db_path,
        force,
        subscription,
        settings.vapid_private_key,
        settings.vapid_claims_sub,
    )
    return job_id


class SubscribeRequest(BaseModel):
    subscription: dict


@app.post("/api/v1/subscribe")
def subscribe(subscribe_request: SubscribeRequest):
    save_subscription(settings.push_subscription_path, subscribe_request.subscription)
    return {"status": "ok"}


def _sse(event: dict) -> str:
    return f"event: {event['event']}\ndata: {json.dumps(event['data'])}\n\n"
