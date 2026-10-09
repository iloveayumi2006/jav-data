from types import SimpleNamespace

from jav_data.desktop_ui import DesktopWindow


def navigation_window():
    calls = []
    shown = []
    window = SimpleNamespace(
        movie_navigation_index=23,
        movie_navigation_total=26,
        movie_navigation_context={
            "q": "出演者",
            "sort": "product_id_desc",
            "page": 1,
            "filter_field": "genres",
            "filter_value": "タグ",
        },
        movie_navigation_pages={1: [{"id": i} for i in range(24)]},
        movie_request_generation=0,
        api=SimpleNamespace(submit=lambda path, callback: calls.append((path, callback))),
        show_movie=lambda movie, generation: shown.append((movie, generation)),
    )
    window.request_navigation_movie = lambda: DesktopWindow.request_navigation_movie(window)
    return window, calls, shown


def test_detail_navigation_crosses_pages_with_search_and_sort():
    window, calls, shown = navigation_window()
    DesktopWindow.navigate_movie(window, 1)
    assert "page=2" in calls[-1][0] and "sort=product_id_desc" in calls[-1][0]
    assert "q=%E5%87%BA%E6%BC%94%E8%80%85" in calls[-1][0]
    assert "filter_field=genres" in calls[-1][0]
    assert "filter_value=%E3%82%BF%E3%82%B0" in calls[-1][0]
    calls[-1][1]({"items": [{"id": 24}, {"id": 25}]})
    assert calls[-1][0] == "/api/movies/24"
    calls[-1][1]({"id": 24})
    assert shown[-1][0]["id"] == 24
    DesktopWindow.navigate_movie(window, -1)
    assert calls[-1][0] == "/api/movies/23"
    window.movie_navigation_index = 0
    count = len(calls)
    DesktopWindow.navigate_movie(window, -1)
    assert len(calls) == count
    window.movie_navigation_index = 25
    DesktopWindow.navigate_movie(window, 1)
    assert len(calls) == count


def test_late_navigation_page_cannot_replace_newer_movie():
    window, calls, _shown = navigation_window()
    DesktopWindow.navigate_movie(window, 1)
    late_callback = calls[-1][1]
    DesktopWindow.navigate_movie(window, -1)
    assert calls[-1][0] == "/api/movies/23"
    count = len(calls)
    late_callback({"items": [{"id": 24}]})
    assert len(calls) == count
