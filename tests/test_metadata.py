from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from jav_data.app import create_app
from jav_data.config import Settings

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JAV_DATA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("JAV_DATA_LIBRARY_DIR", str(tmp_path / "library"))
    config = Config(str(ROOT / "alembic.ini"))
    command.upgrade(config, "0001_foundation")
    command.upgrade(config, "head")
    with TestClient(create_app(Settings.load())) as client:
        yield client


def sample(product_id="demo00001"):
    return {
        "distribution_product_id": product_id,
        "manufacturer_product_id": "DEMO-001",
        "title": "架空の作品タイトル",
        "streaming_release_date": "2026年10月2日",
        "product_release_date": "2026/10/01",
        "runtime": "120分",
        "actresses": [f"架空の出演者{number:02d}" for number in range(50)],
        "directors": ["架空の監督"],
        "series": "架空のシリーズ",
        "maker": "架空のメーカー",
        "label": "架空のレーベル",
        "genres": ["サンプル", "日本語"],
        "related_tags": ["架空のタグ"],
        "video_intro": "保存確認用の架空の紹介文です。\n二行目も保持します。",
        "source_url": "https://www.dmm.co.jp/example/demo00001/",
        "scraped_at": "2026-10-02T21:00:00+09:00",
    }


def test_japanese_round_trip_and_ordered_cast_of_fifty(client):
    payload = sample()
    response = client.post("/api/movies", json=payload)
    assert response.status_code == 201, response.text
    stored = response.json()
    for key, value in payload.items():
        if key != "scraped_at":
            assert stored[key] == value
    assert stored["scraped_at"] == "2026-10-02T12:00:00Z"
    assert len(stored["cast"]) == 50
    assert [actress["name"] for actress in stored["cast"]] == payload["actresses"]
    assert client.get(f"/api/movies/{stored['id']}").json() == stored
    assert client.get("/api/movies").json() == [stored]


def test_edit_cast_reuses_shared_actresses_and_preserves_order(client):
    first = client.post("/api/movies", json=sample()).json()
    second = client.post("/api/movies", json=sample("demo00002")).json()
    assert first["cast"] == second["cast"]
    payload = sample()
    payload["title"] = "更新した作品名"
    payload["actresses"] = [payload["actresses"][49], "新しい架空の出演者"]
    for _ in range(2):
        response = client.put(f"/api/movies/{first['id']}", json=payload)
        assert response.status_code == 200, response.text
        edited = response.json()
        assert edited["title"] == payload["title"]
        assert edited["actresses"] == payload["actresses"]
        assert edited["cast"][0]["id"] == first["cast"][49]["id"]
    assert len(client.get("/api/actresses", params={"limit": 200}).json()) == 51
    assert client.get(f"/api/movies/{second['id']}").json()["cast"] == second["cast"]


def test_conflict_does_not_change_existing_metadata(client):
    first = client.post("/api/movies", json=sample()).json()
    second = client.post("/api/movies", json=sample("demo00002")).json()
    assert client.post("/api/movies", json=sample("DEMO00001")).status_code == 409
    assert client.put(f"/api/movies/{second['id']}", json=sample()).status_code == 409
    assert client.get(f"/api/movies/{second['id']}").json() == second
    assert client.get(f"/api/movies/{first['id']}").json() == first


@pytest.mark.parametrize("identifier", ["../escape", "CON", "NUL.txt", "abc.", "a/b", "a\\b"])
def test_unsafe_folder_identifiers_rejected(client, identifier):
    assert client.post("/api/movies", json=sample(identifier)).status_code == 422
    assert client.get("/api/movies").json() == []


def test_empty_optional_fields_duplicates_and_missing_movie(client):
    payload = {"distribution_product_id": "minimal001", "title": "未設定の作品"}
    payload["actresses"] = ["架空の名前", "架空の名前"]
    response = client.post("/api/movies", json=payload)
    assert response.status_code == 201
    stored = response.json()
    assert stored["actresses"] == ["架空の名前"]
    assert stored["runtime"] is None
    assert stored["genres"] == []
    assert client.get("/api/movies/999999").status_code == 404
    assert client.put("/api/movies/999999", json=payload).status_code == 404
    payload["actresses"] = [" "]
    assert client.post("/api/movies", json=payload).status_code == 422


def test_records_survive_app_restart_and_repeat_migration(client):
    stored = client.post("/api/movies", json=sample()).json()
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    with TestClient(create_app(Settings.load())) as restarted:
        assert restarted.get(f"/api/movies/{stored['id']}").json() == stored
