import httpx
import pytest

from app.instagram import InstagramFetchError, ReelData, extract_shortcode, fetch_reel_data


def test_extract_shortcode_from_reel_url():
    url = "https://www.instagram.com/reel/DcA42tvAIVu/?utm_source=ig_web_copy_link&igsh=abc123"
    assert extract_shortcode(url) == "DcA42tvAIVu"


def test_extract_shortcode_from_p_url():
    url = "https://www.instagram.com/p/Db2baM6oLQi/"
    assert extract_shortcode(url) == "Db2baM6oLQi"


def test_extract_shortcode_from_tv_url():
    url = "https://www.instagram.com/tv/Xyz123abc/"
    assert extract_shortcode(url) == "Xyz123abc"


def test_extract_shortcode_rejects_non_instagram_url():
    with pytest.raises(ValueError):
        extract_shortcode("https://example.com/reel/abc/")


def test_extract_shortcode_rejects_malformed_url():
    with pytest.raises(ValueError):
        extract_shortcode("not a url at all")


def _mock_client(html: str, status_code: int = 200) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text=html)

    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport)


@pytest.mark.asyncio
async def test_fetch_reel_data_parses_video_reel():
    html = open("tests/fixtures/embed_captioned_reel.html").read()
    async with _mock_client(html) as client:
        data = await fetch_reel_data("DcA42tvAIVu", client)

    assert data.username == "_mr.lion_"
    assert data.video_url == "https://instagram.fexample.fna.fbcdn.net/video.mp4?token=abc"
    assert data.caption == "Leave that man alone \U0001f62d\U0001f602"
    assert data.product_type == "clips"
    assert data.video_duration == 20.571


@pytest.mark.asyncio
async def test_fetch_reel_data_parses_image_post_without_video():
    html = open("tests/fixtures/embed_captioned_post.html").read()
    async with _mock_client(html) as client:
        data = await fetch_reel_data("Db2baM6oLQi", client)

    assert data.username == "centuryfinance.ch"
    assert data.video_url is None
    assert data.product_type == "feed"
    assert "franchise minimale" in data.caption
    assert data.thumbnail_url == "https://scontent.cdninstagram.com/thumb.jpg"


@pytest.mark.asyncio
async def test_fetch_reel_data_raises_on_non_200():
    async with _mock_client("not found", status_code=404) as client:
        with pytest.raises(InstagramFetchError):
            await fetch_reel_data("deadbeef123", client)


@pytest.mark.asyncio
async def test_fetch_reel_data_raises_on_malformed_json():
    html = '<script>window.__additionalData = "{not valid json";</script>'
    async with _mock_client(html) as client:
        with pytest.raises(InstagramFetchError):
            await fetch_reel_data("deadbeef123", client)
