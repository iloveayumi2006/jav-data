from concurrent.futures import Future
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from jav_data.discovery import Discovery, parse_results, router, search_url


def result_html(start, stop, next_page=None, term="name"):
    links = "".join(
        f'<a href="/av/content/?id=demo{n:05d}&amp;i3_ref=search">product</a>' * 2
        for n in range(start, stop)
    )
    pagination = (
        f'<a href="/av/list/?key={term}&amp;page={next_page}">Next</a>' if next_page else ""
    )
    return (
        '<ul class="grid grid-cols-[repeat(auto-fill,minmax(160px,1fr))]">'
        + links
        + "</ul>"
        + pagination
        + '<a href="/av/content/?id=unrelated001">Recommendation</a>'
    )


def test_parser_deduplicates_excludes_recommendations_and_follows_same_query():
    urls, next_page = parse_results(result_html(0, 120, 2), "name", 1)
    assert len(urls) == 120
    assert next_page == 2
    assert urls[0] == "https://video.dmm.co.jp/av/content/?id=demo00000"
    assert all("unrelated" not in url and "i3_ref" not in url for url in urls)
    assert parse_results(result_html(0, 1, 2, term="other"), "name", 1)[1] is None
    assert parse_results("<p>0 タイトル</p>", "name", 1) == ([], None)
    assert parse_results("<p>キーワードに一致する商品は見つかりませんでした。</p>", "name", 1) == (
        [],
        None,
    )
    with pytest.raises(ValueError, match="could not be read"):
        parse_results("<p>Login required</p>", "name", 1)


def test_keyword_encoding():
    term = "出演者 & メーカー"
    assert parse_qs(urlsplit(search_url(term)).query) == {"key": [term], "page": ["1"]}


def test_full_crawl_pagination_and_partial_failure(tmp_path, monkeypatch):
    (tmp_path / "browser-session.json").write_text("{}")
    worker = Discovery(SimpleNamespace(data_dir=tmp_path))
    pages = {1: result_html(0, 120, 2), 2: result_html(119, 240, 3), 3: result_html(240, 245)}

    class Page:
        def goto(self, url, **kwargs):
            self.url = url
            self.number = int(parse_qs(urlsplit(url).query)["page"][0])
            return SimpleNamespace(status=200)

        def wait_for_function(self, *args, **kwargs):
            pass

        def content(self):
            return pages[self.number]

        def close(self):
            pass

    class Browser:
        def new_page(self):
            return Page()

        def storage_state(self, **kwargs):
            pass

        def close(self):
            pytest.fail("Discovery must keep the shared Edge browser open")

    def command(action):
        future = Future()
        try:
            future.set_result(action(Browser()))
        except Exception as error:
            future.set_exception(error)
        return future

    worker.worker = SimpleNamespace(state="ready", command=command)
    worker.jobs["test"] = {
        "query": "name",
        "status": "running",
        "urls": [],
        "source_pages": 0,
        "error": None,
    }
    worker.crawl("test", "name")
    assert worker.snapshot("test", 1)["status"] == "completed"
    assert worker.snapshot("test", 1)["total"] == 245
    assert [len(worker.snapshot("test", page)["urls"]) for page in (1, 2, 3)] == [100, 100, 45]
    assert worker.snapshot("test", 3)["source_pages"] == 3
    assert worker.snapshot("unknown", 1) is None
    pages[2] = "<p>Unexpected layout</p>"
    worker.jobs["test"]["urls"] = []
    worker.crawl("test", "name")
    assert worker.snapshot("test", 1)["status"] == "failed"
    assert worker.snapshot("test", 1)["total"] == 120


def test_missing_session_and_concurrent_search(tmp_path):
    worker = Discovery(SimpleNamespace(data_dir=tmp_path))
    worker.jobs["test"] = {"urls": [], "source_pages": 0}
    worker.crawl("test", "name")
    assert worker.snapshot("test", 1)["status"] == "failed"
    assert "session browser" in worker.snapshot("test", 1)["error"]
    worker.thread = SimpleNamespace(is_alive=lambda: True)
    with pytest.raises(ValueError, match="already running"):
        worker.start("name")


def test_api_validation_pagination_and_text_export(tmp_path, monkeypatch):
    app = FastAPI()
    app.include_router(router)
    worker = Discovery(SimpleNamespace(data_dir=tmp_path))
    app.state.discovery = worker
    worker.jobs["test"] = {
        "query": "name",
        "status": "completed",
        "source_pages": 2,
        "error": None,
        "urls": [
            f"https://video.dmm.co.jp/av/content/?id=demo{n:05d}" for n in reversed(range(205))
        ],
    }
    terms = []
    monkeypatch.setattr(worker, "start", lambda term: terms.append(term) or "test")
    with TestClient(app) as client:
        assert client.post("/api/product-searches", json={"query": "   "}).status_code == 422
        assert client.post("/api/product-searches", json={"query": " actress "}).json() == {
            "id": "test"
        }
        assert terms == ["actress"]
        response = client.get("/api/product-searches/test?page=3").json()
        assert len(response["urls"]) == 5
        assert response["urls"] == [
            f"https://video.dmm.co.jp/av/content/?id=demo{n:05d}" for n in range(200, 205)
        ]
        assert response["pages"] == 3 and response["total"] == 205
        assert client.get("/api/product-searches/test?page=0").status_code == 422
        assert client.get("/api/product-searches/missing").status_code == 404
        downloaded = client.get("/api/product-searches/test/download")
        assert len(downloaded.text.splitlines()) == 205
        assert downloaded.text.splitlines() == sorted(worker.jobs["test"]["urls"])
        assert "attachment" in downloaded.headers["content-disposition"]

        def busy(term):
            raise ValueError("Search already running")

        monkeypatch.setattr(worker, "start", busy)
        assert client.post("/api/product-searches", json={"query": "actress"}).status_code == 409
