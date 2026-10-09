from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

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


def numbers(window):
    return [int(button.text()) for button in window.library_page_buttons if not button.isHidden()]


@pytest.mark.parametrize("view", [0, 1])
def test_previous_and_next_visit_every_page_across_number_groups(window, monkeypatch, view):
    loaded = []

    def load():
        loaded.append(window.library_page)
        window.update_library_pagination(window.library_page, 25)

    monkeypatch.setattr(window, "load_library", load)
    window.library_view.setCurrentIndex(view)
    window.update_library_pagination(1, 25)
    assert numbers(window) == list(range(1, 11))
    assert not window.library_previous.isEnabled()
    for page in range(2, 26):
        assert window.library_next.isEnabled()
        window.library_next.click()
        assert loaded[-1] == page
        assert window.library_page_group.checkedButton().text() == str(page)
        if page == 10:
            assert numbers(window) == list(range(1, 11))
        if page == 11:
            assert numbers(window) == list(range(11, 21))
    assert loaded == list(range(2, 26))
    assert numbers(window) == list(range(21, 26))
    assert not window.library_next.isEnabled()
    window.library_next.click()
    assert loaded[-1] == 25
    for page in reversed(range(1, 25)):
        assert window.library_previous.isEnabled()
        window.library_previous.click()
        assert loaded[-1] == page
        if page == 20:
            assert numbers(window) == list(range(11, 21))
        if page == 10:
            assert numbers(window) == list(range(1, 11))
    assert loaded[24:] == list(reversed(range(1, 25)))
    assert not window.library_previous.isEnabled()
    window.library_previous.click()
    assert loaded[-1] == 1


@pytest.mark.parametrize("view", [0, 1])
def test_click_and_jump_work_in_both_views(window, monkeypatch, view):
    loaded = []
    monkeypatch.setattr(window, "load_library", lambda: loaded.append(window.library_page))
    window.library_view.setCurrentIndex(view)
    window.update_library_pagination(1, 25)
    window.library_page_buttons[6].click()
    assert loaded == [7]
    window.library_jump.setText("25")
    window.library_jump_button.click()
    assert loaded[-1] == 25
    window.update_library_pagination(25, 25)
    assert window.library_page_group.checkedButton().text() == "25"
    for invalid in ("", "0", "26", "-1", "abc"):
        window.library_jump.setText(invalid)
        window.jump_library()
    assert loaded == [7, 25]
    window.library_jump.setText("10")
    window.library_jump.returnPressed.emit()
    assert loaded[-1] == 10


def test_single_page_and_result_count_reduction(window, monkeypatch):
    window.update_library_pagination(1, 1)
    assert numbers(window) == [1]
    assert not window.library_previous.isEnabled() and not window.library_next.isEnabled()
    loaded = []
    monkeypatch.setattr(window, "load_library", lambda: loaded.append(window.library_page))
    window.show_library({"page": 21, "pages": 2}, window.library_generation)
    assert loaded == [2]
