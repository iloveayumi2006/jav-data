"""Thread-safe Qt browser adapter for the existing scraper/search page interface."""

import json
import time
import uuid
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile


class WebPage(QWebEnginePage):
    def __init__(self, controller):
        super().__init__(controller.ensure_profile(), controller)
        self.controller = controller

    def createWindow(self, _kind):
        token = self.controller.new_page()
        self.controller.show_page(token)
        return self.controller.pages[token]


class BrowserController(QObject):
    requested = Signal(object)
    pageShown = Signal(object)
    pageClosed = Signal(object)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.pages = {}
        self.cookies = {}
        self.settings = settings
        self.profile = None
        self.requested.connect(self.dispatch)

    def ensure_profile(self):
        if self.profile is not None:
            return self.profile
        settings = self.settings
        self.profile = QWebEngineProfile("jav-data", self)
        self.profile.setPersistentStoragePath(str(settings.data_dir / "embedded-browser"))
        self.profile.setCachePath(str(settings.data_dir / "browser-cache"))
        self.profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
        )
        self.profile.setHttpAcceptLanguage("ja-JP,ja;q=0.9,en;q=0.7")
        store = self.profile.cookieStore()
        store.cookieAdded.connect(self.cookie_added)
        store.cookieRemoved.connect(self.cookie_removed)
        store.loadAllCookies()
        return self.profile

    def cookie_key(self, cookie):
        return (cookie.domain(), cookie.path(), bytes(cookie.name()))

    def cookie_added(self, cookie):
        self.cookies[self.cookie_key(cookie)] = {
            "name": bytes(cookie.name()).decode("utf-8", errors="replace"),
            "value": bytes(cookie.value()).decode("utf-8", errors="replace"),
            "domain": cookie.domain(),
            "path": cookie.path() or "/",
            "expires": -1
            if cookie.isSessionCookie()
            else cookie.expirationDate().toSecsSinceEpoch(),
            "httpOnly": cookie.isHttpOnly(),
            "secure": cookie.isSecure(),
        }

    def cookie_removed(self, cookie):
        self.cookies.pop(self.cookie_key(cookie), None)

    def call(self, action, token=None, value=None, timeout=60):
        future = Future()
        self.requested.emit((action, token, value, future))
        return future.result(timeout=timeout)

    @staticmethod
    def finish(future, result=None, error=None):
        if not future.done():
            if error:
                future.set_exception(ValueError(error))
            else:
                future.set_result(result)

    def new_page(self):
        token = uuid.uuid4().hex
        page = WebPage(self)
        self.pages[token] = page
        page.windowCloseRequested.connect(lambda: self.close_page(token))
        return token

    def show_page(self, token):
        self.pageShown.emit(self.pages[token])

    def close_page(self, token):
        page = self.pages.pop(token, None)
        if page:
            self.pageClosed.emit(page)
            page.triggerAction(QWebEnginePage.WebAction.Stop)
            page.deleteLater()

    @Slot(object)
    def dispatch(self, request):
        action, token, value, future = request
        try:
            if action == "new":
                self.finish(future, self.new_page())
            elif action == "pages":
                self.finish(future, list(self.pages))
            elif action == "cookies":
                self.finish(future, list(self.cookies.values()))
            elif action == "closed":
                self.finish(future, token not in self.pages)
            elif action == "close":
                self.close_page(token)
                self.finish(future)
            elif action == "close_all":
                for identifier in list(self.pages):
                    self.close_page(identifier)
                self.finish(future)
            elif action == "show":
                self.show_page(token)
                self.finish(future)
            else:
                page = self.pages.get(token)
                if page is None:
                    raise ValueError("The embedded browser page was closed")
                if action == "url":
                    self.finish(future, page.url().toString())
                elif action == "html":
                    page.toHtml(lambda html: self.finish(future, html))
                elif action == "js":
                    page.runJavaScript(value, lambda result: self.finish(future, result))
                elif action == "goto":
                    url, timeout = value

                    def loaded(ok):
                        try:
                            page.loadFinished.disconnect(loaded)
                        except RuntimeError:
                            pass
                        self.finish(
                            future,
                            200 if ok else None,
                            None if ok else "Embedded browser could not load the page",
                        )

                    page.loadFinished.connect(loaded)
                    page.setUrl(QUrl(url))
                    QTimer.singleShot(
                        timeout,
                        lambda: self.finish(future, error="Embedded browser navigation timed out"),
                    )
                else:
                    raise ValueError("Unknown embedded browser operation")
        except Exception as error:
            self.finish(future, error=str(error))


class BrowserPage:
    def __init__(self, controller, token):
        self.controller, self.token = controller, token

    @property
    def url(self):
        return self.controller.call("url", self.token)

    def goto(self, url, timeout=45000, **_kwargs):
        status = self.controller.call("goto", self.token, (url, timeout), timeout / 1000 + 5)
        return SimpleNamespace(status=status)

    def content(self):
        return self.controller.call("html", self.token)

    def wait_for_function(self, function, timeout=10000):
        deadline = time.monotonic() + timeout / 1000
        while time.monotonic() < deadline:
            if self.controller.call("js", self.token, f"Boolean(({function})())"):
                return
            time.sleep(0.1)
        raise TimeoutError("Embedded page content did not become ready")

    def is_closed(self):
        return self.controller.call("closed", self.token)

    def close(self):
        self.controller.call("close", self.token)

    def bring_to_front(self):
        self.controller.call("show", self.token)


class BrowserContext:
    def __init__(self, controller):
        self.controller = controller

    @property
    def pages(self):
        return [BrowserPage(self.controller, token) for token in self.controller.call("pages")]

    def new_page(self):
        return BrowserPage(self.controller, self.controller.call("new"))

    def storage_state(self, path):
        state = {"cookies": self.controller.call("cookies"), "origins": []}
        destination = Path(path)
        temporary = destination.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(state), encoding="utf-8")
        temporary.replace(destination)
        return state

    def close(self):
        self.controller.call("close_all")
