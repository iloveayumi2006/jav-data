import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from jav_data.app import create_app
from jav_data.config import Settings
from jav_data.models import MediaAsset, Movie
from jav_data.nfo import normalized_date, runtime_minutes


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JAV_DATA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("JAV_DATA_LIBRARY_DIR", str(tmp_path / "library"))
    command.upgrade(Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head")
    with TestClient(create_app(Settings.load())) as client:
        client.post("/api/downloads/pause")
        yield client


def test_nfo_original_metadata_cast_art_and_folder_routing(client, tmp_path):
    folder = tmp_path / "second"
    folders = client.post("/api/product-folders", json={"path": str(folder)}).json()
    payload = {
        "distribution_product_id": "demo001",
        "title": "作品 & <日本語>",
        "manufacturer_product_id": "DEMO-001",
        "product_release_date": "２０２６年１０月１日",
        "streaming_release_date": "2026/09/30",
        "runtime": "１２０分",
        "actresses": [f"出演者{n}" for n in range(50)],
        "directors": ["監督"],
        "maker": "メーカー",
        "label": "レーベル",
        "series": "シリーズ",
        "genres": ["分類"],
        "related_tags": ["タグ"],
        "video_intro": "紹介 & <本文>\n次の行",
    }
    response = client.post("/api/movies", json=payload)
    assert response.status_code == 201, response.text
    movie_id = response.json()["id"]
    product = folder / "demo001"
    product.mkdir(parents=True)
    with Session(client.app.state.engine) as session:
        session.get(Movie, movie_id).product_folder_id = folders[-1]["id"]
        for kind, filename in [
            ("cover", "demo001pl.jpg"),
            ("screenshot", "screen.jpg"),
            ("trailer", "trailer.mp4"),
            ("cover", "missing.jpg"),
        ]:
            session.add(
                MediaAsset(movie_id=movie_id, kind=kind, filename=filename, status="completed")
            )
            if filename != "missing.jpg":
                (product / filename).write_bytes(b"fixture")
        session.commit()
    result = client.post("/api/nfo/export", json={"movie_ids": [movie_id, movie_id, 999]}).json()[
        "results"
    ]
    assert [r["status"] for r in result] == ["exported", "failed"]
    path = product / "movie.nfo"
    root = ET.fromstring(path.read_bytes())
    assert root.findtext("title") == payload["title"]
    assert root.findtext("plot") == payload["video_intro"]
    assert root.findtext("premiered") == "2026-10-01"
    assert root.findtext("runtime") == "120"
    assert [a.findtext("name") for a in root.findall("actor")] == payload["actresses"]
    assert root.findtext("javdata/product_release_date") == payload["product_release_date"]
    assert root.findtext("javdata/label") == payload["label"]
    assert root.find("javdata/local_trailer") is None
    assert root.findtext("thumb") == "demo001pl.jpg"
    assert root.find("fanart") is None
    assert root.find("collectionnumber") is None
    assert not (tmp_path / "library" / "demo001" / "movie.nfo").exists()
    path.write_bytes(b"existing custom NFO")
    assert (
        client.post("/api/nfo/export", json={"movie_ids": [movie_id]}).json()["results"][0][
            "status"
        ]
        == "skipped"
    )
    assert path.read_bytes() == b"existing custom NFO"
    assert (
        client.post(
            "/api/nfo/export", json={"movie_ids": [movie_id], "profile": "emby", "overwrite": True}
        ).json()["results"][0]["status"]
        == "exported"
    )
    assert ET.fromstring(path.read_bytes()).find("art") is None
    downloaded = client.get(f"/api/movies/{movie_id}/nfo?profile=emby")
    assert downloaded.status_code == 200
    assert "attachment" in downloaded.headers["content-disposition"]
    assert ET.fromstring(downloaded.content).findtext("title") == payload["title"]
    assert client.get("/api/movies/999/nfo").status_code == 404
    assert client.post("/api/nfo/export", json={"movie_ids": []}).status_code == 422
    assert client.get(f"/api/movies/{movie_id}/nfo?profile=bad").status_code == 422


@pytest.mark.parametrize(
    "value,expected",
    [("2024年2月29日", "2024-02-29"), ("2025/2/29", None), (None, None), ("未定", None)],
)
def test_normalize_dates(value, expected):
    assert normalized_date(value) == expected


def test_runtime_and_invalid_xml(client):
    assert runtime_minutes("９０分") == 90
    assert runtime_minutes("不明") is None
    movie_id = client.post(
        "/api/movies", json={"distribution_product_id": "demo002", "title": "bad\u0001"}
    ).json()["id"]
    assert client.get(f"/api/movies/{movie_id}/nfo").status_code == 422
    assert (
        client.post("/api/nfo/export", json={"movie_ids": [movie_id]}).json()["results"][0][
            "status"
        ]
        == "failed"
    )


def test_existing_library_conversion_is_idempotent(client, tmp_path):
    from jav_data.emby_conversion import convert_library

    movie_id = client.post(
        "/api/movies", json={"distribution_product_id": "convert001", "title": "作品"}
    ).json()["id"]
    product = tmp_path / "library" / "convert001"
    product.mkdir(parents=True)
    old = product / "convert001pl.jpg"
    old.write_bytes(b"original cover bytes")
    with Session(client.app.state.engine) as session:
        session.add(
            MediaAsset(movie_id=movie_id, kind="cover", filename=old.name, status="completed")
        )
        session.commit()
    settings, engine = client.app.state.settings, client.app.state.engine
    first = convert_library(settings, engine)
    assert first[0]["renamed"] == 1 and "error" not in first[0]
    assert not old.exists()
    new = product / "convert001-fanart.jpg"
    assert new.read_bytes() == b"original cover bytes"
    assert ET.parse(product / "movie.nfo").findtext("thumb") == new.name
    assert convert_library(settings, engine)[0]["renamed"] == 0
    asset = client.get("/api/media-assets").json()[0]
    assert asset["filename"] == new.name
    assert client.get(f"/media/{asset['id']}").content == new.read_bytes()
