import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session

from jav_data.app import create_app
from jav_data.config import Settings
from jav_data.downloads import DownloadWorker, asset_path, request_headers
from jav_data.media import discover_images, trusted_media_url
from jav_data.models import MediaAsset


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JAV_DATA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("JAV_DATA_LIBRARY_DIR", str(tmp_path / "library"))
    command.upgrade(Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head")
    with TestClient(create_app(Settings.load())) as client:
        client.post("/api/downloads/pause")
        yield client


def test_only_original_cover_is_discovered():
    html = """<img src="https://pics.dmm.co.jp/digital/video/demo001/demo001pl.jpg">
        <img src="https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/demo001/demo001pl.jpg?w=800&amp;q=50&amp;f=webp">
        <img src="https://pics.dmm.co.jp/digital/video/demo001/demo001ps.jpg">
        <img src="https://pics.dmm.co.jp/digital/video/demo001/demo001jp-1.jpg">
        <img src="https://pics.dmm.co.jp/digital/video/other001/other001pl.jpg">
        <img src="https://evil.example/demo001pl.jpg">"""
    images = discover_images(html, "demo001")
    assert images == [
        {
            "kind": "cover",
            "filename": "demo001-fanart.jpg",
            "url": "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/demo001/demo001pl.jpg",
        }
    ]


def test_media_url_and_path_boundaries(tmp_path):
    with pytest.raises(ValueError):
        trusted_media_url("https://dmm.co.jp.evil.example/image.jpg")
    with pytest.raises(ValueError):
        asset_path(Settings(tmp_path / "data", tmp_path / "library"), "demo001", "../secret")


def test_cookies_are_scoped_to_cdn_host_and_path(tmp_path):
    settings = Settings(tmp_path / "data", tmp_path / "library")
    settings.prepare()
    (settings.data_dir / "browser-session.json").write_text(
        json.dumps(
            {
                "cookies": [
                    {"name": "shared", "value": "fictional", "domain": ".dmm.co.jp", "path": "/"},
                    {
                        "name": "login",
                        "value": "private",
                        "domain": "accounts.dmm.co.jp",
                        "path": "/",
                    },
                    {
                        "name": "account_path",
                        "value": "private",
                        "domain": ".dmm.co.jp",
                        "path": "/account",
                    },
                    {
                        "name": "expired",
                        "value": "private",
                        "domain": ".dmm.co.jp",
                        "path": "/",
                        "expires": 1,
                    },
                ]
            }
        )
    )
    headers = request_headers(settings, "https://pics.dmm.co.jp/digital/test.jpg", None)
    assert headers["Cookie"] == "shared=fictional"
    assert "Cookie" not in request_headers(settings, "https://pics.dmm.com/image.jpg", None)


def test_http_cover_verified_before_replacing_existing_file(client, monkeypatch):
    movie = client.post(
        "/api/movies", json={"distribution_product_id": "demo001", "title": "作品"}
    ).json()
    with Session(client.app.state.engine) as session:
        asset = MediaAsset(
            movie_id=movie["id"],
            kind="cover",
            filename="demo001-fanart.jpg",
            url="https://pics.dmm.co.jp/digital/video/demo001/demo001pl.jpg",
            status="queued",
        )
        session.add(asset)
        session.commit()
        asset_id = asset.id
    destination = client.app.state.settings.library_dir / "demo001" / "demo001-fanart.jpg"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"previous file")
    output = io.BytesIO()
    Image.new("RGB", (600, 400)).save(output, format="JPEG")
    data = output.getvalue()

    def response():
        stream = io.BytesIO(data)
        stream.headers = {"Content-Length": str(len(data))}
        return stream

    monkeypatch.setattr(
        "jav_data.downloads.build_opener",
        lambda *args: SimpleNamespace(open=lambda *args, **kwargs: response()),
    )
    worker = DownloadWorker(client.app.state.settings, client.app.state.engine)
    worker.process_next()
    with Image.open(destination) as image:
        assert image.size == (600, 400)
    assert client.get(f"/media/{asset_id}").status_code == 200
    stored = client.get("/api/media-assets").json()[0]
    assert stored["status"] == "completed" and stored["width"] == 600
    import xml.etree.ElementTree as ET

    assert ET.parse(destination.parent / "movie.nfo").findtext("thumb") == "demo001-fanart.jpg"
    assert not destination.with_name(destination.name + ".part").exists()
    worker.update(asset_id, status="queued")
    data = b"not an image"
    worker.process_next()
    with Image.open(destination) as image:
        assert image.size == (600, 400)
    assert client.get("/api/media-assets").json()[0]["status"] == "failed"


