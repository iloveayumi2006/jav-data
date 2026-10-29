"""Synthetic offline browser benchmark; never opens real sites or user profiles.

Run from the project root:
    .venv/Scripts/python.exe scripts/profile-browser.py --output build/browser.json

The same warmed interactive page compares full-load and DOM-ready navigation. A
background page repeats the DOM-ready case with the scraper's resource filter.
Times describe this controlled local server, not DMM/MGS or VPN performance.
"""

import argparse
import base64
import json
import statistics
import threading
import time
from collections import Counter, defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urlsplit

from PySide6.QtCore import QCoreApplication, QEvent, Qt, QTimer
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication

from jav_data.config import Settings
from jav_data.qt_browser import BrowserController, BrowserPage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--image-delay", type=float, default=1.8)
    args = parser.parse_args()
    if not 1 <= args.rounds <= 10 or not 0.5 <= args.image_delay <= 5:
        parser.error("Use 1–10 rounds and an image delay of 0.5–5 seconds")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    counts = defaultdict(Counter)
    lock = threading.Lock()
    pixel = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a3K0"
        "AAAAASUVORK5CYII="
    )

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            request = urlsplit(self.path)
            case = parse_qs(request.query).get("case", ["warm"])[0]
            with lock:
                counts[case][request.path] += 1
            content_type = "text/html; charset=utf-8"
            if request.path == "/page":
                body = (
                    '<!doctype html><link rel="icon" href="data:,">'
                    f'<script src="/script.js?case={case}"></script>'
                    f'<img src="/slow.png?case={case}"><p>Local test metadata</p>'
                ).encode()
            elif request.path == "/script.js":
                content_type = "application/javascript"
                body = (
                    "window.scriptLoaded = true;"
                    f"fetch('/data?case={case}').then(r => r.json()).then(data => "
                    "{window.fetchLoaded = data.ok;});"
                ).encode()
            elif request.path == "/data":
                content_type, body = "application/json", b'{"ok":true}'
            elif request.path == "/slow.png":
                time.sleep(args.image_delay)
                content_type, body = "image/png", pixel
            else:
                body = b'<!doctype html><link rel="icon" href="data:,"><p>Warm page</p>'
            try:
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass  # DOM-ready navigation may leave its intentionally slow image behind.

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    base = f"http://127.0.0.1:{server.server_port}"
    report = {
        "method": "Synthetic local HTTP server, temporary browser profile, warmed pages",
        "limitation": "These are controlled navigation timings, not actual website timings.",
        "image_delay_ms": args.image_delay * 1000,
        "runs": [],
    }
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    temporary_profile = TemporaryDirectory(
        prefix="browser-benchmark-", dir=args.output.parent, ignore_cleanup_errors=True
    )
    try:
        with temporary_profile as temporary:
            root = Path(temporary)
            controller = BrowserController(Settings(root / "data", root / "library"))
            interactive = controller.new_page()
            # Give the page a visible lifecycle without displaying a user-facing window.
            view = QWebEngineView()
            view.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
            view.setPage(controller.pages[interactive])
            view.resize(800, 600)
            view.show()
            background = controller.new_page(background=True)

            def measure():
                try:
                    for token in (interactive, background):
                        BrowserPage(controller, token).goto(base + "/warm", timeout=10000)
                    for iteration in range(args.rounds):
                        for name, token, mode in (
                            ("interactive_full_load", interactive, "load"),
                            ("interactive_dom_ready", interactive, "domcontentloaded"),
                            ("background_dom_ready", background, "domcontentloaded"),
                        ):
                            case = f"{name}_{iteration}"
                            page = BrowserPage(controller, token)
                            start = time.perf_counter()
                            page.goto(base + "/page?case=" + case, timeout=10000, wait_until=mode)
                            navigation_ms = (time.perf_counter() - start) * 1000
                            page.wait_for_function(
                                "() => window.scriptLoaded && window.fetchLoaded", timeout=5000
                            )
                            with lock:
                                received = dict(counts[case])
                            if any(
                                received.get(path) != 1 for path in ("/page", "/script.js", "/data")
                            ):
                                raise AssertionError("The test page, script or fetch did not run")
                            if received.get("/slow.png", 0) != (token == interactive):
                                raise AssertionError("Unexpected image request policy")
                            report["runs"].append(
                                {
                                    "case": name,
                                    "round": iteration + 1,
                                    "navigation_ms": round(navigation_ms, 2),
                                    "script_and_fetch_ready_ms": round(
                                        (time.perf_counter() - start) * 1000, 2
                                    ),
                                    "requests": received,
                                }
                            )
                except Exception as error:
                    report["error"] = str(error)

            worker = threading.Thread(target=measure, daemon=True)
            worker.start()
            timer = QTimer()
            timer.timeout.connect(lambda: app.quit() if not worker.is_alive() else None)
            timer.start(25)
            app.exec()
            timer.stop()
            worker.join()
            view.hide()
            view.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            for token in list(controller.pages):
                controller.close_page(token)
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            controller.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    finally:
        server.shutdown()
        server.server_close()
        serving.join()
        # Chromium may finish a final cache write just after its Qt profile is destroyed.
        temporary_profile.cleanup()
    report["median_navigation_ms"] = {
        case: round(
            statistics.median(
                run["navigation_ms"] for run in report["runs"] if run["case"] == case
            ),
            2,
        )
        for case in dict.fromkeys(run["case"] for run in report["runs"])
    }
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if "error" in report:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
