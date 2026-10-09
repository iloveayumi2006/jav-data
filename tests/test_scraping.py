from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from jav_data.app import create_app
from jav_data.config import Settings
from jav_data.jobs import ScrapeWorker
from jav_data.models import ScrapeJob
from jav_data.scraper import SessionRequired, parse_product, product_url

URL = "https://video.dmm.co.jp/av/content/?id=ipzz00671"


def html():
    names = "".join(f'<a href="/actress/{i}">架空の出演者{i}</a>' for i in range(50))
    return f"""<h1>架空の作品</h1><table>
    <tr><th>配信開始日：</th><td>2026年10月2日</td></tr>
    <tr><th>収録時間：</th><td>120分</td></tr>
    <tr><th>出演者：</th><td>{names}</td></tr>
    <tr><th>メーカー：</th><td>架空のメーカー</td></tr>
    <tr><th>ジャンル：</th><td><a>サンプル</a><a>日本語</a></td></tr>
    <tr><th>メーカー品番：</th><td>DEMO-001</td></tr></table>
    <div id="introduction">架空の紹介文<br>二行目</div>"""


def test_product_parser_preserves_japanese_and_cast():
    movie = parse_product(html(), URL)
    assert movie.title == "架空の作品"
    assert movie.distribution_product_id == "ipzz00671"
    assert movie.manufacturer_product_id == "DEMO-001"
    assert movie.runtime == "120分"
    assert len(movie.actresses) == 50
    assert movie.actresses[-1] == "架空の出演者49"
    assert movie.video_intro == "架空の紹介文\n二行目"
    assert str(movie.source_url) == URL


def test_definition_list_and_gates():
    movie = parse_product("<h1>作品</h1><dl><dt>収録時間</dt><dd>90分</dd></dl>", URL)
    assert movie.runtime == "90分"
    with pytest.raises(SessionRequired):
        parse_product("<h1>年齢確認</h1><p>18歳以上ですか</p>", URL)
    with pytest.raises(SessionRequired):
        parse_product('<input type="password">', URL)
    with pytest.raises(ValueError, match="No product metadata"):
        parse_product("<h1>Access denied</h1>", URL)


@pytest.mark.parametrize(
    "url",
    [
        "http://video.dmm.co.jp/av/content/?id=abc",
        "https://video.dmm.co.jp.evil.test/av/content/?id=abc",
        "https://www.dmm.co.jp/actress/123",
        "https://video.dmm.co.jp/av/content/?id=../escape",
        "https://video.dmm.co.jp/av/content/",
    ],
)
def test_reject_non_product_urls(url):
    with pytest.raises(ValueError):
        product_url(url)


def test_current_intro_container_excludes_promotional_links():
    content = html().replace('<div id="introduction">架空の紹介文<br>二行目</div>', "")
    content += """<div class="flex flex-col gap-2 text-xs leading-[16.8px]">
        <div>架空の紹介文<br>二行目</div>
        <div><h2>特集</h2><p>含めない広告リンク</p></div></div>"""
    assert parse_product(content, URL).video_intro == "架空の紹介文\n二行目"


def test_legacy_url():
    url = "https://www.dmm.co.jp/digital/videoa/-/detail/=/cid=demo001/"
    assert parse_product(html(), product_url(url)).distribution_product_id == "demo001"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("JAV_DATA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("JAV_DATA_LIBRARY_DIR", str(tmp_path / "library"))
    command.upgrade(Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head")
    with TestClient(create_app(Settings.load())) as client:
        yield client


def test_queue_validation_dedup_retry_and_persistence(app):
    response = app.post("/api/scrape-jobs", json={"urls": [URL, URL]})
    assert response.status_code == 201
    job = response.json()[0]
    assert len(response.json()) == 1
    assert job["status"] == "queued"
    assert app.post("/api/scrape-jobs", json={"urls": [URL]}).json()[0]["id"] == job["id"]
    assert app.post(f"/api/scrape-jobs/{job['id']}/retry").status_code == 409
    assert app.post("/api/scrape-jobs", json={"urls": ["https://example.com"]}).status_code == 422
    assert app.post("/api/session/ready").status_code == 400
    assert app.get("/api/session").json()["status"] == "closed"


class FakePage:
    url = URL

    def goto(self, *args, **kwargs):
        return type("Response", (), {"status": 200})()

    def wait_for_function(self, *args, **kwargs):
        pass

    def content(self):
        return html()

    def close(self):
        pass


def test_worker_saves_metadata_and_upserts(app):
    engine = app.app.state.engine
    settings = app.app.state.settings
    worker = ScrapeWorker(settings, engine)
    worker.browser = type("Browser", (), {"new_page": lambda self: FakePage()})()
    job_id = app.post("/api/scrape-jobs", json={"urls": [URL]}).json()[0]["id"]
    worker.process_next()
    first = app.get("/api/movies").json()[0]
    assert len(first["actresses"]) == 50
    assert (settings.library_dir / "ipzz00671" / "metadata.json").is_file()
    assert (settings.library_dir / "ipzz00671" / "movie.nfo").is_file()
    assert app.get("/api/scrape-jobs").json()[0]["status"] == "completed"
    assert app.post(f"/api/scrape-jobs/{job_id}/retry").status_code == 200
    worker.process_next()
    assert len(app.get("/api/movies").json()) == 1
    with Session(engine) as session:
        assert session.get(ScrapeJob, job_id).attempts == 2
