"""Product URL validation and a conservative HTML metadata adapter."""

import re
from urllib.parse import parse_qs, unquote, urlsplit

from bs4 import BeautifulSoup

from jav_data.models import utc_now
from jav_data.schemas import MovieInput

LABELS = {
    "配信開始日": "streaming_release_date",
    "商品発売日": "product_release_date",
    "発売日": "product_release_date",
    "収録時間": "runtime",
    "出演者": "actresses",
    "監督": "directors",
    "シリーズ": "series",
    "メーカー": "maker",
    "レーベル": "label",
    "ジャンル": "genres",
    "関連タグ": "related_tags",
    "配信品番": "distribution_product_id",
    "メーカー品番": "manufacturer_product_id",
}
LIST_FIELDS = {"actresses", "directors", "genres", "related_tags"}


class SessionRequired(ValueError):
    pass


def product_url(value: str) -> str:
    value = value.strip()
    url = urlsplit(value)
    if url.hostname in {"www.mgstage.com", "mgstage.com"}:
        from jav_data.mgs import canonical_product_url

        return canonical_product_url(value)
    if (
        url.scheme != "https"
        or url.username
        or url.password
        or url.port not in (None, 443)
        or url.hostname not in {"www.dmm.co.jp", "dmm.co.jp", "video.dmm.co.jp"}
    ):
        raise ValueError("Use an HTTPS DMM or MGS product URL")
    if "/detail/" not in url.path and not url.path.startswith("/av/content/"):
        raise ValueError("Use a product detail URL, not a discovery or actress page")
    url_product_id(value)
    return value


def url_product_id(value: str) -> str:
    url = urlsplit(value)
    if url.hostname in {"www.mgstage.com", "mgstage.com"}:
        from jav_data.mgs import distribution_id, original_product_id

        return distribution_id(original_product_id(value))
    match = re.search(r"(?:^|/)cid=([^/]+)", unquote(url.path))
    query = parse_qs(url.query)
    identifier = match.group(1) if match else (query.get("cid") or query.get("id") or [""])[0]
    if not identifier:
        raise ValueError("Product URL must contain cid or id")
    return MovieInput(
        distribution_product_id=identifier, title="validation"
    ).distribution_product_id


def parse_product(html: str, source_url: str) -> MovieInput:
    if urlsplit(source_url).hostname in {"www.mgstage.com", "mgstage.com"}:
        from jav_data.mgs import parse_product as parse_mgs_product

        return parse_mgs_product(html, source_url)
    soup = BeautifulSoup(html, "html.parser")
    if soup.select_one('input[type="password"]'):
        raise SessionRequired(
            "Login is required. Complete login in the session browser, then retry."
        )
    values = {}
    for row in soup.select("tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        if len(cells) < 2:
            continue
        label = cells[0].get_text("", strip=True).rstrip("：:")
        if label in LABELS:
            values[LABELS[label]] = cells[1]
    for term in soup.select("dt"):
        label = term.get_text("", strip=True).rstrip("：:")
        detail = term.find_next_sibling("dd")
        if label in LABELS and detail is not None:
            values[LABELS[label]] = detail
    # New layouts may use a text label followed by a sibling value container.
    for label_node in soup.find_all(["span", "div", "p"]):
        if len(label_node.get_text(strip=True)) > 16:
            continue
        label = label_node.get_text("", strip=True).rstrip("：:")
        sibling = label_node.find_next_sibling()
        if label in LABELS and LABELS[label] not in values and sibling is not None:
            values[LABELS[label]] = sibling
    if not values:
        text = soup.get_text(" ", strip=True)
        if any(word in text for word in ("18歳", "年齢認証", "年齢確認", "ログイン")):
            raise SessionRequired(
                "Complete age confirmation or login in the session browser, then retry."
            )
        raise ValueError("No product metadata found; page may be blocked or its layout unsupported")
    title_node = soup.select_one("h1#title, h1[itemprop='name'], h1")
    meta = soup.select_one('meta[property="og:title"]')
    title = (
        title_node.get_text(" ", strip=True)
        if title_node
        else (meta.get("content", "") if meta else "")
    )
    if not title:
        raise ValueError("Product title missing; refusing to save an incomplete page")
    fields = {"title": title, "source_url": source_url, "scraped_at": utc_now()}
    for field, node in values.items():
        if field in LIST_FIELDS:
            links = [a.get_text(" ", strip=True) for a in node.select("a")]
            text = node.get_text("\n", strip=True)
            items = links or re.split(r"[\n、]+", text)
            fields[field] = [item for item in items if item and item not in {"----", "---", "―"}]
        else:
            text = node.get_text(" ", strip=True)
            if text and text not in {"----", "---", "―"}:
                fields[field] = text
    fields.setdefault("distribution_product_id", url_product_id(source_url))
    intro = soup.select_one(
        "[itemprop='description'], .mg-b20.lh4, .summary__txt, .product-introduction, "
        "#introduction, div[class~='leading-[16.8px]'] > div:first-child"
    )
    if intro:
        fields["video_intro"] = intro.get_text("\n", strip=True)
    return MovieInput.model_validate(fields)
