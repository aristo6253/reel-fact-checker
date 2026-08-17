from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.claim_bundle import ClaimBundle
from app.claude_client import Claim, ExtractionResult, Verdict, VerdictResult
from app.instagram import InstagramFetchError, ReelData
from app.pipeline import run_pipeline


@pytest.fixture(autouse=True)
def _no_history(monkeypatch):
    """Default all pipeline tests to a cache miss + no-op save, so they never touch disk.
    Tests that care about caching behavior override these explicitly."""
    monkeypatch.setattr("app.pipeline.get_cached", lambda db_path, shortcode: None)
    monkeypatch.setattr("app.pipeline.save_check", lambda *args, **kwargs: None)


@pytest.mark.asyncio
async def test_pipeline_yields_error_on_fetch_failure():
    with patch("app.pipeline.extract_shortcode", return_value="abc123"), patch(
        "app.pipeline.fetch_reel_data", new=AsyncMock(side_effect=InstagramFetchError("boom"))
    ):
        events = [e async for e in run_pipeline("https://www.instagram.com/reel/abc123/", MagicMock(), MagicMock(), "test.db")]

    assert events[-1]["event"] == "failed"
    assert "couldn't access this reel" in events[-1]["data"]["message"].lower()


@pytest.mark.asyncio
async def test_pipeline_no_claims_at_all_has_no_trustworthiness_score():
    reel = ReelData(username="u", caption="Nice weather today", video_url=None, product_type="feed")

    with patch("app.pipeline.extract_shortcode", return_value="abc123"), patch(
        "app.pipeline.fetch_reel_data", new=AsyncMock(return_value=reel)
    ), patch("app.pipeline.extract_claims", return_value=ExtractionResult(claims=[])):
        events = [e async for e in run_pipeline("https://www.instagram.com/reel/abc123/", MagicMock(), MagicMock(), "test.db")]

    assert events[-1]["event"] == "done"
    assert events[-1]["data"]["trustworthiness_score"] is None


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
        events = [e async for e in run_pipeline("https://www.instagram.com/reel/abc123/", MagicMock(), MagicMock(), "test.db")]

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
        events = [e async for e in run_pipeline("https://www.instagram.com/reel/abc123/", MagicMock(), MagicMock(), "test.db")]

    event_names = [e["event"] for e in events]
    assert event_names == [
        "fetching",
        "reel_info",
        "transcribing",
        "transcript",
        "extracting_claims",
        "verifying_claims",
        "done",
    ]
    transcript_event = next(e for e in events if e["event"] == "transcript")
    assert transcript_event["data"]["transcript"] == "narrated words"
    reel_info_event = next(e for e in events if e["event"] == "reel_info")
    assert reel_info_event["data"]["username"] == "u"
    assert reel_info_event["data"]["caption"] == "A caption claim."
    mock_remove.assert_called_once_with("/tmp/fake.mp4")


@pytest.mark.asyncio
async def test_pipeline_downloads_and_passes_carousel_images_to_extraction():
    reel = ReelData(
        username="u",
        caption="See slides",
        video_url=None,
        product_type="carousel",
        image_urls=["https://x/slide1.jpg", "https://x/slide2.jpg"],
    )
    extraction = ExtractionResult(claims=[Claim(text="A slide claim.", classification="factual")])
    verdict = VerdictResult(
        headline_verdict="ok",
        claims=[Verdict(claim="A slide claim.", classification="factual", verdict="verified", explanation="e", sources=[])],
    )

    with patch("app.pipeline.extract_shortcode", return_value="abc123"), patch(
        "app.pipeline.fetch_reel_data", new=AsyncMock(return_value=reel)
    ), patch(
        "app.pipeline.download_image_base64",
        new=AsyncMock(side_effect=lambda url, client: {"media_type": "image/jpeg", "data": f"b64:{url}"}),
    ) as mock_download_image, patch(
        "app.pipeline.extract_claims", return_value=extraction
    ) as mock_extract_claims, patch(
        "app.pipeline.verify_claims", return_value=verdict
    ):
        events = [e async for e in run_pipeline("https://www.instagram.com/p/abc123/", MagicMock(), MagicMock(), "test.db")]

    assert mock_download_image.call_count == 2
    passed_images = mock_extract_claims.call_args.args[2]
    assert passed_images == [
        {"media_type": "image/jpeg", "data": "b64:https://x/slide1.jpg"},
        {"media_type": "image/jpeg", "data": "b64:https://x/slide2.jpg"},
    ]
    reel_info_event = next(e for e in events if e["event"] == "reel_info")
    assert reel_info_event["data"]["image_urls"] == ["https://x/slide1.jpg", "https://x/slide2.jpg"]
    assert events[-1]["event"] == "done"


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
        events = [e async for e in run_pipeline("https://www.instagram.com/reel/abc123/", MagicMock(), MagicMock(), "test.db")]

    mock_download.assert_not_called()
    event_names = [e["event"] for e in events]
    assert event_names == ["fetching", "reel_info", "transcript", "extracting_claims", "verifying_claims", "done"]