def test_library_search_literal_and_metadata_fields(client):
    client.post(
        "/api/movies",
        json={
            "distribution_product_id": "demo001",
            "title": "作品",
            "actresses": ["架空の出演者"],
            "maker": "架空のメーカー",
        },
    )
    for term in ("demo001", "架空の出演者", "架空のメーカー"):
        assert client.get("/api/library", params={"q": term}).json()["total"] == 1
    assert client.get("/api/library", params={"q": "%"}).json()["total"] == 0


def test_library_title_sort_spans_pages_and_preserves_search(client):
    for number in reversed(range(25)):
        response = client.post(
            "/api/movies",
            json={
                "distribution_product_id": f"sort{number:03d}",
                "title": f"Title {number:02d}",
                "streaming_release_date": f"2024/01/{25 - number:02d}",
                "product_release_date": f"2024/01/{number + 1:02d}",
                "actresses": ["共通の出演者", f"Cast {24 - number:02d}"],
                "maker": f"Maker {24 - number:02d}",
            },
        )
        assert response.status_code == 201

    def titles(**params):
        result = client.get("/api/library", params=params)
        assert result.status_code == 200
        return [movie["title"] for movie in result.json()["items"]]

    ascending = titles(sort="title_asc") + titles(sort="title_asc", page=2)
    descending = titles(sort="title_desc") + titles(sort="title_desc", page=2)
    assert ascending == [f"Title {number:02d}" for number in range(25)]
    assert descending == list(reversed(ascending))
    assert titles(sort="title_desc", q="Title 0") == list(reversed(ascending[:10]))
    for field in ("release_date", "product_id", "actresses", "maker"):
        ordered = titles(sort=f"{field}_asc") + titles(sort=f"{field}_asc", page=2)
        backwards = titles(sort=f"{field}_desc") + titles(sort=f"{field}_desc", page=2)
        assert ordered == (ascending if field == "product_id" else descending)
        assert backwards == list(reversed(ordered))
    assert client.get("/api/library", params={"sort": "invalid"}).status_code == 422


def test_library_cover_preview_and_original_routes(client):
    from sqlalchemy import event

    movie = client.post(
        "/api/movies",
        json={
            "distribution_product_id": "preview001",
            "title": "Preview",
            "actresses": ["Example actress"],
        },
    ).json()
    folder = client.app.state.settings.library_dir / "preview001"
    folder.mkdir(parents=True)
    path = folder / "preview001-fanart.jpg"
    Image.new("RGB", (2000, 1500), "red").save(path)
    original = path.read_bytes()
    with Session(client.app.state.engine) as session:
        asset = MediaAsset(
            movie_id=movie["id"], kind="cover", filename=path.name, status="completed"
        )
        session.add(asset)
        session.commit()
        asset_id = asset.id
    page = client.get("/api/library").json()
    assert page["items"][0]["cover"]["id"] == asset_id
    assert page["items"][0]["cover"]["version"]
    statements = []

    def recorded(conn, cursor, statement, parameters, context, many):
        if statement.startswith("SELECT"):
            statements.append(statement)

    event.listen(client.app.state.engine, "before_cursor_execute", recorded)
    try:
        response = client.get(f"/media/{asset_id}?preview=true")
    finally:
        event.remove(client.app.state.engine, "before_cursor_execute", recorded)
    assert response.status_code == 200
    assert len(statements) == 1
    with Image.open(io.BytesIO(response.content)) as image:
        assert image.width <= 768 and image.height <= 512
    assert client.get(f"/media/{asset_id}").content == original
    assert path.read_bytes() == original
