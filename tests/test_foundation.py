from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from jav_data.app import create_app
from jav_data.config import Settings

ROOT = Path(__file__).resolve().parents[1]


def test_config_paths_and_environment_override(tmp_path, monkeypatch):
    config = tmp_path / "config.toml"
    config.write_text('[storage]\ndata_dir="db"\nlibrary_dir="media 日本語"', encoding="utf-8")
    settings = Settings.load(config)
    assert settings.data_dir == tmp_path / "db"
    assert settings.library_dir == tmp_path / "media 日本語"
    monkeypatch.setenv("JAV_DATA_LIBRARY_DIR", str(tmp_path / "override"))
    assert Settings.load(config).library_dir == tmp_path / "override"


def test_migration_and_dashboard(tmp_path, monkeypatch):
    monkeypatch.setenv("JAV_DATA_DATA_DIR", str(tmp_path / "db 日本語"))
    monkeypatch.setenv("JAV_DATA_LIBRARY_DIR", str(tmp_path / "media"))
    config = Config(str(ROOT / "alembic.ini"))
    command.upgrade(config, "head")
    command.upgrade(config, "head")  # Starting again must preserve an existing database.
    settings = Settings.load()
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").json()["database"] == "ok"
        assert client.get("/api/library").json()["total"] == 0
    assert settings.database_path.is_file()
    assert settings.library_dir.is_dir()


def test_unmigrated_database_does_not_report_ready(tmp_path):
    with pytest.raises(RuntimeError, match="alembic upgrade head"):
        with TestClient(create_app(Settings(tmp_path / "db", tmp_path / "media"))):
            pass
