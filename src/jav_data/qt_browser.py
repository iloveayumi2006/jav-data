"""Thread-safe Qt browser adapter for the existing scraper/search page interface."""

import json
import time
import uuid
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtWebEngineCore import (
    QWebEngineLoadingInfo,
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineScript,
    QWebEngineSettings,
    QWebEngineUrlRequestInfo,
    QWebEngineUrlRequestInterceptor,
)


class ScrapeResources(QWebEngineUrlRequestInterceptor):
    """Background metadata pages need DOM/scripts, not decoded pictures or video."""

    BLOCKED = frozenset(
        getattr(QWebEngineUrlRequestInfo.ResourceType, "ResourceType" + name)
        for name in ("Image", "Media", "FontResource", "Prefetch", "Favicon")
    )

    def interceptRequest(self, info):
        # Runs on Chromium's request path: never call the profile or perform I/O here.
        if info.resourceType() in self.BLOCKED:
            info.block(True)


class Navigation(QObject):
    """One cancellable navigation, with a DOM-ready marker unique to its document."""

    def __init__(self, page, url, timeout, wait_until, future):
        super().__init__(page)
        self.page, self.future = page, future
        self.done = False
        self.wait_until = wait_until
        self.checking = False
        self.marker = uuid.uuid4().hex
        self.deadline = QTimer(self)
        self.deadline.setSingleShot(True)
        self.deadline.timeout.connect(self.timed_out)
        self.poll = QTimer(self)
        self.poll.setInterval(100)
        self.poll.timeout.connect(self.check_dom)
        page.navigation = self
        page.setLifecycleState(QWebEnginePage.LifecycleState.Active)
        self.script = QWebEngineScript()
        self.script.setName("jav-data-navigation")
        self.script.setWorldId(QWebEngineScript.ScriptWorldId.ApplicationWorld)
        self.script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
        self.script.setRunsOnSubFrames(False)
        self.script.setSourceCode(f"window.__javDataReady = '{self.marker}';")
        page.scripts().insert(self.script)
        self.poll.start()
        page.loadingChanged.connect(self.loading_changed)
        self.deadline.start(timeout)
        page.setUrl(QUrl(url))

    def check_dom(self):
        if self.done or self.checking:
            return
        self.checking = True
        completed = " && document.readyState === 'complete'" if self.wait_until == "load" else ""
        self.page.runJavaScript(
            f"window.__javDataReady === '{self.marker}'{completed}",
            QWebEngineScript.ScriptWorldId.ApplicationWorld,
            self.dom_checked,
        )

    def dom_checked(self, ready):
        self.checking = False
        if ready and not self.done:
            self.finish()

    def loading_changed(self, info):
        status = QWebEngineLoadingInfo.LoadStatus
        # Chromium can coalesce loadStarted when replacing a still-loading document.
        # Success belongs to this navigation only after its own document marker exists.
        if info.status() == status.LoadSucceededStatus:
            self.check_dom()
        elif (
            info.status() == status.LoadFailedStatus
            and info.errorCode() != -3  # ERR_ABORTED from a superseded/stopped navigation
            and info.url() in (self.page.url(), self.page.requestedUrl())
        ):
            self.finish("Embedded browser could not load the page")

    def timed_out(self):
        self.finish("Embedded browser navigation timed out", stop=True)

    def finish(self, error=None, *, stop=False):
        if self.done:
            return
        self.done = True
        self.deadline.stop()
        self.poll.stop()
        self.page.loadingChanged.disconnect(self.loading_changed)
        self.page.scripts().remove(self.script)
        self.page.navigation = None
        if stop:
            self.page.triggerAction(QWebEnginePage.WebAction.Stop)
        self.page.controller.finish(self.future, 200 if error is None else None, error)
        self.page.update_lifecycle()
        self.deleteLater()


class WebPage(QWebEnginePage):
    def __init__(self, controller, background=False):
        super().__init__(controller.ensure_profile(), controller)
        self.controller = controller
        self.background = background
        self.navigation = None
        self.settings().setAttribute(
            QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, True
        )
        if background:
            self.resources = ScrapeResources(self)
            self.setUrlRequestInterceptor(self.resources)
            self.setAudioMuted(True)
        self.visibleChanged.connect(self.update_lifecycle)
        self.recommendedStateChanged.connect(self.update_lifecycle)

    def update_lifecycle(self, *_args):
        # Never freeze a worker page or interrupt a load/login that Qt considers active.
        state = QWebEnginePage.LifecycleState
        if self.background or self.navigation is not None or self.isVisible():
            target = state.Active
        else:
            target = state.Active if self.recommendedState() == state.Active else state.Frozen
        if self.lifecycleState() != target:
            self.setLifecycleState(target)

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

    def new_page(self, background=False):
        token = uuid.uuid4().hex
        page = WebPage(self, background)
        self.pages[token] = page
        page.windowCloseRequested.connect(lambda: self.close_page(token))
        return token

    def show_page(self, token):
        page = self.pages[token]
        page.setLifecycleState(QWebEnginePage.LifecycleState.Active)
        self.pageShown.emit(page)

    def close_page(self, token):
        page = self.pages.pop(token, None)
        if page:
            if page.navigation is not None:
                page.navigation.finish("The embedded browser page was closed", stop=True)
            self.pageClosed.emit(page)
            page.triggerAction(QWebEnginePage.WebAction.Stop)
            page.deleteLater()

    @Slot(object)
    def dispatch(self, request):
        action, token, value, future = request
        if future.cancelled():
            return
        try:
            if action == "new":
                self.finish(future, self.new_page(background=bool(value)))
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
                    url, timeout, wait_until = value
                    if wait_until not in {"load", "domcontentloaded"}:
                        raise ValueError("Unsupported browser navigation wait mode")
                    if page.navigation is not None:
                        page.navigation.finish("Browser navigation was replaced", stop=True)
                    Navigation(page, url, timeout, wait_until, future)
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

    def goto(self, url, timeout=45000, wait_until="load"):
        status = self.controller.call(
            "goto", self.token, (url, timeout, wait_until), timeout / 1000 + 5
        )
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

    def new_page(self, *, background=False):
        return BrowserPage(self.controller, self.controller.call("new", value=background))

    def storage_state(self, path):
        state = {"cookies": self.controller.call("cookies"), "origins": []}
        destination = Path(path)
        temporary = destination.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(state), encoding="utf-8")
        temporary.replace(destination)
        return state

    def close(self):
        self.controller.call("close_all")
