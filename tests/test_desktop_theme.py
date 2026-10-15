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
    assert window.library_view.currentIndex() == window.library_views.currentIndex() == 1
    assert window.library_view.group.button(1).isChecked()
    assert not hasattr(window, "open_selected_button")
    for index, control in enumerate(window.navigation.buttons):
        control.click()
        assert window.navigation.currentRow() == window.stack.currentIndex() == index
    window.navigation.buttons[0].click()
    window.library_view.group.button(1).click()
    assert window.library_view.currentIndex() == window.library_views.currentIndex() == 1
    window.library_view.group.button(0).click()
    assert window.library_view.currentIndex() == window.library_views.currentIndex() == 0
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


def test_search_waits_for_completion_then_deletes_copies_and_saves(window, monkeypatch, tmp_path):
    from PySide6.QtCore import QItemSelectionModel
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QFileDialog

    requests = []
    monkeypatch.setattr(window.api, "submit", lambda *a, **kw: requests.append((a, kw)))
    window.navigation.setCurrentRow(2)
    window.resize(1440, 960)
    window.show()
    QTest.qWait(50)
    QApplication.processEvents()
    original_box = window.search_results.geometry()
    assert not window.copy_urls_button.isEnabled()
    assert not window.save_urls_button.isEnabled()
    window.product_query.setText("demo")
    window.start_search()
    window.search_id = "demo"
    window.search_running = True
    for _ in range(3):
        window.show_search({"status": "running", "source_pages": 4})
    assert not window.search_results.isHidden()
    assert window.search_urls_model.rowCount() == 0
    QApplication.processEvents()
    assert window.search_results.geometry() == original_box
    window.search_timer.stop()
    window.show_search({"status": "completed"})
    assert requests[-1][0][0].endswith("?all_urls=true")
    urls = [f"https://video.dmm.co.jp/av/content/?id=demo{i:05d}" for i in range(205)]
    requests[-1][0][1]({"status": "completed", "urls": urls, "total": 205})
    assert window.search_urls_model.stringList() == urls
    QApplication.processEvents()
    assert window.search_results.geometry() == original_box
    assert window.copy_urls_button.isEnabled() and window.save_urls_button.isEnabled()
    selection = window.urls_result.selectionModel()
    for row in (0, 5, 204):
        selection.select(
            window.search_urls_model.index(row), QItemSelectionModel.SelectionFlag.Select
        )
    window.delete_search_urls()
    expected = [url for row, url in enumerate(urls) if row not in {0, 5, 204}]
    window.copy_search_urls()
    assert QApplication.clipboard().text().splitlines() == expected
    output = tmp_path / "urls.txt"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: (str(output), ""))
    window.save_search_urls()
    assert output.read_text(encoding="utf-8").splitlines() == expected
    assert window.search_urls_model.rowCount() == 202


def test_compact_scrape_retry_still_targets_original_job(window, monkeypatch):
    from PySide6.QtWidgets import QPushButton

    calls = []
    monkeypatch.setattr(window.api, "submit", lambda path, *a, **kw: calls.append(path))
    window.show_jobs([{"id": 507, "status": "failed", "url": "sample", "error": "failed"}])
    retry = window.jobs_table.cellWidget(0, 4).findChild(QPushButton)
    assert retry.width() == 64 and retry.height() == 28
    retry.click()
    assert calls[-1] == "/api/scrape-jobs/507/retry"


def test_metadata_export_uses_displayed_filter_sort_and_excludes_page(
    window, monkeypatch, tmp_path
):
    from PySide6.QtWidgets import QFileDialog

    requests = []
    monkeypatch.setattr(window.api, "submit", lambda *a, **kw: requests.append((a, kw)))
    output = tmp_path / "export.xlsx"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: (str(output), ""))
    window.library_context = {
        "q": "検索",
        "filter_field": "actresses",
        "filter_value": "出演者",
        "sort": "release_date_desc",
        "page": 3,
    }
    window.export_metadata_button.click()
    args, kwargs = requests[-1]
    assert args[0].startswith("/api/library/export?") and kwargs["raw"]
    assert parse_qs(urlsplit(args[0]).query) == {
        "q": ["検索"],
        "filter_field": ["actresses"],
        "filter_value": ["出演者"],
        "sort": ["release_date_desc"],
    }
    assert not window.export_metadata_button.isEnabled()
    args[1](b"example workbook")
    assert output.read_bytes() == b"example workbook"
    assert window.export_metadata_button.isEnabled()