@pytest.mark.asyncio
async def test_pipeline_returns_cached_result_without_rerunning_checks():
    reel = ReelData(username="u", caption="A caption claim.", video_url=None, product_type="clips")
    cached = {
        "url": "https://www.instagram.com/reel/abc123/",
        "transcript": "old transcript",
        "result": {"headline_verdict": "ok", "trustworthiness_score": 80, "claims": []},
        "checked_at": "2026-08-01T00:00:00+00:00",
    }

    with patch("app.pipeline.extract_shortcode", return_value="abc123"), patch(
        "app.pipeline.fetch_reel_data", new=AsyncMock(return_value=reel)
    ), patch("app.pipeline.get_cached", return_value=cached), patch(
        "app.pipeline.extract_claims"
    ) as mock_extract_claims, patch(
        "app.pipeline.verify_claims"
    ) as mock_verify_claims:
        events = [e async for e in run_pipeline("https://www.instagram.com/reel/abc123/", MagicMock(), MagicMock(), "test.db")]

    mock_extract_claims.assert_not_called()
    mock_verify_claims.assert_not_called()
    event_names = [e["event"] for e in events]
    assert event_names == ["fetching", "reel_info", "transcript", "cached"]
    assert events[-1]["data"]["headline_verdict"] == "ok"
    assert events[-1]["data"]["trustworthiness_score"] == 80
    assert events[-1]["data"]["checked_at"] == "2026-08-01T00:00:00+00:00"


@pytest.mark.asyncio
async def test_pipeline_force_bypasses_cache():
    reel = ReelData(username="u", caption="A caption claim.", video_url=None, product_type="clips")
    extraction = ExtractionResult(claims=[Claim(text="A caption claim.", classification="factual")])
    verdict = VerdictResult(
        headline_verdict="fresh result",
        claims=[Verdict(claim="A caption claim.", classification="factual", verdict="verified", explanation="e", sources=[])],
    )
    cached = {
        "url": "https://www.instagram.com/reel/abc123/",
        "transcript": None,
        "result": {"headline_verdict": "stale result", "trustworthiness_score": 50, "claims": []},
        "checked_at": "2026-08-01T00:00:00+00:00",
    }

    with patch("app.pipeline.extract_shortcode", return_value="abc123"), patch(
        "app.pipeline.fetch_reel_data", new=AsyncMock(return_value=reel)
    ), patch("app.pipeline.get_cached", return_value=cached) as mock_get_cached, patch(
        "app.pipeline.extract_claims", return_value=extraction
    ), patch("app.pipeline.verify_claims", return_value=verdict):
        events = [
            e
            async for e in run_pipeline(
                "https://www.instagram.com/reel/abc123/", MagicMock(), MagicMock(), "test.db", force=True
            )
        ]

    mock_get_cached.assert_called_once()
    assert events[-1]["event"] == "done"
    assert events[-1]["data"]["headline_verdict"] == "fresh result"


