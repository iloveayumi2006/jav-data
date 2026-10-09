"""MGS product adapter; retain original identifiers and Japanese metadata."""

import re
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup

from jav_data.models import utc_now
from jav_data.schemas import MovieInput


def distribution_id(identifier):
    match = re.fullmatch(r"([A-Za-z]+)-(\d+)", identifier)
    if not match:
        raise ValueError("Unsupported MGS product ID; expected letters-number, such as ABF-232")
    return match[1].lower() + match[2].zfill(5)


def original_product_id(url):
    parsed = urlsplit(url)
    match = re.fullmatch(r"/product/product_detail/([A-Za-z]+-\d+)/?", parsed.path)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"www.mgstage.com", "mgstage.com"}
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or not match
    ):
        raise ValueError("Use an HTTPS MGS product URL with a supported letters-number ID")
    identifier = match[1].upper()
    MovieInput(distribution_product_id=distribution_id(identifier), title="validation")
    return identifier


def canonical_product_url(url):
    return f"https://www.mgstage.com/product/product_detail/{original_product_id(url)}/"


def parse_product(html, source_url):
    from jav_data.scraper import LABELS, LIST_FIELDS, SessionRequired

    soup = BeautifulSoup(html, "html.parser")
    original_id = original_product_id(source_url)
    labels = {**LABELS, "出演": "actresses", "品番": "manufacturer_product_id"}
    values = {}
    container = soup.select_one(".detail_left") or soup.select_one(".detail_data")
    if container is None:
        if soup.select_one('input[type="password"]') or any(
            word in soup.get_text() for word in ("年齢認証", "年齢確認", "18歳", "ログイン")
        ):
            raise SessionRequired(
                "Complete MGS age confirmation/login, mark session ready, then retry"
            )
        raise ValueError("MGS product metadata could not be read; check the page or Japan IP")
    for row in container.select("tr"):
        cells = row.find_all(["td", "th"], recursive=False)
        if len(cells) >= 2:
            field = labels.get(cells[0].get_text(strip=True).rstrip("：:"))
            if field:
                values[field] = cells[1]
    title = soup.select_one("h1.tag")
    if not title or not title.get_text(strip=True):
        raise ValueError("MGS product title missing")
    product_node = values.get("manufacturer_product_id")
    if product_node is None or product_node.get_text(strip=True).upper() != original_id:
        raise ValueError("MGS page product ID does not match its URL")
    fields = dict(
        title=title.get_text(" ", strip=True),
        source_url=canonical_product_url(source_url),
        distribution_product_id=distribution_id(original_id),
        scraped_at=utc_now(),
    )
    for field, node in values.items():
        if field == "distribution_product_id":
            continue
        if field in LIST_FIELDS:
            items = [a.get_text(" ", strip=True) for a in node.select("a")]
            fields[field] = items or re.split(r"[\n、]+", node.get_text("\n", strip=True))
        else:
            text = node.get_text(" ", strip=True)
            if text and text not in {"---", "----", "―"}:
                fields[field] = text
    intro = soup.select_one(".introduction")
    meta = soup.select_one('meta[property="og:description"]')
    candidates = [intro.get_text("\n", strip=True) if intro else ""]
    if meta and meta.get("content"):
        candidates.append(meta["content"].strip())
    introduction = candidates[-1] or candidates[0]
    if introduction:
        fields["video_intro"] = introduction
    return MovieInput.model_validate(fields)


def discover_cover(html, product_id):
    from jav_data.media import trusted_media_url

    soup = BeautifulSoup(html, "html.parser")
    link = soup.select_one("a#EnlargeImage[href]")
    if link is None:
        raise ValueError("MGS enlarged cover link missing; refusing to download a thumbnail")
    url = trusted_media_url(link["href"])
    if urlsplit(url).hostname != "image.mgstage.com":
        raise ValueError("MGS cover must use the MGS image host")
    name = urlsplit(url).path.rsplit("/", 1)[-1]
    match = re.fullmatch(r"pb_e_([a-z]+-\d+)\.(jpg|jpeg|png|webp)", name, re.I)
    if not match or distribution_id(match[1]) != product_id:
        raise ValueError("MGS cover does not match the current product")
    extension = match[2].lower().replace("jpeg", "jpg")
    return [{"kind": "cover", "url": url, "filename": f"{product_id}-fanart.{extension}"}]


def parse_search_results(html, term, current_page):
    soup = BeautifulSoup(html, "html.parser")
    grid = soup.select_one("ul.product_list")
    if grid is None:
        text = soup.get_text(" ", strip=True)
        if any(word in text for word in ("該当する商品", "見つかりません", "検索結果がありません")):
            return [], None
        raise ValueError("MGS search results could not be read; check authentication and Japan IP")
    products = []
    for link in grid.select('a[href*="/product/product_detail/"]'):
        parsed = urlsplit(urljoin("https://www.mgstage.com/", link["href"]))
        if parsed.hostname != "www.mgstage.com" or parsed.scheme != "https":
            continue
        match = re.fullmatch(r"/product/product_detail/([A-Za-z0-9-]+)/?", parsed.path)
        if match:
            products.append(f"https://www.mgstage.com/product/product_detail/{match[1].upper()}/")
    next_pages = []
    for link in soup.select("a.page[href]"):
        parsed = urlsplit(urljoin("https://www.mgstage.com/search/cSearch.php", link["href"]))
        params = parse_qs(parsed.query)
        allowed = {"search_word", "type", "list_cnt", "page"}
        number = params.get("page", ["1"])[0]
        if (
            parsed.scheme == "https"
            and parsed.hostname == "www.mgstage.com"
            and parsed.path == "/search/cSearch.php"
            and params.get("search_word") == [term]
            and set(params) <= allowed
            and number.isdecimal()
            and int(number) > current_page
        ):
            next_pages.append(int(number))
    return list(dict.fromkeys(products)), min(next_pages) if next_pages else None
