"""Portable desktop entry point; embedded browser and private local services."""

import argparse
import hashlib
import json
import logging
import os
import socket
import sys
import threading
import time
from pathlib import Path

import uvicorn
from alembic import command
from alembic.config import Config
from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox

from jav_data.app import create_app
from jav_data.config import Settings, application_root
from jav_data.desktop_ui import DesktopWindow
from jav_data.qt_browser import BrowserContext, BrowserController


def migrate(settings):
    bundle = Path(getattr(sys, "_MEIPASS", application_root()))
    config = Config(str(bundle / "alembic.ini"))
    config.set_main_option("script_location", str(bundle / "migrations"))
    config.attributes["settings"] = settings
    command.upgrade(config, "head")


class Backend:
    def __init__(self, settings, controller, self_test=False):
        self.app = create_app(settings, lambda: BrowserContext(controller))
        self.socket = socket.socket()
        self.socket.bind(("127.0.0.1", 0))
        self.socket.listen(128)
        self.port = self.socket.getsockname()[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self.settings = settings
        if self_test:
            from fastapi.responses import HTMLResponse

            @self.app.get("/__desktop_check", response_class=HTMLResponse)
            def check_page():
                return (
                    "<html><body><h1>Browser check</h1><script>"
                    "document.cookie='test=fictional;path=/';"
                    "setTimeout(()=>{document.body.dataset.ready='yes'},100)"
                    "</script></body></html>"
                )

        self.server = uvicorn.Server(
            uvicorn.Config(
                self.app,
                host="127.0.0.1",
                port=self.port,
                log_config=None,
                access_log=False,
                timeout_graceful_shutdown=5,
            )
        )
        self.thread = threading.Thread(target=self.run, name="jav-data-services", daemon=True)

    def run(self):
        try:
            self.server.run(sockets=[self.socket])
        except Exception:
            logging.exception("Desktop services failed")

    def start(self):
        self.thread.start()
        for _ in range(200):
            if self.server.started:
                (self.settings.data_dir / "runtime.json").write_text(
                    json.dumps({"pid": os.getpid(), "port": self.port}), encoding="utf-8"
                )
                return
            if not self.thread.is_alive():
                break
            time.sleep(0.05)
        raise RuntimeError("Desktop services could not start. See data/jav-data.log.")

    def stop(self):
        self.server.should_exit = True


def existing_instance(name):
    connection = QLocalSocket()
    connection.connectToServer(name)
    if connection.waitForConnected(300):
        connection.write(b"activate")
        connection.waitForBytesWritten(300)
        connection.disconnectFromServer()
        return True
    return False


def self_check(window, output):
    """Offline packaged-app validation without touching the user's database."""
    import xml.etree.ElementTree as ET
    from concurrent.futures import ThreadPoolExecutor

    from PySide6.QtCore import QObject, Signal

    class Result(QObject):
        finished = Signal(object)

    result = Result(window)
    website_sources = [window.auth_source.itemText(i) for i in range(window.auth_source.count())]
    search_sources = [window.search_source.itemText(i) for i in range(window.search_source.count())]

    def finished(report):
        window.grab().save(str(Path(output).with_suffix(".png")))
        Path(output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        window.close()

    result.finished.connect(finished)
    pool = ThreadPoolExecutor(max_workers=1)
    window._check_pool = pool

    def run():
        try:
            health = window.api.request("/health")
            assert health["status"] == "ok"
            assert website_sources == search_sources == ["DMM", "MGS"]
            assert window.api.request("/api/library")["total"] == 0
            context = BrowserContext(window.controller)
            browser_page = context.new_page()
            browser_page.goto(window.backend.base + "/__desktop_check")
            browser_page.wait_for_function("() => document.body.dataset.ready === 'yes'")
            assert "Browser check" in browser_page.content()
            context.storage_state(str(window.settings.data_dir / "browser-session.json"))
            cookies = json.loads((window.settings.data_dir / "browser-session.json").read_text())
            assert any(cookie["name"] == "test" for cookie in cookies["cookies"])
            browser_page.close()
            payload = {
                "distribution_product_id": "demo001",
                "title": "架空の日本語作品",
                "actresses": [f"架空の出演者{n}" for n in range(50)],
                "runtime": "120分",
            }
            movie = window.api.request("/api/movies", payload)
            assert len(movie["cast"]) == 50
            xml = window.api.request(f"/api/movies/{movie['id']}/nfo?profile=emby", raw=True)
            assert len(ET.fromstring(xml).findall("actor")) == 50
            exports = window.api.request(
                "/api/nfo/export", {"movie_ids": [movie["id"]], "profile": "emby"}
            )
            assert exports["results"][0]["status"] == "exported"
            result.finished.emit(
                {
                    "ok": True,
                    "native_screens": window.stack.count(),
                    "embedded_browser": True,
                    "cookies": True,
                    "japanese_cast": 50,
                    "nfo": True,
                    "website_sources": website_sources,
                    "executable": sys.executable,
                }
            )
        except Exception as error:
            logging.exception("Desktop check failed")
            result.finished.emit({"ok": False, "error": str(error)})
        finally:
            pool.shutdown(wait=False)

    pool.submit(run)


def main():
    parser = argparse.ArgumentParser(description="jav-data portable desktop app")
    parser.add_argument("--self-test", metavar="REPORT_JSON", help=argparse.SUPPRESS)
    args = parser.parse_args()
    os.chdir(application_root())
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("jav-data.Desktop")
    app = QApplication(sys.argv[:1])
    app.setApplicationName("jav-data")
    app.setWindowIcon(QIcon(str(Path(__file__).parent / "assets" / "app.ico")))
    app.setQuitOnLastWindowClosed(False)
    temporary = None
    if args.self_test:
        import tempfile

        temporary = tempfile.TemporaryDirectory(prefix="jav-data-desktop-check-")
        settings = Settings(Path(temporary.name) / "data", Path(temporary.name) / "library")
    else:
        settings = Settings.load()
    settings.prepare()
    logging.basicConfig(
        filename=settings.data_dir / "jav-data.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )
    name = "jav-data-" + hashlib.sha256(str(settings.data_dir).casefold().encode()).hexdigest()[:16]
    if not args.self_test and existing_instance(name):
        return
    local = QLocalServer(app)
    QLocalServer.removeServer(name)
    if not local.listen(name):
        raise RuntimeError("Could not create the desktop instance lock")
    try:
        migrate(settings)
        controller = BrowserController(settings, app)
        backend = Backend(settings, controller, bool(args.self_test))
        backend.start()
        window = DesktopWindow(backend, controller, settings)

        def activate():
            connection = local.nextPendingConnection()
            if connection:
                connection.close()
                connection.deleteLater()
            window.showNormal()
            window.raise_()
            window.activateWindow()

        local.newConnection.connect(activate)
        window.show()
        if args.self_test:
            QTimer.singleShot(500, lambda: self_check(window, args.self_test))
        exit_code = app.exec()
        for token in list(controller.pages):
            controller.close_page(token)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        if controller.profile is not None:
            controller.profile.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        for _ in range(10):
            app.processEvents()
            time.sleep(0.05)
        (settings.data_dir / "runtime.json").unlink(missing_ok=True)
        local.close()
        if temporary:
            logging.shutdown()
            temporary.cleanup()
        return exit_code
    except Exception as error:
        logging.exception("Desktop startup failed")
        if args.self_test:
            Path(args.self_test).write_text(json.dumps({"ok": False, "error": str(error)}))
        else:
            QMessageBox.critical(None, "jav-data startup failed", str(error))
        return 1


if __name__ == "__main__":
    sys.exit(main() or 0)
