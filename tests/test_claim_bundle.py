from app.claim_bundle import assemble
from app.instagram import ReelData


def test_assemble_builds_bundle_with_all_fields():
    reel = ReelData(
        username="someone",
        caption="A claim about something.",
        video_url="https://example.com/v.mp4",
        product_type="clips",
    )

    bundle = assemble(
        reel=reel,
        source_url="https://www.instagram.com/reel/abc123/",
        transcript="spoken words here",
    )

    assert bundle.caption == "A claim about something."
    assert bundle.transcript == "spoken words here"
    assert bundle.source_url == "https://www.instagram.com/reel/abc123/"


def test_assemble_allows_no_transcript():
    reel = ReelData(username="x", caption="caption only", video_url=None, product_type="feed")
    bundle = assemble(reel=reel, source_url="https://www.instagram.com/p/xyz/", transcript=None)
    assert bundle.transcript is None
