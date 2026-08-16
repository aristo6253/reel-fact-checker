import os
import tempfile
from typing import AsyncIterator

import anthropic
import httpx

from app.claim_bundle import assemble
from app.claude_client import extract_claims, verify_claims
from app.content_router import extract_audio_rms, has_narration
from app.instagram import InstagramFetchError, extract_shortcode, fetch_reel_data
from app.transcription import transcribe


async def download_video(video_url: str, http_client: httpx.AsyncClient) -> str:
    response = await http_client.get(video_url)
    fd, path = tempfile.mkstemp(suffix=".mp4")
    with os.fdopen(fd, "wb") as f:
        f.write(response.content)
    return path


async def run_pipeline(
    url: str, anthropic_client: anthropic.Anthropic, http_client: httpx.AsyncClient
) -> AsyncIterator[dict]:
    yield {"event": "fetching", "data": {}}

    try:
        shortcode = extract_shortcode(url)
        reel = await fetch_reel_data(shortcode, http_client)
    except (InstagramFetchError, ValueError):
        yield {"event": "error", "data": {"message": "Couldn't access this reel."}}
        return

    transcript: str | None = None
    video_path: str | None = None

    try:
        if reel.video_url:
            video_path = await download_video(reel.video_url, http_client)
            try:
                if has_narration(extract_audio_rms(video_path)):
                    yield {"event": "transcribing", "data": {}}
                    transcript = transcribe(video_path)
            finally:
                os.remove(video_path)

        bundle = assemble(reel=reel, source_url=url, transcript=transcript)

        yield {"event": "extracting_claims", "data": {}}
        extraction = extract_claims(bundle, anthropic_client)

        if not extraction.claims:
            yield {"event": "done", "data": {"headline_verdict": "No factual claims detected.", "claims": []}}
            return

        yield {"event": "verifying_claims", "data": {}}
        result = verify_claims(extraction, bundle, anthropic_client)
    except Exception:
        yield {"event": "error", "data": {"message": "Something went wrong while checking this reel."}}
        return

    yield {"event": "done", "data": result.model_dump()}
