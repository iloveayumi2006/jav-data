import io
import threading
from types import SimpleNamespace

import pytest
from PIL import Image
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QDialog

from jav_data.config import Settings
from jav_data.desktop_ui import ApiClient, DesktopWindow
from jav_data.qt_browser import BrowserController


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def test_hidden_cards_are_lazy_and_closed_cover_windows_are_destroyed(
    qt_app, tmp_path, monkeypatch
):
    monkeypatch.setattr(ApiClient, "submit", lambda *args, **kwargs: None)
    settings = Settings(tmp_path / "data", tmp_path / "library")
    controller = BrowserController(settings)
    assert controller.profile is None
    window = DesktopWindow(SimpleNamespace(base="http://127.0.0.1:1"), controller, settings)
    assert window.browser_view is None
    movie = {
        "id": 1,
        "title": "Example",
        "distribution_product_id": "example001",
        "streaming_release_date": "2026/10/01",
        "maker": "Example",
        "actresses": [],
        "cover": None,
    }
    window.show_library(
        {"items": [movie], "total": 1, "page": 1, "pages": 1}, window.library_generation
    )
    assert not window.library_cards
    window.library_view.setCurrentIndex(1)
    assert len(window.library_cards) == 1
    data = io.BytesIO()
    Image.new("RGB", (600, 400), "white").save(data, format="PNG")
    for _ in range(8):
        window.show_full_cover(data.getvalue(), "example.png")
        window.dialogs[-1].close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert window.dialogs == []
    assert window.findChildren(QDialog) == []
    token = controller.new_page()
    controller.show_page(token)
    assert window.browser_view is not None
    controller.close_page(token)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert window.browser_view is None and not controller.pages
    for key in range(40):
        window.show_thumbnail(data.getvalue(), 0, window.library_generation, (key, "v1"))
    assert window.preview_cache_bytes <= 24 * 1024 * 1024
    assert len(window.preview_cache) < 40
    window.api.pool.shutdown()
    window.api.preview_pool.shutdown()
    window.deleteLater()
    controller.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_cancelled_library_requests_cannot_deliver_stale_results(qt_app):
    api = ApiClient("unused")
    completed = threading.Event()
    release = threading.Event()
    delivered = []

    def request(*args):
        completed.set()
        assert release.wait(2)
        return b"old preview"

    api.request = request
    api.submit("/old", delivered.append, raw=True, group="library")
    assert completed.wait(2)
    release.set()
    api.preview_pool.shutdown(wait=True)
    api.cancel_group("library")
    qt_app.processEvents()
    assert not delivered
    api.pool.shutdown()
    api.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
