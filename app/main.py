import json

import anthropic
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

from app.config import daily_cap, rate_limiter, settings
from app.pipeline import run_pipeline

app = FastAPI()


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/api/v1/check")
async def check(url: str, request: Request):
    client_ip = request.client.host if request.client else "unknown"
    if not rate_limiter.allow(client_ip):
        return StreamingResponse(
            iter([_sse({"event": "error", "data": {"message": "Rate limit exceeded. Try again in a minute."}})]),
            media_type="text/event-stream",
            status_code=429,
        )
    if not daily_cap.allow():
        return StreamingResponse(
            iter([_sse({"event": "error", "data": {"message": "Daily request limit reached. Try again tomorrow."}})]),
            media_type="text/event-stream",
            status_code=503,
        )

    daily_cap.record()
    anthropic_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    async def event_stream():
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as http_client:
            async for event in run_pipeline(url, anthropic_client, http_client):
                yield _sse(event)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _sse(event: dict) -> str:
    return f"event: {event['event']}\ndata: {json.dumps(event['data'])}\n\n"
