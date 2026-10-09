from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel

from jav_data.config import Settings
from jav_data.desktop_ui import ApiClient, DesktopWindow
from jav_data.library import TAG_LABELS
from jav_data.qt_browser import BrowserController
from jav_data.schemas import MovieInput


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(ApiClient, "submit", lambda *args, **kwargs: None)
    settings = Settings(tmp_path / "data", tmp_path / "library")
    widget = DesktopWindow(SimpleNamespace(base="unused"), BrowserController(settings), settings)
    yield widget
    if widget.movie_dialog:
        widget.movie_dialog.hide()
    widget.hide()
    widget.api.pool.shutdown(wait=False)
    widget.api.preview_pool.shutdown(wait=False)
    widget.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("view", [0, 1])
def test_movie_tag_link_opens_exact_filter_and_clear_preserves_view_and_sort(
    window, monkeypatch, view
):
    value = '出演者 & "<名前>" · 日本語'
    movie = MovieInput(
        distribution_product_id="demo001",
        title="Demo",
        actresses=["First", value],
        source_url="https://video.dmm.co.jp/av/content/?id=demo001",
    ).model_dump(mode="json") | {"id": 1}
    window.library_view.setCurrentIndex(view)
    window.library_sort_column = 2
    window.library_sort_order = "desc"
    window.library_page = 7
    window.library_query.setText("Old search")
    window.show_movie(movie)
    field = window.movie_content.findChild(QLabel, "metadata_actresses")
    assert field.textFormat() == Qt.TextFormat.RichText
    assert field.text().count("<a href=") == 2
    assert "&lt;名前&gt;" in field.text() and "&amp;" in field.text()
    assert not field.openExternalLinks()
    source = next(
        label
        for label in window.movie_content.findChildren(QLabel)
        if label.text() == movie["source_url"]
    )
    assert source.textFormat() == Qt.TextFormat.AutoText
    assert "<a " not in source.text()
    requests = []
    monkeypatch.setattr(
        window.api, "submit", lambda *args, **kwargs: requests.append((args, kwargs))
    )
    previous_generation = window.movie_request_generation
    field.linkActivated.emit("1")
    assert window.movie_request_generation > previous_generation
    assert not window.movie_dialog.isVisible()
    assert window.navigation.currentRow() == 0 and window.library_page == 1
    assert window.library_view.currentIndex() == view and window.library_query.text() == ""
    assert window.library_filter_label.text().endswith(value)
    assert not window.library_filter_controls.isHidden()
    parameters = parse_qs(urlsplit(requests[-1][0][0]).query)
    assert parameters == {
        "page": ["1"],
        "sort": ["product_id_desc"],
        "filter_field": ["actresses"],
        "filter_value": [value],
    }
    window.library_query.setText("New search")
    window.search_library()
    assert parse_qs(urlsplit(requests[-1][0][0]).query)["q"] == ["New search"]
    window.clear_library_filter_button.click()
    assert window.library_tag_filter is None and window.library_filter_controls.isHidden()
    assert parse_qs(urlsplit(requests[-1][0][0]).query) == {
        "q": ["New search"],
        "page": ["1"],
        "sort": ["product_id_desc"],
    }
    assert window.library_view.currentIndex() == view


def test_every_metadata_link_uses_its_original_value_and_missing_values_stay_plain(
    window, monkeypatch
):
    clicked = []
    monkeypatch.setattr(window, "filter_library_by_tag", lambda *args: clicked.append(args))
    for key in TAG_LABELS:
        value = (
            ["監督A", "監督B"]
            if key in {"actresses", "directors", "genres", "related_tags"}
            else "メーカー"
        )
        field = window.movie_metadata_field(key, value)
        field.linkActivated.emit("1" if isinstance(value, list) else "0")
        assert clicked[-1] == (key, value[-1] if isinstance(value, list) else value)
        field.deleteLater()
        empty = window.movie_metadata_field(key, [])
        assert empty.text() == "—" and empty.textFormat() == Qt.TextFormat.PlainText
        empty.deleteLater()
