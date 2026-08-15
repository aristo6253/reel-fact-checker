import html as html_lib
import json
import re
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel

_SHORTCODE_RE = re.compile(r"^/(p|reel|tv)/([A-Za-z0-9_-]+)/?$")


def extract_shortcode(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc not in ("www.instagram.com", "instagram.com"):
        raise ValueError(f"not an Instagram URL: {url}")
    match = _SHORTCODE_RE.match(parsed.path)
    if not match:
        raise ValueError(f"could not find a shortcode in: {url}")
    return match.group(2)


EMBED_URL_TEMPLATE = "https://www.instagram.com/{shortcode}/embed/captioned/"
_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


class InstagramFetchError(Exception):
    pass


class ReelData(BaseModel):
    username: str
    caption: str
    video_url: str | None
    product_type: str
    video_duration: float | None = None
    thumbnail_url: str | None = None


async def fetch_reel_data(shortcode: str, client: httpx.AsyncClient) -> ReelData:
    url = EMBED_URL_TEMPLATE.format(shortcode=shortcode)
    response = await client.get(url, headers={"User-Agent": _UA})
    if response.status_code != 200:
        raise InstagramFetchError(f"fetch failed with status {response.status_code} for {shortcode}")

    body = response.text
    match = re.search(r'window\.__additionalData\s*=\s*"(.*?)";', body)
    if not match:
        raise InstagramFetchError(f"no post data found for {shortcode}")

    # The blob is JSON, itself JSON-encoded again as a string for embedding
    # in the page's JS (Instagram double-encodes: the object is serialized
    # to JSON text, then that text is serialized again as a JSON string
    # literal). Decode in two passes: the first pass undoes the outer
    # string-literal escaping (standard JSON string rules handle `\"`,
    # `\\`, `\/`, and `\uXXXX` uniformly — no hand-rolled regex needed) and
    # yields the inner JSON text; the second pass parses that text into the
    # actual object.
    inner_json_text = json.loads('"' + match.group(1) + '"')
    payload = json.loads(inner_json_text)

    caption_edges = payload.get("edge_media_to_caption", {}).get("edges", [])
    caption = caption_edges[0]["node"]["text"] if caption_edges else ""

    thumbnail_match = re.search(r'<meta property="og:image" content="([^"]*)"', body)
    thumbnail_url = html_lib.unescape(thumbnail_match.group(1)) if thumbnail_match else None

    return ReelData(
        username=payload.get("username", ""),
        caption=caption,
        video_url=payload.get("video_url"),
        product_type=payload.get("product_type", "unknown"),
        video_duration=payload.get("video_duration"),
        thumbnail_url=thumbnail_url,
    )
