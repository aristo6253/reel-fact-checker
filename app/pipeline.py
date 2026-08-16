import asyncio
import base64
import json
import logging
import os
import tempfile
from typing import AsyncIterator

import anthropic
import httpx

from app.claim_bundle import assemble
from app.claude_client import extract_claims, verify_claims
from app.content_router import extract_audio_rms, has_narration
from app.history import get_cached, save_check
from app.instagram import InstagramFetchError, extract_shortcode, fetch_reel_data
from app.transcription import transcribe

logger = logging.getLogger(__name__)

# Same UA app/instagram.py uses for its own fetches — CDN video URLs can also 403 without one.
_VIDEO_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


async def download_video(video_url: str, http_client: httpx.AsyncClient) -> str:
    response = await http_client.get(video_url, headers={"User-Agent": _VIDEO_UA})
    response.raise_for_status()
    fd, path = tempfile.mkstemp(suffix=".mp4")
    with os.fdopen(fd, "wb") as f:
        f.write(response.content)
    return path


async def download_image_base64(image_url: str, http_client: httpx.AsyncClient) -> dict:
    response = await http_client.get(image_url, headers={"User-Agent": _VIDEO_UA})
    response.raise_for_status()
    media_type = response.headers.get("content-type", "image/jpeg").split(";")[0]
    return {"media_type": media_type, "data": base64.b64encode(response.content).decode("ascii")}


async def run_pipeline(
    url: str,
    anthropic_client: anthropic.Anthropic,
    http_client: httpx.AsyncClient,
    history_db_path: str,
    force: bool = False,
) -> AsyncIterator[dict]:
    logger.info("run start: %s (force=%s)", url, force)
    yield {"event": "fetching", "data": {}}

    try:
        shortcode = extract_shortcode(url)
        reel = await fetch_reel_data(shortcode, http_client)
    except (InstagramFetchError, ValueError):
        logger.exception("failed to fetch reel %s", url)
        yield {"event": "failed", "data": {"message": "Couldn't access this reel."}}
        return

    yield {
        "event": "reel_info",
        "data": {
            "username": reel.username,
            "caption": reel.caption,
            "product_type": reel.product_type,
            "video_duration": reel.video_duration,
            "thumbnail_url": reel.thumbnail_url,
            "image_urls": reel.image_urls,
        },
    }

    cached = await asyncio.to_thread(get_cached, history_db_path, shortcode)

    if not force and cached is not None:
        logger.info("run served from cache: %s (shortcode=%s)", url, shortcode)
        yield {"event": "transcript", "data": {"transcript": cached["transcript"]}}
        yield {"event": "cached", "data": {**cached["result"], "checked_at": cached["checked_at"]}}
        return

    transcript: str | None = None
    video_path: str | None = None

    try:
        if cached is not None:
            # Forced recheck of a previously-checked reel: the audio hasn't changed, so
            # reuse the stored transcript rather than re-downloading the video and
            # re-running Whisper — only extraction/verification need to run fresh.
            transcript = cached["transcript"]
        elif reel.video_url:
            video_path = await download_video(reel.video_url, http_client)
            try:
                rms = await asyncio.to_thread(extract_audio_rms, video_path)
                if has_narration(rms):
                    yield {"event": "transcribing", "data": {}}
                    transcript = await asyncio.to_thread(transcribe, video_path)
            finally:
                os.remove(video_path)

        yield {"event": "transcript", "data": {"transcript": transcript}}

        images = [await download_image_base64(u, http_client) for u in reel.image_urls]

        bundle = assemble(reel=reel, source_url=url, transcript=transcript)

        yield {"event": "extracting_claims", "data": {}}
        extraction = await asyncio.to_thread(extract_claims, bundle, anthropic_client, images)

        if not extraction.claims:
            result_data = {"headline_verdict": "No factual claims detected.", "trustworthiness_score": None, "claims": []}
            await asyncio.to_thread(
                save_check,
                history_db_path,
                shortcode,
                url,
                transcript,
                json.dumps(result_data),
                reel.username,
                reel.caption,
                reel.product_type,
                reel.thumbnail_url,
            )
            logger.info("run done (no factual claims): %s (shortcode=%s)", url, shortcode)
            yield {"event": "done", "data": result_data}
            return

        yield {"event": "verifying_claims", "data": {}}
        result = await asyncio.to_thread(verify_claims, extraction, bundle, anthropic_client)
    except Exception:
        logger.exception("run failed: %s (shortcode=%s)", url, shortcode)
        yield {"event": "failed", "data": {"message": "Something went wrong while checking this reel."}}
        return

    await asyncio.to_thread(
        save_check,
        history_db_path,
        shortcode,
        url,
        transcript,
        result.model_dump_json(),
        reel.username,
        reel.caption,
        reel.product_type,
        reel.thumbnail_url,
    )
    logger.info(
        "run done: %s (shortcode=%s, score=%s, claims=%d)",
        url, shortcode, result.trustworthiness_score, len(result.claims),
    )
    yield {"event": "done", "data": result.model_dump()}
