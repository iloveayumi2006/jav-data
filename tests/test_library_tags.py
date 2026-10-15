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


def test_excel_export_all_pages_order_filters_and_literal_japanese(client):
    import io
    from xml.etree import ElementTree as ET
    from zipfile import ZipFile

    from jav_data.metadata_export import COLUMNS, NS

    for number in reversed(range(27)):
        payload = {
            "distribution_product_id": f"export{number:03d}",
            "manufacturer_product_id": "000123",
            "title": "=日本語 & <作品> " + f"{number:02d}",
            "streaming_release_date": "2026/10/01",
            "product_release_date": "2026年10月2日",
            "actresses": ["二番目ではない", "出演者 <二>"],
            "runtime": "120分",
            "series": "シリーズ",
            "maker": "メーカー",
            "label": "レーベル",
            "genres": ["共通" if number < 26 else "除外"],
            "source_url": "https://video.dmm.co.jp/av/content/?id=export001",
        }
        assert client.post("/api/movies", json=payload).status_code == 201

    def export(params):
        response = client.get("/api/library/export", params=params)
        assert response.status_code == 200
        assert "spreadsheetml.sheet" in response.headers["content-type"]
        with ZipFile(io.BytesIO(response.content)) as archive:
            for name in archive.namelist():
                ET.fromstring(archive.read(name))
            root = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        rows = root.findall(f"{{{NS}}}sheetData/{{{NS}}}row")
        assert not root.findall(f".//{{{NS}}}f")
        assert all(c.attrib["t"] == "inlineStr" for row in rows for c in row)
        return [[c.find(f"{{{NS}}}is/{{{NS}}}t").text or "" for c in row] for row in rows]

    all_rows = export({"sort": "product_id_desc"})
    assert all_rows[0] == [label for label, _, _ in COLUMNS]
    assert len(all_rows) == 28
    assert all_rows[1][3] == "export026" and all_rows[-1][3] == "export000"
    assert all_rows[1][:3] == ["2026/10/01", "2026年10月2日", "二番目ではない; 出演者 <二>"]
    assert all_rows[1][4:7] == ["000123", "=日本語 & <作品> 26", "120分"]
    params = {"filter_field": "genres", "filter_value": "共通", "sort": "title_asc"}
    filtered = export(params)
    assert len(filtered) == 27
    expected = []
    for page in (1, 2):
        expected.extend(
            m["distribution_product_id"]
            for m in client.get("/api/library", params=params | {"page": page}).json()["items"]
        )
    assert [r[3] for r in filtered[1:]] == expected
    assert len(export(params | {"q": "作品> 0"})) == 11
    assert len(export({"q": "no matches"})) == 1
    assert client.get("/api/library/export", params={"filter_field": "genres"}).status_code == 400
    assert client.get("/api/library/export", params={"sort": "invalid"}).status_code == 422
