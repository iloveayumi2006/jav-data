from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from jav_data.app import create_app
from jav_data.config import Settings
from jav_data.jobs import ScrapeWorker
from jav_data.models import MediaAsset, ScrapeJob


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JAV_DATA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("JAV_DATA_LIBRARY_DIR", str(tmp_path / "library"))
    command.upgrade(Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head")
    with TestClient(create_app(Settings.load())) as client:
        client.post("/api/downloads/pause")
        yield client


class Page:
    frames = []

    def goto(self, url, **kwargs):
        self.url = url
        return type("Response", (), {"status": 200})()

    def wait_for_function(self, *args, **kwargs):
        pass

    def content(self):
        return "<h1>架空の作品</h1><dl><dt>収録時間</dt><dd>90分</dd></dl>"

    def close(self):
        pass


def test_three_folders_route_new_products_and_preserve_existing_locations(client, tmp_path):
    for folder in (tmp_path / "second", tmp_path / "third"):
        assert client.post("/api/product-folders", json={"path": str(folder)}).status_code == 201
    folders = client.get("/api/product-folders").json()
    assert [f["label"] for f in folders] == ["library", "second", "third"]
    worker = ScrapeWorker(client.app.state.settings, client.app.state.engine)
    worker.browser = type("Browser", (), {"new_page": lambda self: Page()})()
    url = "https://video.dmm.co.jp/av/content/?id=demo002"
    client.post("/api/scrape-jobs", json={"urls": [url], "product_folder_id": folders[1]["id"]})
    worker.process_next()
    movie = client.get("/api/movies").json()[0]
    assert movie["product_folder_id"] == folders[1]["id"]
    assert (tmp_path / "second" / "demo002" / "metadata.json").is_file()
    assert not (tmp_path / "library" / "demo002").exists()
    # Selecting a different root for a rescrape does not silently move an existing movie.
    client.post("/api/scrape-jobs", json={"urls": [url], "product_folder_id": folders[2]["id"]})
    worker.process_next()
    assert client.get("/api/movies").json()[0]["product_folder_id"] == folders[1]["id"]
    assert not (tmp_path / "third" / "demo002").exists()
    assert (
        len(client.post("/api/product-folders", json={"path": str(tmp_path / "second")}).json())
        == 3
    )
    assert (
        client.post(
            "/api/product-folders", json={"path": str(tmp_path / "second" / "nested")}
        ).status_code
        == 400
    )


def test_clear_history_preserves_files_library_and_active_jobs(client):
    movie = client.post(
        "/api/movies", json={"distribution_product_id": "demo001", "title": "作品"}
    ).json()
    engine = client.app.state.engine
    with Session(engine) as session:
        for status in ("completed", "failed", "queued", "running", "awaiting_session"):
            session.add(
                ScrapeJob(url="https://video.dmm.co.jp/av/content/?id=" + status, status=status)
            )
        asset = MediaAsset(
            movie_id=movie["id"], kind="cover", filename="cover.jpg", status="completed"
        )
        session.add(asset)
        session.add(
            MediaAsset(
                movie_id=movie["id"], kind="cover", filename="pendingpl.jpg", status="queued"
            )
        )
        session.commit()
        asset_id = asset.id
    path = client.app.state.settings.library_dir / "demo001" / "cover.jpg"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"fixture")
    assert client.post("/api/scrape-history/clear").json()["cleared"] == 2
    assert {j["status"] for j in client.get("/api/scrape-jobs").json()} == {
        "queued",
        "running",
        "awaiting_session",
    }
    assert client.post("/api/download-history/clear").json()["cleared"] == 1
    assert len(client.get("/api/media-assets", params={"history": True}).json()) == 1
    assert len(client.get("/api/media-assets", params={"movie_id": movie["id"]}).json()) == 2
    assert client.get(f"/media/{asset_id}").content == b"fixture"
    assert client.get(f"/api/movies/{movie['id']}").status_code == 200
    assert path.is_file()
    assert client.post("/api/download-history/clear").json()["cleared"] == 0


