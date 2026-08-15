from pydantic import BaseModel

from app.instagram import ReelData


class ClaimBundle(BaseModel):
    caption: str
    transcript: str | None
    source_url: str


def assemble(reel: ReelData, source_url: str, transcript: str | None) -> ClaimBundle:
    return ClaimBundle(
        caption=reel.caption,
        transcript=transcript,
        source_url=source_url,
    )
