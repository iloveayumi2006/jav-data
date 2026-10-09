import pytest
from test_scraping import FakePage, app  # noqa: F401, F811

from jav_data.media import discover_images, trusted_media_url
from jav_data.mgs import distribution_id
from jav_data.scraper import SessionRequired, parse_product, product_url, url_product_id

URL = "https://www.mgstage.com/product/product_detail/ABF-232/"


def product_html(identifier="ABF-232"):
    return f"""<h1><img></h1><h1 class="tag">架空の作品</h1>
    <div class="detail_data"><table>
    <tr><th>出演：</th><td><a>架空の出演者</a><a>別の出演者</a></td></tr>
    <tr><th>品番：</th><td>{identifier}</td></tr>
    <tr><th>メーカー：</th><td>架空のメーカー</td></tr>
    <tr><th>配信開始日：</th><td>2025/05/22</td></tr>
    <tr><th>商品発売日：</th><td>2025/06/06</td></tr>
    <tr><th>収録時間：</th><td>165min</td></tr></table></div>
    <p class="txt introduction">紹介文<br>二行目</p>
    <a id="EnlargeImage" href="https://image.mgstage.com/images/prestige/abf/232/pb_e_abf-232.jpg">Cover</a>"""


@pytest.mark.parametrize(
    "original, expected",
    [
        ("ABF-232", "abf00232"),
        ("ABW-054", "abw00054"),
        ("ABP-542", "abp00542"),
        ("abc-123456", "abc123456"),
    ],
)
def test_identifier_conversion(original, expected):
    assert distribution_id(original) == expected


@pytest.mark.parametrize("value", ["123ABC-001", "ABC-12-X", "ABC--12", "ABC", "../ABC-1"])
def test_unsupported_ids_are_rejected(value):
    with pytest.raises(ValueError):
        distribution_id(value)


def test_url_validation_and_metadata_mapping():
    assert product_url(URL + "?tracking=1") == URL
    assert url_product_id(URL) == "abf00232"
    movie = parse_product(product_html(), URL)
    assert movie.distribution_product_id == "abf00232"
    assert movie.manufacturer_product_id == "ABF-232"
    assert movie.title == "架空の作品"
    assert movie.actresses == ["架空の出演者", "別の出演者"]
    assert movie.streaming_release_date == "2025/05/22"
    assert movie.product_release_date == "2025/06/06"
    assert movie.runtime == "165min"
    assert movie.video_intro == "紹介文\n二行目"
    assert movie.directors == []
    with pytest.raises(ValueError, match="does not match"):
        parse_product(product_html("ABF-233"), URL)
    with pytest.raises(SessionRequired):
        parse_product("<h1>年齢認証</h1>", URL)
    for url in (
        URL.replace("https", "http"),
        URL.replace("www.mgstage.com", "www.mgstage.com.evil.test"),
        URL.replace("ABF-232", "123ABC-232"),
    ):
        with pytest.raises(ValueError):
            product_url(url)


def test_original_cover_selection_and_cdn_boundaries():
    cover = discover_images(product_html(), "abf00232")[0]
    assert cover["filename"] == "abf00232-fanart.jpg"
    assert "pb_e_abf-232.jpg" in cover["url"]
    with pytest.raises(ValueError, match="does not match"):
        discover_images(product_html(), "abw00054")
    with pytest.raises(ValueError):
        trusted_media_url("https://image.mgstage.com.evil.test/cover.jpg")


def test_full_intro_and_empty_intro():
    html = (
        product_html() + '<meta property="og:description" content="完全な紹介文とその続き">'
        '<p id="introduction_all"><a>すべてを見る</a></p>'
    )
    assert parse_product(html, URL).video_intro == "完全な紹介文とその続き"
    html = product_html().replace("紹介文<br>二行目", "")
    assert parse_product(html, URL).video_intro is None


