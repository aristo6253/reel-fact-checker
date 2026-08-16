from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.claim_bundle import ClaimBundle
from app.claude_client import Claim, ExtractionResult, Verdict, VerdictResult
from app.instagram import InstagramFetchError, ReelData
from app.pipeline import run_pipeline


@pytest.mark.asyncio
async def test_pipeline_yields_error_on_fetch_failure():
    with patch("app.pipeline.extract_shortcode", return_value="abc123"), patch(
        "app.pipeline.fetch_reel_data", new=AsyncMock(side_effect=InstagramFetchError("boom"))
    ):
        events = [e async for e in run_pipeline("https://www.instagram.com/reel/abc123/", MagicMock(), MagicMock())]

    assert events[-1]["event"] == "error"
    assert "couldn't access this reel" in events[-1]["data"]["message"].lower()


@pytest.mark.asyncio
async def test_pipeline_skips_transcription_for_silent_video():
    reel = ReelData(username="u", caption="A caption claim.", video_url="https://x/v.mp4", product_type="clips")
    extraction = ExtractionResult(claims=[Claim(text="A caption claim.", classification="factual")])
    verdict = VerdictResult(
        headline_verdict="ok",
        claims=[Verdict(claim="A caption claim.", classification="factual", verdict="verified", explanation="e", sources=[])],
    )

    with patch("app.pipeline.extract_shortcode", return_value="abc123"), patch(
        "app.pipeline.fetch_reel_data", new=AsyncMock(return_value=reel)
    ), patch("app.pipeline.download_video", new=AsyncMock(return_value="/tmp/fake.mp4")), patch(
        "app.pipeline.extract_audio_rms", return_value=1.0
    ), patch("app.pipeline.has_narration", return_value=False), patch(
        "app.pipeline.transcribe"
    ) as mock_transcribe, patch(
        "app.pipeline.extract_claims", return_value=extraction
    ), patch(
        "app.pipeline.verify_claims", return_value=verdict
    ), patch("os.remove"):
        events = [e async for e in run_pipeline("https://www.instagram.com/reel/abc123/", MagicMock(), MagicMock())]

    mock_transcribe.assert_not_called()
    assert events[-1]["event"] == "done"
    assert events[-1]["data"]["headline_verdict"] == "ok"


@pytest.mark.asyncio
async def test_pipeline_transcribes_when_narration_detected():
    reel = ReelData(username="u", caption="A caption claim.", video_url="https://x/v.mp4", product_type="clips")
    extraction = ExtractionResult(claims=[Claim(text="Narrated claim.", classification="factual")])
    verdict = VerdictResult(
        headline_verdict="ok",
        claims=[Verdict(claim="Narrated claim.", classification="factual", verdict="verified", explanation="e", sources=[])],
    )

    with patch("app.pipeline.extract_shortcode", return_value="abc123"), patch(
        "app.pipeline.fetch_reel_data", new=AsyncMock(return_value=reel)
    ), patch("app.pipeline.download_video", new=AsyncMock(return_value="/tmp/fake.mp4")), patch(
        "app.pipeline.extract_audio_rms", return_value=1000.0
    ), patch("app.pipeline.has_narration", return_value=True), patch(
        "app.pipeline.transcribe", return_value="narrated words"
    ), patch(
        "app.pipeline.extract_claims", return_value=extraction
    ), patch(
        "app.pipeline.verify_claims", return_value=verdict
    ), patch("os.remove") as mock_remove:
        events = [e async for e in run_pipeline("https://www.instagram.com/reel/abc123/", MagicMock(), MagicMock())]

    event_names = [e["event"] for e in events]
    assert event_names == ["fetching", "transcribing", "extracting_claims", "verifying_claims", "done"]
    mock_remove.assert_called_once_with("/tmp/fake.mp4")


@pytest.mark.asyncio
async def test_pipeline_skips_video_steps_when_no_video_url():
    reel = ReelData(username="u", caption="A caption claim.", video_url=None, product_type="clips")
    extraction = ExtractionResult(claims=[Claim(text="A caption claim.", classification="factual")])
    verdict = VerdictResult(
        headline_verdict="ok",
        claims=[Verdict(claim="A caption claim.", classification="factual", verdict="verified", explanation="e", sources=[])],
    )

    with patch("app.pipeline.extract_shortcode", return_value="abc123"), patch(
        "app.pipeline.fetch_reel_data", new=AsyncMock(return_value=reel)
    ), patch("app.pipeline.download_video", new=AsyncMock()) as mock_download, patch(
        "app.pipeline.extract_claims", return_value=extraction
    ), patch("app.pipeline.verify_claims", return_value=verdict):
        events = [e async for e in run_pipeline("https://www.instagram.com/reel/abc123/", MagicMock(), MagicMock())]

    mock_download.assert_not_called()
    event_names = [e["event"] for e in events]
    assert event_names == ["fetching", "extracting_claims", "verifying_claims", "done"]


@pytest.mark.asyncio
async def test_pipeline_yields_error_when_downstream_stage_raises():
    reel = ReelData(username="u", caption="A caption claim.", video_url=None, product_type="clips")

    with patch("app.pipeline.extract_shortcode", return_value="abc123"), patch(
        "app.pipeline.fetch_reel_data", new=AsyncMock(return_value=reel)
    ), patch("app.pipeline.extract_claims", side_effect=RuntimeError("Claude API timeout")):
        events = [e async for e in run_pipeline("https://www.instagram.com/reel/abc123/", MagicMock(), MagicMock())]

    assert events[-1]["event"] == "error"
    assert events[-1]["data"]["message"] == "Something went wrong while checking this reel."
