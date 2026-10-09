from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from jav_data.app import create_app
from jav_data.config import Settings
from jav_data.library import TAG_LABELS


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JAV_DATA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("JAV_DATA_LIBRARY_DIR", str(tmp_path / "library"))
    command.upgrade(Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head")
    with TestClient(create_app(Settings.load())) as client:
        client.post("/api/downloads/pause")
        yield client


@pytest.mark.parametrize("field", TAG_LABELS)
def test_metadata_filter_matches_only_complete_values_in_the_selected_field(client, field):
    value = '日本語 %_ & "<タグ>" · 名前'
    listed = field in {"actresses", "directors", "genres", "related_tags"}
    for identifier, tag, title in (
        ("exact001", value, "Matching movie"),
        ("partial001", value + "追加", "Partial match"),
        ("other001", "その他", value),
    ):
        payload = {"distribution_product_id": identifier, "title": title}
        payload[field] = ["別の名前", tag] if listed else tag
        # The same value in a different metadata field must not count.
        payload["maker" if field != "maker" else "label"] = value
        assert client.post("/api/movies", json=payload).status_code == 201
    result = client.get("/api/library", params={"filter_field": field, "filter_value": value})
    assert result.status_code == 200
    assert result.json()["total"] == 1
    assert result.json()["items"][0]["distribution_product_id"] == "exact001"
    assert (
        client.get(
            "/api/library",
            params={
                "filter_field": field,
                "filter_value": "Missing tag",
            },
        ).json()["total"]
        == 0
    )
    assert client.get("/api/library").json()["total"] == 3


def test_tag_filter_counts_pages_sorts_and_combines_with_text_search(client):
    for number in reversed(range(26)):
        assert (
            client.post(
                "/api/movies",
                json={
                    "distribution_product_id": f"tag{number:03d}",
                    "title": f"Title {number:02d}",
                    "genres": ["共通", "ほか"] if number < 25 else ["共通追加"],
                },
            ).status_code
            == 201
        )
    params = {"filter_field": "genres", "filter_value": "共通", "sort": "product_id_desc"}
    first = client.get("/api/library", params=params).json()
    second = client.get("/api/library", params=params | {"page": 2}).json()
    assert first["total"] == second["total"] == 25 and first["pages"] == 2
    assert [movie["distribution_product_id"] for movie in first["items"] + second["items"]] == [
        f"tag{number:03d}" for number in reversed(range(25))
    ]
    searched = client.get("/api/library", params=params | {"q": "Title 0"}).json()
    assert searched["total"] == 10 and searched["items"][0]["title"] == "Title 09"


def test_invalid_or_incomplete_tag_filters_are_rejected(client):
    for params in (
        {"filter_field": "genres"},
        {"filter_value": "タグ"},
        {"filter_field": "genres", "filter_value": " "},
    ):
        assert client.get("/api/library", params=params).status_code == 400
    for field in ("source_url", "title", "unknown"):
        assert (
            client.get(
                "/api/library",
                params={
                    "filter_field": field,
                    "filter_value": "Value",
                },
            ).status_code
            == 422
        )
