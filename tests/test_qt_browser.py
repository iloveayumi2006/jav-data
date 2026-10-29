"""Real Chromium checks against a local server; no website account/profile is used."""

import threading
import time
from concurrent.futures import Future
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtWidgets import QApplication

from jav_data.config import Settings
from jav_data.qt_browser import BrowserController


def wait(qt_app, predicate, timeout=12):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "Browser did not complete the expected operation"
        qt_app.processEvents()
        time.sleep(0.005)


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def browser(qt_app, tmp_path):
    settings = Settings(tmp_path / "data", tmp_path / "library")
    settings.prepare()
    controller = BrowserController(settings)
    yield controller
    for token in list(controller.pages):
        controller.close_page(token)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    controller.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qt_app.processEvents()


@pytest.fixture
def site():
    release = threading.Event()
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            if self.path in {"/image", "/delayed"}:
                release.wait(20)
            if self.path == "/api":
                data, mime = b'{"ready":true}', "application/json"
            elif self.path == "/script":
                data = b"fetch('/api').then(r=>r.json()).then(()=>document.title='Script ready')"
                mime = "text/javascript"
            elif self.path == "/image":
                data, mime = b"not-an-image", "image/png"
            else:
                data = (
                    b"<html><head><title>Page</title></head><body>Metadata"
                    b"<img src='/image'><script src='/script'></script></body></html>"
                    if self.path == "/page"
                    else b"<html><body>Second document</body></html>"
                )
                mime = "text/html"
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield SimpleNamespace(
        url=f"http://127.0.0.1:{server.server_port}", requests=requests, release=release
    )
    release.set()
    server.shutdown()
    server.server_close()
    thread.join()


def navigate(controller, token, url, mode="domcontentloaded", timeout=10000):
    future = Future()
    controller.dispatch(("goto", token, (url, timeout, mode), future))
    return future


def test_dom_ready_does_not_wait_for_images_or_accept_previous_document(qt_app, browser, site):
    token = browser.new_page()
    page = browser.pages[token]
    page.setVisible(True)
    loaded = []
    page.loadFinished.connect(loaded.append)
    future = navigate(browser, token, site.url + "/page")
    wait(qt_app, future.done)
    assert future.result() == 200
    assert loaded == [] and not site.release.is_set()
    wait(qt_app, lambda: page.title() == "Script ready")
    site.release.set()
    wait(qt_app, lambda: bool(loaded))
    site.release.clear()
    second = navigate(browser, token, site.url + "/delayed")
    wait(qt_app, lambda: "/delayed" in site.requests)
    for _ in range(30):
        qt_app.processEvents()
        time.sleep(0.01)
    assert not second.done(), "A previous document's ready marker completed the new load"
    site.release.set()
    wait(qt_app, second.done)
    assert second.result() == 200
    assert page.navigation is None
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not page.findChildren(QTimer), "Completed navigation must release timers promptly"


def test_background_skips_images_but_preserves_scripts_and_fetch(qt_app, browser, site):
    token = browser.new_page(background=True)
    page = browser.pages[token]
    future = navigate(browser, token, site.url + "/page", "load")
    wait(qt_app, future.done)
    assert future.result() == 200
    wait(qt_app, lambda: page.title() == "Script ready")
    assert "/image" not in site.requests
    assert "/script" in site.requests and "/api" in site.requests
    html = []
    page.toHtml(html.append)
    wait(qt_app, lambda: bool(html))
    assert '<img src="/image">' in html[0], "Cover discovery still needs original DOM URLs"
    assert page.lifecycleState() == page.LifecycleState.Active


def test_full_load_waits_and_timeout_or_close_releases_pending_navigation(qt_app, browser, site):
    token = browser.new_page()
    page = browser.pages[token]
    page.setVisible(True)
    future = navigate(browser, token, site.url + "/page", "load")
    wait(qt_app, lambda: "/image" in site.requests)
    assert not future.done()
    site.release.set()
    wait(qt_app, future.done)
    assert future.result() == 200
    site.release.clear()
    timed_out = navigate(browser, token, site.url + "/delayed", timeout=300)
    wait(qt_app, timed_out.done)
    with pytest.raises(ValueError, match="timed out"):
        timed_out.result()
    assert page.navigation is None
    site.release.set()
    recovered = navigate(browser, token, site.url + "/ok")
    wait(qt_app, recovered.done)
    assert recovered.result() == 200
    site.release.clear()
    closed = navigate(browser, token, site.url + "/delayed")
    browser.close_page(token)
    assert closed.done()
    with pytest.raises(ValueError, match="closed"):
        closed.result()


def test_navigation_can_replace_loading_document_and_pending_request(qt_app, browser, site):
    token = browser.new_page()
    page = browser.pages[token]
    page.setVisible(True)
    for mode in ("load", "domcontentloaded", "load"):
        first = navigate(browser, token, site.url + "/page")
        wait(qt_app, first.done)
        assert first.result() == 200
        assert not site.release.is_set()
        second = navigate(browser, token, site.url + "/ok", mode)
        wait(qt_app, second.done)
        assert second.result() == 200
    pending = navigate(browser, token, site.url + "/delayed")
    wait(qt_app, lambda: "/delayed" in site.requests)
    replacement = navigate(browser, token, site.url + "/ok", "load")
    with pytest.raises(ValueError, match="replaced"):
        pending.result()
    wait(qt_app, replacement.done)
    assert replacement.result() == 200


def test_hidden_authentication_can_freeze_and_resume_without_affecting_worker(
    qt_app, browser, site
):
    token = browser.new_page()
    page = browser.pages[token]
    page.setVisible(True)
    future = navigate(browser, token, site.url + "/ok")
    wait(qt_app, future.done)
    assert future.result() == 200
    page.setVisible(False)
    wait(qt_app, lambda: page.lifecycleState() == page.LifecycleState.Frozen)
    page.setLifecycleState(page.LifecycleState.Active)
    page.setVisible(True)
    wait(qt_app, lambda: page.lifecycleState() == page.LifecycleState.Active)
    html = []
    page.toHtml(html.append)
    wait(qt_app, lambda: bool(html))
    assert "Second document" in html[0]
