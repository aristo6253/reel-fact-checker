import re
from urllib.parse import urlparse

_SHORTCODE_RE = re.compile(r"^/(p|reel|tv)/([A-Za-z0-9_-]+)/?$")


def extract_shortcode(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc not in ("www.instagram.com", "instagram.com"):
        raise ValueError(f"not an Instagram URL: {url}")
    match = _SHORTCODE_RE.match(parsed.path)
    if not match:
        raise ValueError(f"could not find a shortcode in: {url}")
    return match.group(2)