def test_media_serving_uses_movie_folder(client, tmp_path):
    folder = client.post("/api/product-folders", json={"path": str(tmp_path / "extra")}).json()[-1]
    movie = client.post(
        "/api/movies", json={"distribution_product_id": "demo001", "title": "作品"}
    ).json()
    with Session(client.app.state.engine) as session:
        session.execute(
            text("UPDATE movies SET product_folder_id=:folder WHERE id=:id"),
            {"folder": folder["id"], "id": movie["id"]},
        )
        asset = MediaAsset(
            movie_id=movie["id"], kind="cover", filename="cover.jpg", status="completed"
        )
        session.add(asset)
        session.commit()
        asset_id = asset.id
    path = tmp_path / "extra" / "demo001" / "cover.jpg"
    path.parent.mkdir()
    path.write_bytes(b"second-root")
    assert client.get(f"/media/{asset_id}").content == b"second-root"


def test_upgrade_preserves_existing_cast_and_media(tmp_path, monkeypatch):
    monkeypatch.setenv("JAV_DATA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("JAV_DATA_LIBRARY_DIR", str(tmp_path / "library"))
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(config, "0004_media")
    import sqlite3

    with sqlite3.connect(Settings.load().database_path) as db:
        db.execute(
            "INSERT INTO movies (id,distribution_product_id,title,directors,genres,related_tags,"
            "created_at,updated_at) VALUES "
            "(1,'demo','作品','[]','[]','[]','2026-10-02','2026-10-02')"
        )
        db.execute("INSERT INTO actresses VALUES (1, '出演者')")
        db.execute("INSERT INTO movie_actresses VALUES (1,1,0)")
        db.execute(
            "INSERT INTO media_assets (id,movie_id,filename,kind,status,downloaded_bytes,"
            "attempts,updated_at) VALUES (1,1,'cover.jpg','cover','completed',100,1,'2026-10-02')"
        )
    command.upgrade(config, "head")
    with TestClient(create_app(Settings.load())) as client:
        movie = client.get("/api/movies/1").json()
        assert movie["actresses"] == ["出演者"]
        assert movie["product_folder_id"] is not None
        assert client.get("/api/media-assets").json()[0]["status"] == "completed"


def disk_movie(root, identifier="demo001", title="作品"):
    import json

    folder = root / identifier
    folder.mkdir(parents=True, exist_ok=True)
    metadata = folder / "metadata.json"
    metadata.write_text(
        json.dumps(
            {
                "id": 999,
                "product_folder_id": 999,
                "distribution_product_id": identifier,
                "title": title,
                "actresses": ["出演者"],
                "streaming_release_date": "2025/01/02",
                "created_at": "2025-01-01T00:00:00Z",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return metadata


def test_add_library_imports_metadata_and_existing_cover(client, tmp_path):
    from PIL import Image

    root = tmp_path / "imported"
    metadata = disk_movie(root)
    before = metadata.read_bytes()
    Image.new("RGB", (240, 160), "white").save(root / "demo001" / "demo001-fanart.jpg")
    response = client.post("/api/product-folders", json={"path": str(root)})
    assert response.status_code == 201
    library = response.json()[-1]
    assert library["label"] == "imported"
    assert library["scan"]["added"] == 1
    movie = client.get("/api/movies").json()[0]
    assert movie["id"] != 999 and movie["product_folder_id"] == library["id"]
    assert movie["actresses"] == ["出演者"]
    cover = client.get("/api/media-assets").json()[0]
    assert cover["status"] == "completed" and cover["width"] == 240
    assert client.get("/api/library").json()["items"][0]["cover"]
    assert client.get(f"/media/{cover['id']}").status_code == 200
    assert metadata.read_bytes() == before
    assert client.post("/api/product-folders/refresh").json()["added"] == 0
    assert len(client.get("/api/movies").json()) == 1


def test_refresh_imports_updates_and_removes_deleted_metadata(client):
    import json

    root = client.app.state.settings.library_dir
    metadata = disk_movie(root)
    assert client.post("/api/product-folders/refresh").json()["added"] == 1
    movie = client.get("/api/movies").json()[0]
    data = json.loads(metadata.read_text(encoding="utf-8"))
    data["title"], data["actresses"] = "Updated", ["新しい出演者"]
    metadata.write_text(json.dumps(data), encoding="utf-8")
    assert client.post("/api/product-folders/refresh").json()["updated"] == 1
    changed = client.get(f"/api/movies/{movie['id']}").json()
    assert changed["title"] == "Updated" and changed["actresses"] == ["新しい出演者"]
    with Session(client.app.state.engine) as session:
        session.add(
            ScrapeJob(
                url="https://video.dmm.co.jp/av/content/?id=demo001",
                movie_id=movie["id"],
                status="completed",
            )
        )
        session.add(
            MediaAsset(movie_id=movie["id"], kind="cover", filename="missing.jpg", status="failed")
        )
        session.commit()
    metadata.unlink()
    assert client.post("/api/product-folders/refresh").json()["removed"] == 1
    assert client.get(f"/api/movies/{movie['id']}").status_code == 404
    assert client.get("/api/media-assets").json() == []
    assert client.get("/api/scrape-jobs").json()[0]["movie_id"] is None
    assert metadata.parent.is_dir()  # Refresh does not delete user files or folders.


def test_refresh_keeps_records_for_invalid_metadata_and_unavailable_library(client, tmp_path):
    root = tmp_path / "extra"
    metadata = disk_movie(root)
    client.post("/api/product-folders", json={"path": str(root)})
    metadata.write_text("{invalid", encoding="utf-8")
    result = client.post("/api/product-folders/refresh").json()
    assert result["skipped"] == 1 and result["removed"] == 0
    assert len(client.get("/api/movies").json()) == 1
    root.rename(tmp_path / "offline")
    result = client.post("/api/product-folders/refresh").json()
    assert result["removed"] == 0 and result["skipped"] == 1
    assert "unavailable" in result["warnings"][0]
    assert len(client.get("/api/movies").json()) == 1


def test_library_conflict_and_mismatched_folder_are_not_imported(client, tmp_path):
    disk_movie(client.app.state.settings.library_dir)
    client.post("/api/product-folders/refresh")
    root = tmp_path / "extra"
    disk_movie(root, title="Do not overwrite")
    result = client.post("/api/product-folders", json={"path": str(root)}).json()[-1]
    assert result["scan"]["skipped"] == 1
    assert client.get("/api/movies").json()[0]["title"] == "作品"
    metadata = disk_movie(root, "demo002")
    metadata.parent.rename(root / "wrong-name")
    result = client.post("/api/product-folders/refresh").json()
    assert result["added"] == 0 and result["skipped"] == 2
    assert len(client.get("/api/movies").json()) == 1


def test_scanning_waits_for_concurrent_work_and_releases_after_error():
    import threading

    from jav_data.library_sync import LibraryActivity

    activity = LibraryActivity()
    entered = threading.Barrier(3)
    release = threading.Event()
    scanned = threading.Event()

    def work():
        with activity.work():
            entered.wait(timeout=3)
            assert release.wait(timeout=3)

    def scan():
        with activity.scan():
            scanned.set()

    workers = [threading.Thread(target=work) for _ in range(2)]
    for worker in workers:
        worker.start()
    entered.wait(timeout=3)  # Scraping and downloads can work simultaneously.
    scanner = threading.Thread(target=scan)
    scanner.start()
    with activity.condition:
        activity.condition.wait_for(lambda: activity.scanning, timeout=3)
    assert not scanned.is_set()
    release.set()
    for worker in workers:
        worker.join(timeout=3)
    scanner.join(timeout=3)
    assert scanned.is_set()
    with pytest.raises(ValueError), activity.scan():
        raise ValueError("failed scan")
    with activity.work():
        assert activity.active == 1


def test_refresh_tracks_moves_in_both_directions(client, tmp_path):
    primary = client.app.state.settings.library_dir
    extra = tmp_path / "extra"
    library = client.post("/api/product-folders", json={"path": str(extra)}).json()[-1]
    metadata = disk_movie(primary)
    client.post("/api/product-folders/refresh")
    (primary / "demo001").rename(extra / "demo001")
    result = client.post("/api/product-folders/refresh").json()
    assert result["added"] + result["updated"] == 1
    assert client.get("/api/movies").json()[0]["product_folder_id"] == library["id"]
    (extra / "demo001").rename(primary / "demo001")
    result = client.post("/api/product-folders/refresh").json()
    assert result["updated"] == 1 and result["removed"] == 0
    assert client.get("/api/movies").json()[0]["product_folder_id"] != library["id"]
    assert metadata.is_file()


def test_remove_library_preserves_files_other_movies_and_history(client, tmp_path):
    from PIL import Image
    from sqlalchemy import select

    from jav_data.models import MovieActress

    root = tmp_path / "My movies 日本語"
    metadata = disk_movie(root)
    cover_path = metadata.parent / "demo001-fanart.jpg"
    Image.new("RGB", (240, 160), "white").save(cover_path)
    nfo = metadata.parent / "movie.nfo"
    nfo.write_text("custom NFO", encoding="utf-8")
    original = {path: path.read_bytes() for path in (metadata, cover_path, nfo)}
    library = client.post("/api/product-folders", json={"path": str(root)}).json()[-1]
    assert library["label"] == root.name
    removed_movie = client.get("/api/movies").json()[0]
    disk_movie(client.app.state.settings.library_dir, "demo002")
    client.post("/api/product-folders/refresh")
    with Session(client.app.state.engine) as session:
        for status in ("queued", "running", "awaiting_session", "completed", "failed"):
            session.add(
                ScrapeJob(
                    product_folder_id=library["id"],
                    movie_id=removed_movie["id"],
                    url="https://video.dmm.co.jp/av/content/?id=" + status,
                    status=status,
                )
            )
        session.commit()
    result = client.post(f"/api/product-folders/{library['id']}/remove")
    assert result.status_code == 200
    assert result.json()["removed"] == 1
    assert [folder["label"] for folder in result.json()["folders"]] == ["library"]
    assert [movie["distribution_product_id"] for movie in client.get("/api/movies").json()] == [
        "demo002"
    ]
    assert client.get("/api/media-assets").json() == []
    with Session(client.app.state.engine) as session:
        assert (
            session.scalar(select(MovieActress).where(MovieActress.movie_id == removed_movie["id"]))
            is None
        )
        assert all(job.product_folder_id is None for job in session.scalars(select(ScrapeJob)))
    jobs = client.get("/api/scrape-jobs").json()
    assert all(job["movie_id"] is None for job in jobs)
    assert all(
        job["status"] == "failed"
        for job in jobs
        if job["url"].endswith(("queued", "running", "awaiting_session"))
    )
    assert all(path.read_bytes() == value for path, value in original.items())
    assert client.post(f"/api/product-folders/{library['id']}/remove").status_code == 404
    restored = client.post("/api/product-folders", json={"path": str(root)}).json()[-1]
    assert restored["scan"]["added"] == 1
    assert client.get("/api/media-assets").json()[0]["status"] == "completed"
    # Old jobs must never redirect to a new or restored library on retry.
    assert client.post(f"/api/scrape-jobs/{jobs[0]['id']}/retry").status_code == 400


def test_remove_default_and_last_library_persists_across_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("JAV_DATA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("JAV_DATA_LIBRARY_DIR", str(tmp_path / "library"))
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(config, "head")
    settings = Settings.load()
    with TestClient(create_app(settings)) as client:
        primary = client.get("/api/product-folders").json()[0]
        extra = client.post("/api/product-folders", json={"path": str(tmp_path / "extra")}).json()[
            -1
        ]
        url = "https://video.dmm.co.jp/av/content/?id=demo001"
        job = client.post(
            "/api/scrape-jobs", json={"urls": [url], "product_folder_id": primary["id"]}
        ).json()[0]
        assert client.post(f"/api/product-folders/{primary['id']}/remove").status_code == 200
    command.upgrade(config, "head")
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/product-folders").json() == [
            {key: value for key, value in extra.items() if key != "scan"}
        ]
        assert client.post(f"/api/scrape-jobs/{job['id']}/retry").status_code == 400
        assert client.post(f"/api/product-folders/{extra['id']}/remove").json()["folders"] == []
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/product-folders").json() == []
        assert client.post("/api/scrape-jobs", json={"urls": [url]}).status_code == 400
        assert (
            client.post(
                "/api/movies", json={"distribution_product_id": "demo001", "title": "作品"}
            ).status_code
            == 400
        )
        # Readding the default path restores its portable location semantics.
        restored = client.post("/api/product-folders", json={"path": str(settings.library_dir)})
        assert restored.status_code == 201
        assert restored.json()[0]["label"] == "library"
        assert client.post("/api/scrape-jobs", json={"urls": [url]}).status_code == 201
