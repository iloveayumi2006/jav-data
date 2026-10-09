import json
from unittest.mock import MagicMock

from jav_data.config import Settings
from jav_data.database import make_engine
from jav_data.jobs import ScrapeWorker


def test_ready_saves_cookies_and_reopening_restores_them(tmp_path, monkeypatch):
    settings = Settings(tmp_path / "data", tmp_path / "library")
    settings.prepare()
    engine = make_engine(settings)
    browser = MagicMock()
    cookies = [{"name": "test", "value": "fictional", "domain": ".dmm.co.jp", "path": "/"}]
    (settings.data_dir / "browser-session.json").write_text(
        json.dumps({"cookies": cookies, "origins": []}), encoding="utf-8"
    )

    def save_state(path):
        with open(path, "w", encoding="utf-8") as file:
            json.dump({"cookies": cookies, "origins": []}, file)

    browser.storage_state.side_effect = save_state
    browser.pages = [MagicMock()]
    auth_page = MagicMock()
    auth_page.is_closed.return_value = False
    browser.new_page.return_value = auth_page
    factory = MagicMock(return_value=browser)
    # Opening looks for queued jobs, so use the real current schema in this isolated database.
    from jav_data.database import Base

    Base.metadata.create_all(engine)
    worker = ScrapeWorker(settings, engine, factory)
    worker.start()
    try:
        worker.command("open").result(timeout=5)
        worker.command("ready").result(timeout=5)
        auth_page.goto.assert_called_once_with("https://video.dmm.co.jp/av/", timeout=45000)
        assert (settings.data_dir / "browser-session.json").is_file()
        worker.command("close").result(timeout=5)
        browser.close.assert_not_called()
        auth_page.close.assert_called_once()
        worker.command("open").result(timeout=5)
        factory.assert_called_once()
        assert (
            json.loads((settings.data_dir / "browser-session.json").read_text())["cookies"]
            == cookies
        )
        assert worker.browser is browser
    finally:
        worker.stop()
        engine.dispose()
