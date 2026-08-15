import pytest

from app.instagram import extract_shortcode


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