@pytest.mark.asyncio
async def test_pipeline_force_recheck_reuses_cached_transcript_without_redownloading_video():
    reel = ReelData(username="u", caption="A caption claim.", video_url="https://x/v.mp4", product_type="clips")
    extraction = ExtractionResult(claims=[Claim(text="A caption claim.", classification="factual")])
    verdict = VerdictResult(
        headline_verdict="fresh result",
        claims=[Verdict(claim="A caption claim.", classification="factual", verdict="verified", explanation="e", sources=[])],
    )
    cached = {
        "url": "https://www.instagram.com/reel/abc123/",
        "transcript": "previously transcribed audio",
        "result": {"headline_verdict": "stale result", "trustworthiness_score": 50, "claims": []},
        "checked_at": "2026-08-01T00:00:00+00:00",
    }

    with patch("app.pipeline.extract_shortcode", return_value="abc123"), patch(
        "app.pipeline.fetch_reel_data", new=AsyncMock(return_value=reel)
    ), patch("app.pipeline.get_cached", return_value=cached), patch(
        "app.pipeline.download_video", new=AsyncMock()
    ) as mock_download_video, patch("app.pipeline.transcribe") as mock_transcribe, patch(
        "app.pipeline.extract_claims", return_value=extraction
    ) as mock_extract_claims, patch("app.pipeline.verify_claims", return_value=verdict):
        events = [
            e
            async for e in run_pipeline(
                "https://www.instagram.com/reel/abc123/", MagicMock(), MagicMock(), "test.db", force=True
            )
        ]

    mock_download_video.assert_not_called()
    mock_transcribe.assert_not_called()
    transcript_event = next(e for e in events if e["event"] == "transcript")
    assert transcript_event["data"]["transcript"] == "previously transcribed audio"
    bundle_arg = mock_extract_claims.call_args.args[0]
    assert bundle_arg.transcript == "previously transcribed audio"
    assert events[-1]["event"] == "done"


@pytest.mark.asyncio
async def test_pipeline_saves_result_after_successful_check():
    reel = ReelData(username="u", caption="A caption claim.", video_url=None, product_type="clips")
    extraction = ExtractionResult(claims=[Claim(text="A caption claim.", classification="factual")])
    verdict = VerdictResult(
        headline_verdict="ok",
        claims=[Verdict(claim="A caption claim.", classification="factual", verdict="verified", explanation="e", sources=[])],
    )

    with patch("app.pipeline.extract_shortcode", return_value="abc123"), patch(
        "app.pipeline.fetch_reel_data", new=AsyncMock(return_value=reel)
    ), patch("app.pipeline.extract_claims", return_value=extraction), patch(
        "app.pipeline.verify_claims", return_value=verdict
    ), patch("app.pipeline.save_check") as mock_save_check:
        events = [
            e
            async for e in run_pipeline(
                "https://www.instagram.com/reel/abc123/", MagicMock(), MagicMock(), "history.db"
            )
        ]

    assert events[-1]["event"] == "done"
    mock_save_check.assert_called_once()
    args = mock_save_check.call_args.args
    assert args[0] == "history.db"
    assert args[1] == "abc123"
    assert args[2] == "https://www.instagram.com/reel/abc123/"


@pytest.mark.asyncio
async def test_pipeline_yields_error_when_downstream_stage_raises():
    reel = ReelData(username="u", caption="A caption claim.", video_url=None, product_type="clips")

    with patch("app.pipeline.extract_shortcode", return_value="abc123"), patch(
        "app.pipeline.fetch_reel_data", new=AsyncMock(return_value=reel)
    ), patch("app.pipeline.extract_claims", side_effect=RuntimeError("Claude API timeout")):
        events = [e async for e in run_pipeline("https://www.instagram.com/reel/abc123/", MagicMock(), MagicMock(), "test.db")]

    assert events[-1]["event"] == "failed"
    assert events[-1]["data"]["message"] == "Something went wrong while checking this reel."
