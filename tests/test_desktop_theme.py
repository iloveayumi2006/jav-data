from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from PySide6.QtWidgets import QApplication

from jav_data.config import Settings
from jav_data.desktop_ui import ApiClient, DesktopWindow, MovieCard
from jav_data.qt_browser import BrowserController
from jav_data.schemas import MovieInput


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


def test_sidebar_view_buttons_and_sort_controls_keep_existing_query_context(window, monkeypatch):
    for index, control in enumerate(window.navigation.buttons):
        control.click()
        assert window.navigation.currentRow() == window.stack.currentIndex() == index
    window.navigation.buttons[0].click()
    window.library_view.group.button(1).click()
    assert window.library_view.currentIndex() == window.library_views.currentIndex() == 1
    assert window.open_selected_button.isHidden()
    window.library_view.group.button(0).click()
    assert window.library_view.currentIndex() == window.library_views.currentIndex() == 0
    assert not window.open_selected_button.isHidden()
    calls = []
    monkeypatch.setattr(window.api, "submit", lambda path, *a, **kw: calls.append(path))
    window.library_query.setText("検索")
    window.library_tag_filter = ("genres", "日本語")
    window.library_page = 5
    index = window.library_sort_combo.findData(2)
    window.library_sort_combo.setCurrentIndex(index)
    window.library_sort_combo.activated.emit(index)
    params = parse_qs(urlsplit(calls[-1]).query)
    assert params == {
        "q": ["検索"],
        "filter_field": ["genres"],
        "filter_value": ["日本語"],
        "page": ["1"],
        "sort": ["product_id_asc"],
    }
    window.library_order_button.click()
    assert parse_qs(urlsplit(calls[-1]).query)["sort"] == ["product_id_desc"]
    window.library_table.horizontalHeader().sectionClicked.emit(3)
    assert window.library_sort_combo.currentData() == 3
    assert parse_qs(urlsplit(calls[-1]).query)["sort"] == ["actresses_asc"]


def test_fixed_cover_cards_reflow_for_small_and_wide_windows_with_long_metadata(window):
    app = QApplication.instance()
    movie = MovieInput(
        distribution_product_id="demo001",
        title="長い日本語タイトル" * 20,
        actresses=[f"出演者{index}" for index in range(50)],
    ).model_dump(mode="json") | {"id": 1, "cover": None}
    window.show_library(
        {"items": [movie] * 24, "total": 24, "page": 1, "pages": 1}, window.library_generation
    )
    window.library_view.group.button(1).click()
    window.resize(1120, 780)
    window.show()
    app.processEvents()
    columns = window.card_grid.columns
    assert columns >= 2
    assert all(
        card.width() == MovieCard.WIDTH and card.height() == MovieCard.HEIGHT
        for card in window.library_cards.values()
    )
    window.resize(3840, 1600)
    app.processEvents()
    assert window.card_grid.columns > columns
    assert len(window.library_cards) == 24