def test_search_excludes_recommendations_filters_and_other_queries():
    from jav_data.mgs import parse_search_results

    html = """<ul class="product_list"><li>
    <a href="/product/product_detail/ABF-232/">one</a>
    <a href="/product/product_detail/ABF-232/">duplicate</a></li></ul>
    <a href="/product/product_detail/ABW-054/">Recommendation</a>
    <a class="page" href="cSearch.php?search_word=test&amp;page=2">Next</a>
    <a class="page" href="cSearch.php?search_word=test&amp;page=3&amp;actor[]=other">Filter</a>
    <a class="page" href="cSearch.php?search_word=other&amp;page=4">Other</a>"""
    assert parse_search_results(html, "test", 1) == ([URL], 2)
    assert parse_search_results(html, "test", 2) == ([URL], None)
    with pytest.raises(ValueError, match="authentication"):
        parse_search_results("<h1>年齢認証</h1>", "test", 1)


def test_mgs_cookies_do_not_leak_to_dmm(tmp_path):
    import json

    from jav_data.config import Settings
    from jav_data.downloads import request_headers

    settings = Settings(tmp_path / "data", tmp_path / "library")
    settings.prepare()
    (settings.data_dir / "browser-session.json").write_text(
        json.dumps(
            {
                "cookies": [
                    {"name": "mgs", "value": "fictional", "domain": ".mgstage.com", "path": "/"},
                    {"name": "dmm", "value": "fictional", "domain": ".dmm.co.jp", "path": "/"},
                ]
            }
        ),
        encoding="utf-8",
    )
    assert (
        request_headers(settings, "https://image.mgstage.com/image.jpg", URL)["Cookie"]
        == "mgs=fictional"
    )
    assert (
        request_headers(settings, "https://pics.dmm.co.jp/image.jpg", None)["Cookie"]
        == "dmm=fictional"
    )


def test_scrape_upsert_and_source_collision(app):  # noqa: F811
    from jav_data.jobs import ScrapeWorker

    class Page(FakePage):
        url = URL

        def content(self):
            return product_html()

    app.app.state.downloader.paused = True
    worker = ScrapeWorker(app.app.state.settings, app.app.state.engine)
    worker.browser = type("Browser", (), {"new_page": lambda self: Page()})()
    job = app.post("/api/scrape-jobs", json={"urls": [URL]}).json()[0]
    worker.process_next()
    movie = app.get("/api/movies").json()[0]
    assert movie["distribution_product_id"] == "abf00232"
    folder = app.app.state.settings.library_dir / "abf00232"
    assert (folder / "movie.nfo").is_file()
    original = (folder / "metadata.json").read_bytes()
    app.post(f"/api/scrape-jobs/{job['id']}/retry")
    worker.process_next()
    assert len(app.get("/api/movies").json()) == 1
    Page.url = "https://video.dmm.co.jp/av/content/?id=abf00232"
    Page.content = lambda self: (
        "<h1>Do not overwrite</h1><table><tr><th>収録時間</th><td>90分</td></tr></table>"
    )
    app.post("/api/scrape-jobs", json={"urls": [Page.url]})
    saved = (folder / "metadata.json").read_bytes()
    worker.process_next()
    assert app.get("/api/scrape-jobs").json()[0]["status"] == "failed"
    assert (folder / "metadata.json").read_bytes() == saved
    assert original and saved


def test_original_mgs_id_collision_does_not_merge(app):  # noqa: F811
    from jav_data.jobs import ScrapeWorker

    app.app.state.downloader.paused = True
    app.post(
        "/api/movies",
        json={
            "distribution_product_id": "abf00232",
            "title": "Existing movie",
            "manufacturer_product_id": "ABF-00232",
            "source_url": "https://www.mgstage.com/product/product_detail/ABF-00232/",
        },
    )

    class Page(FakePage):
        url = URL

        def content(self):
            return product_html()

    worker = ScrapeWorker(app.app.state.settings, app.app.state.engine)
    worker.browser = type("Browser", (), {"new_page": lambda self: Page()})()
    app.post("/api/scrape-jobs", json={"urls": [URL]})
    worker.process_next()
    assert app.get("/api/scrape-jobs").json()[0]["status"] == "failed"
    assert app.get("/api/movies").json()[0]["title"] == "Existing movie"
