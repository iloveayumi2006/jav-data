"""Background DMM keyword discovery, separate from metadata/download queues."""

import re
import threading
import uuid
from typing import Literal
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from jav_data.scraper import url_product_id

router = APIRouter()


def search_url(term, page=1, source="dmm"):
    if source == "mgs":
        return "https://www.mgstage.com/search/cSearch.php?" + urlencode(
            {"search_word": term, "page": page, "type": "top", "list_cnt": 120}
        )
    return "https://video.dmm.co.jp/av/list/?" + urlencode({"key": term, "page": page})


def parse_results(html, term, current_page):
    soup = BeautifulSoup(html, "html.parser")
    grid = soup.find(
        "ul",
        class_=lambda value: value and "grid-cols-[repeat(auto-fill,minmax(160px,1fr))]" in value,
    )
    text = soup.get_text(" ", strip=True)
    if grid is None:
        if re.search(
            r"0\s*タイトル|該当する商品はありません|検索結果がありません|"
            r"商品が見つかりません|商品は見つかりません",
            text,
        ):
            return [], None
        raise ValueError(
            "DMM search results could not be read. Check the session or search layout."
        )
    products = []
    seen = set()
    for link in grid.select('a[href*="/av/content/"]'):
        url = urljoin("https://video.dmm.co.jp", link["href"])
        if urlsplit(url).hostname != "video.dmm.co.jp":
            continue
        try:
            identifier = url_product_id(url)
        except ValueError:
            continue
        if identifier not in seen:
            seen.add(identifier)
            products.append("https://video.dmm.co.jp/av/content/?" + urlencode({"id": identifier}))
    next_pages = []
    for link in soup.select("a[href]"):
        parsed = urlsplit(urljoin("https://video.dmm.co.jp", link["href"]))
        params = parse_qs(parsed.query)
        if (
            parsed.hostname == "video.dmm.co.jp"
            and parsed.path == "/av/list/"
            and params.get("key") == [term]
        ):
            number = params.get("page", ["1"])[0]
            if number.isdecimal() and int(number) > current_page:
                next_pages.append(int(number))
    return products, min(next_pages) if next_pages else None


class Discovery:
    def __init__(self, settings, worker=None):
        self.settings = settings
        self.worker = worker
        self.lock = threading.Lock()
        self.jobs = {}
        self.thread = None
        self.stopping = threading.Event()

    def start(self, term, source="dmm"):
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise ValueError("A product search is already running. Wait for it to finish.")
            if not self.worker or self.worker.state != "ready":
                raise ValueError(
                    "Complete Website Authentication and mark the session ready first."
                )
            self.stopping.clear()
            while len(self.jobs) >= 10:
                self.jobs.pop(next(iter(self.jobs)))
            identifier = uuid.uuid4().hex
            self.jobs[identifier] = {
                "query": term,
                "source": source,
                "status": "running",
                "urls": [],
                "source_pages": 0,
                "error": None,
            }
            self.thread = threading.Thread(target=self.crawl, args=(identifier, term), daemon=True)
            self.thread.start()
            return identifier

    def snapshot(self, identifier, page):
        with self.lock:
            job = self.jobs.get(identifier)
            if job is None:
                return None
            return {
                **job,
                "urls": sorted(job["urls"])[(page - 1) * 100 : page * 100],
                "total": len(job["urls"]),
                "pages": max(1, (len(job["urls"]) + 99) // 100),
                "page": page,
            }

    def stop(self):
        self.stopping.set()
        if self.thread:
            self.thread.join(timeout=50)

    def cancel(self):
        self.stopping.set()

    def crawl(self, identifier, term):
        try:
            if not self.worker:
                raise ValueError("Open the DMM session browser and mark it ready first.")
            self.worker.command(
                lambda context: self.crawl_in_context(identifier, term, context)
            ).result()
        except Exception as error:
            with self.lock:
                self.jobs[identifier].update(status="failed", error=str(error))

    def crawl_in_context(self, identifier, term, context):
        page = context.new_page()
        try:
            number = 1
            source = self.jobs[identifier].get("source", "dmm")
            visited, seen = set(), set()
            while number is not None and not self.stopping.is_set():
                if number in visited:
                    raise ValueError(
                        "Website pagination repeated. Collected URLs are available, "
                        "but results are incomplete."
                    )
                visited.add(number)
                response = page.goto(
                    search_url(term, number, source), wait_until="domcontentloaded", timeout=45000
                )
                if response and response.status >= 400:
                    raise ValueError(
                        f"Website search returned HTTP {response.status}; results are incomplete."
                    )
                if (
                    urlsplit(page.url).hostname
                    not in (
                        {"www.mgstage.com", "mgstage.com"}
                        if source == "mgs"
                        else {"video.dmm.co.jp"}
                    )
                    or "age_check" in page.url
                ):
                    raise ValueError(
                        "Website requires confirmation/login. Complete it in the session "
                        "browser and mark it ready, then search again."
                    )
                try:
                    page.wait_for_function(
                        "() => document.querySelector('ul.product_list') || "
                        "/見つかりません/.test(document.body.innerText)"
                        if source == "mgs"
                        else "() => document.querySelector("
                        "'ul[class*=grid-cols] a[href*=\"/av/content/\"]') || "
                        "/該当する商品はありません|検索結果がありません|"
                        "商品が見つかりません|商品は見つかりません/"
                        ".test(document.body.innerText)",
                        timeout=20000,
                    )
                except TimeoutError:
                    # The initial loading screen also says '0 titles'. Only accept
                    # that empty state after allowing client-side results to load.
                    pass
                if source == "mgs":
                    from jav_data.mgs import parse_search_results

                    urls, next_page = parse_search_results(page.content(), term, number)
                else:
                    urls, next_page = parse_results(page.content(), term, number)
                with self.lock:
                    job = self.jobs[identifier]
                    for url in urls:
                        if url not in seen:
                            seen.add(url)
                            job["urls"].append(url)
                    job["source_pages"] += 1
                number = next_page
                if number is not None:
                    self.stopping.wait(1)
            with self.lock:
                self.jobs[identifier]["status"] = (
                    "cancelled" if self.stopping.is_set() else "completed"
                )
        finally:
            try:
                context.storage_state(path=str(self.settings.data_dir / "browser-session.json"))
            finally:
                page.close()


class SearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    source: Literal["dmm", "mgs"] = "dmm"


@router.post("/api/product-searches", status_code=202)
def start_search(payload: SearchInput, request: Request):
    term = payload.query.strip()
    if not term:
        raise HTTPException(422, "Enter a search keyword")
    try:
        identifier = (
            request.app.state.discovery.start(term, "mgs")
            if payload.source == "mgs"
            else request.app.state.discovery.start(term)
        )
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    return {"id": identifier}


@router.get("/api/product-searches/{identifier}")
def results(identifier: str, request: Request, page: int = Query(1, ge=1)):
    job = request.app.state.discovery.snapshot(identifier, page)
    if job is None:
        raise HTTPException(404, "Search expired or app restarted; run the search again")
    return job


@router.get("/api/product-searches/{identifier}/download")
def download(identifier: str, request: Request):
    with request.app.state.discovery.lock:
        job = request.app.state.discovery.jobs.get(identifier)
        if job is None:
            raise HTTPException(404, "Search not found")
        content = "\n".join(sorted(job["urls"]))
    return Response(
        content,
        media_type="text/plain",
        headers={"Content-Disposition": 'attachment; filename="product-urls.txt"'},
    )
