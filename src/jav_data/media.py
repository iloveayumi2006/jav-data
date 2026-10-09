"""Extract only the current product's original cover image."""

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup


def trusted_media_url(url: str) -> str:
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or not (
            host == "image.mgstage.com"
            or any(
                host == domain or host.endswith("." + domain) for domain in ("dmm.co.jp", "dmm.com")
            )
        )
    ):
        raise ValueError("Media URL is outside supported CDN hosts")
    return url


def original_image(url: str) -> str:
    parsed = urlsplit(trusted_media_url(url))
    if parsed.hostname == "awsimgsrc.dmm.co.jp" and parsed.path.startswith("/pics_dig/"):
        return urlunsplit(parsed._replace(query="", fragment=""))
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query)
        if key not in {"w", "h", "t", "width", "height"}
    ]
    return urlunsplit(parsed._replace(query=urlencode(query)))


def discover_images(html: str, product_id: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    if soup.select_one("a#EnlargeImage"):
        from jav_data.mgs import discover_cover

        return discover_cover(html, product_id)
    found = {}
    pattern = re.compile(rf"^{re.escape(product_id)}(pl)\.(jpg|jpeg|png|webp)$", re.I)
    for img in soup.select("img"):
        src = img.get("data-src") or img.get("src", "")
        if not src.startswith("https://"):
            continue
        filename = urlsplit(src).path.rsplit("/", 1)[-1]
        match = pattern.fullmatch(filename)
        if not match:
            continue
        try:
            url = original_image(src)
        except ValueError:
            continue
        extension = match.group(2).lower().replace("jpeg", "jpg")
        local = f"{product_id}-fanart.{extension}"
        priority = 2 if urlsplit(url).hostname == "awsimgsrc.dmm.co.jp" else 0
        if local not in found or priority > found[local]["priority"]:
            found[local] = {"kind": "cover", "url": url, "filename": local, "priority": priority}
    return [
        {key: value for key, value in item.items() if key != "priority"}
        for item in sorted(found.values(), key=lambda item: item["filename"])
    ]
