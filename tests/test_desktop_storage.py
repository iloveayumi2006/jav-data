from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QPushButton

from jav_data.config import Settings
from jav_data.desktop_ui import ApiClient, DesktopWindow
from jav_data.qt_browser import BrowserController


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(ApiClient, "submit", lambda *args, **kwargs: None)
    settings = Settings(tmp_path / "data", tmp_path / "library")
    widget = DesktopWindow(SimpleNamespace(base="unused"), BrowserController(settings), settings)
    yield widget
    widget.hide()
    widget.api.pool.shutdown(wait=False)
    widget.api.preview_pool.shutdown(wait=False)
    widget.deleteLater()
    app.processEvents()


def test_library_names_selection_and_empty_state(window):
    libraries = [
        {"id": 1, "label": "Movies", "path": "D:/Movies"},
        {"id": 2, "label": "Movies", "path": "E:/Movies"},
    ]
    window.show_folders(libraries)
    assert window.library_folders.item(0, 0).text() == "Movies"
    assert window.library_folders.item(1, 1).text() == "E:/Movies"
    window.target_folder.setCurrentIndex(1)
    window.show_folders(libraries)
    assert window.target_folder.currentData() == 2
    window.show_folders([])
    assert window.library_folders.rowCount() == 0
    assert not window.target_folder.isEnabled() and not window.enqueue_button.isEnabled()
    assert window.add_library_button.isEnabled()


def test_remove_button_refreshes_library_and_recovers_after_error(window, monkeypatch):
    library = {"id": 3, "label": "日本語 Movies", "path": "D:/日本語 Movies"}
    window.show_folders([library])
    requests = []
    monkeypatch.setattr(
        window.api, "submit", lambda *args, **kwargs: requests.append((args, kwargs))
    )
    refreshed = []
    monkeypatch.setattr(window, "load_library", lambda: refreshed.append(True))
    monkeypatch.setattr(window, "refresh_status", lambda: None)
    window.library_folders.cellWidget(0, 2).click()
    args, kwargs = requests[-1]
    assert args[0] == "/api/product-folders/3/remove"
    assert not window.add_library_button.isEnabled() and not window.library_folders.isEnabled()
    kwargs["on_error"]("Removal failed")
    assert window.library_folders.isEnabled() and window.enqueue_button.isEnabled()
    window.library_folders.cellWidget(0, 2).click()
    requests[-1][0][1]({"folders": [], "removed": 4})
    assert refreshed == [True] and window.library_folders.rowCount() == 0
    assert "4 movies" in window.storage_feedback.text()
    assert "Files remain" in window.storage_feedback.text()
    assert window.add_library_button.isEnabled() and not window.enqueue_button.isEnabled()


def test_cover_numbers_restart_after_clear_and_retry_uses_permanent_id(window, monkeypatch):
    calls = []
    monkeypatch.setattr(window.api, "submit", lambda path, *a, **kw: calls.append(path))
    asset = {
        "id": 601,
        "filename": "demo-fanart.jpg",
        "status": "completed",
        "total_bytes": 100,
        "downloaded_bytes": 100,
        "width": 1000,
        "height": 700,
        "error": None,
    }
    window.show_covers([asset | {"id": 602}, asset])
    assert [window.covers_table.item(row, 0).text() for row in range(2)] == ["2", "1"]
    window.show_covers([])
    window.show_covers([asset | {"id": 903, "status": "failed"}])
    assert window.covers_table.horizontalHeaderItem(0).text() == "ID"
    assert window.covers_table.item(0, 0).text() == "1"
    retry = window.covers_table.cellWidget(0, 6).findChild(QPushButton)
    assert retry.width() == 64 and retry.height() == 28
    retry.click()
    assert calls[-1] == "/api/media-assets/903/retry"


def test_large_cover_list_reuses_rows_for_progress_and_new_downloads(window):
    def asset(i):
        return {
            "id": i,
            "filename": f"cover{i}.jpg",
            "status": "downloading",
            "total_bytes": 100000,
            "downloaded_bytes": 0,
            "width": None,
            "height": None,
            "error": None,
        }

    rows = [asset(i) for i in reversed(range(1, 1106))]
    window.show_covers(rows)
    assert window.covers_table.rowCount() == 1105
    preserved = window.covers_table.item(0, 1)
    progress = rows[0] | {"downloaded_bytes": 50000}
    window.show_covers([progress] + rows[1:])
    assert window.covers_table.item(0, 1) is preserved
    assert "49 KB" in window.covers_table.item(0, 3).text()
    window.show_covers([asset(1106), progress] + rows[1:])
    assert window.covers_table.rowCount() == 1106
    assert window.covers_table.item(1, 1) is preserved
    assert window.covers_table.item(0, 0).text() == "1106"
    assert window.covers_table.item(1105, 0).text() == "1"
    window.show_covers([asset(1106)])
    assert window.covers_table.rowCount() == 1
    assert window.covers_table.item(0, 0).text() == "1"
