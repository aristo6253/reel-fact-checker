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


# Instagram's embed endpoint 404s without a type segment; any of p/reel/tv works
# regardless of the post's actual type, so "reel" is hardcoded rather than threading
# the matched type through extract_shortcode's return value.
EMBED_URL_TEMPLATE = "https://www.instagram.com/reel/{shortcode}/embed/captioned/"
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
    image_urls: list[str] = []


async def fetch_reel_data(shortcode: str, client: httpx.AsyncClient) -> ReelData:
    url = EMBED_URL_TEMPLATE.format(shortcode=shortcode)
    response = await client.get(url, headers={"User-Agent": _UA})
    if response.status_code != 200:
        raise InstagramFetchError(f"fetch failed with status {response.status_code} for {shortcode}")

    body = response.text
    # Instagram moves this payload around (was `window.__additionalData = "...";`,
    # now buried inside a ServerJS `s.handle({...})` blob under a shifting key) but
    # it's always a double-JSON-encoded string containing this marker, so match the
    # containing JSON string literal directly rather than a specific variable name.
    # `(?:[^"\\]|\\.)*` is the standard "JSON string body" pattern: any non-quote,
    # non-backslash char, or a backslash followed by anything (handles `\"`, `\\`,
    # `\/`, `\uXXXX` uniformly).
    match = re.search(r'"((?:[^"\\]|\\.)*edge_media_to_caption(?:[^"\\]|\\.)*)"', body)
    if not match:
        raise InstagramFetchError(f"no post data found for {shortcode}")

    try:
        inner_json_text = json.loads('"' + match.group(1) + '"')
        payload = json.loads(inner_json_text)
        media = payload.get("gql_data", {}).get("shortcode_media") or payload.get(
            "gql_data", {}
        ).get("xdt_shortcode_media", {})
        caption_edges = media.get("edge_media_to_caption", {}).get("edges", [])
        caption = caption_edges[0]["node"]["text"] if caption_edges else ""
    except (json.JSONDecodeError, KeyError, IndexError) as exc:
        raise InstagramFetchError(f"could not parse post data for {shortcode}") from exc

    # og:image meta tag is frequently absent from the current page (Instagram doesn't
    # always render it), so prefer the media object's own image fields first.
    thumbnail_url = media.get("display_url") or media.get("thumbnail_src")
    if not thumbnail_url:
        thumbnail_match = re.search(r'<meta property="og:image" content="([^"]*)"', body)
        thumbnail_url = html_lib.unescape(thumbnail_match.group(1)) if thumbnail_match else None

    # Carousel posts have no top-level product_type or video_url — the actual content
    # (images, sometimes video clips) lives one level down, per slide.
    sidecar_edges = media.get("edge_sidecar_to_children", {}).get("edges", [])
    image_urls = [edge["node"]["display_url"] for edge in sidecar_edges if edge["node"].get("display_url")]
    product_type = media.get("product_type") or ("carousel" if sidecar_edges else "unknown")

    return ReelData(
        username=media.get("owner", {}).get("username", ""),
        caption=caption,
        video_url=media.get("video_url"),
        product_type=product_type,
        video_duration=media.get("video_duration"),
        thumbnail_url=thumbnail_url,
        image_urls=image_urls,
    )
