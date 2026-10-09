"""Offline desktop benchmark using a database snapshot and read-only original covers."""

import time

STARTED = time.perf_counter()
import argparse
import ctypes
import json
import os
import sys
import sqlite3
import tempfile
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtWidgets import QApplication, QDialog

if module_root := os.environ.get("JAV_DATA_PROFILE_MODULES"):
    sys.path.insert(0, module_root)

from jav_data.config import Settings
from jav_data.desktop import Backend
from jav_data.desktop_ui import ApiClient, DesktopWindow
from jav_data.qt_browser import BrowserController


class Counters(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_ulong), ("faults", ctypes.c_ulong)] + [
        (name, ctypes.c_size_t)
        for name in (
            "peak_ws",
            "ws",
            "peak_paged",
            "paged",
            "peak_nonpaged",
            "nonpaged",
            "pagefile",
            "peak_pagefile",
            "private",
        )
    ]


def memory_mb():
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    kernel = ctypes.windll.kernel32
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    get_info = ctypes.windll.psapi.GetProcessMemoryInfo
    get_info.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_ulong]
    assert get_info(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
    return round(counters.private / 1048576, 1)


parser = argparse.ArgumentParser()
parser.add_argument("--output", required=True)
args = parser.parse_args()
original = Settings.load(Path("portable/jav-data/config.toml"))
temporary = tempfile.TemporaryDirectory(prefix="jav-data-profile-")
settings = Settings(Path(temporary.name) / "data", original.library_dir)
settings.data_dir.mkdir()
with sqlite3.connect(f"file:{original.database_path.as_posix()}?mode=ro", uri=True) as source:
    with sqlite3.connect(settings.database_path) as destination:
        source.backup(destination)
        destination.execute("UPDATE media_assets SET status='failed' WHERE status <> 'completed'")
        destination.execute("DELETE FROM scrape_jobs")
        destination.commit()
source.close()
destination.close()
app = QApplication([])
app.setQuitOnLastWindowClosed(False)
controller = BrowserController(settings, app)
backend = Backend(settings, controller)
backend.start()
metrics = {"requests": 0, "image_bytes": 0, "active": 0, "pending": 0, "last": time.perf_counter()}
request = ApiClient.request


def measured(self, path, body=None, raw=False):
    metrics["requests"] += 1
    metrics["active"] += 1
    try:
        result = request(self, path, body, raw)
        if raw:
            metrics["image_bytes"] += len(result)
        return result
    finally:
        metrics["active"] -= 1
        metrics["last"] = time.perf_counter()


ApiClient.request = measured
submit = ApiClient.submit


def tracked_submit(self, path, callback=None, **kwargs):
    metrics["pending"] += 1

    def rendered(result):
        try:
            if callback:
                callback(result)
        finally:
            metrics["pending"] -= 1
            metrics["last"] = time.perf_counter()

    return submit(self, path, rendered, **kwargs)


ApiClient.submit = tracked_submit
window = DesktopWindow(backend, controller, settings)
window.show()
report = {}
stage = 0
stage_start = STARTED
last_tick = time.perf_counter()
max_gap = 0


def tick():
    global stage, stage_start, last_tick, max_gap
    now = time.perf_counter()
    max_gap = max(max_gap, now - last_tick)
    last_tick = now
    if now - STARTED > 60:
        report["error"] = "benchmark timeout"
        finish()
        return
    if metrics["active"] or metrics["pending"] or now - metrics["last"] < 0.5:
        return
    if stage == 0:
        report["initial"] = {
            "ready_seconds": round(now - STARTED - 0.5, 3),
            "private_mb": memory_mb(),
            "requests": metrics["requests"],
            "image_mb": round(metrics["image_bytes"] / 1048576, 2),
            "hidden_cards": len(window.library_cards),
            "ui_max_gap_ms": round(max_gap * 1000, 1),
        }
        window.library_view.setCurrentIndex(1)
        stage = 1
        stage_start = now
        return
    if stage == 1 and now - stage_start > 0.4:
        report["cover_view_private_mb"] = memory_mb()
        window.open_movie(0)
        stage = 2
        stage_start = now
        return
    if stage == 2 and now - stage_start > 0.6:
        from sqlalchemy import select
        from sqlalchemy.orm import Session
        from jav_data.models import MediaAsset, Movie
        from jav_data.storage import movie_root

        with Session(backend.app.state.engine) as session:
            asset = session.scalar(select(MediaAsset).where(MediaAsset.status == "completed"))
            movie = session.get(Movie, asset.movie_id)
            data = (
                movie_root(settings, session, movie)
                / movie.distribution_product_id
                / asset.filename
            ).read_bytes()
        for _ in range(8):
            window.show_full_cover(data, "benchmark.jpg")
            window.dialogs[-1].close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        report["after_viewer_closes"] = {
            "private_mb": memory_mb(),
            "remaining_dialogs": len(window.findChildren(QDialog)),
        }
        stage = 3
        stage_start = now
        window.library_page = 2
        window.load_library()
        return
    if stage == 3:
        report["page2_seconds"] = round(now - stage_start - 0.5, 3)
        stage = 4
        stage_start = now
        window.library_page = 1
        window.load_library()
        return
    if stage == 4:
        report["return_page1_seconds"] = round(now - stage_start - 0.5, 3)
        report["final_private_mb"] = memory_mb()
        finish()


def finish():
    timer.stop()
    Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    window.close()


timer = QTimer()
timer.timeout.connect(tick)
timer.start(20)
app.exec()
for token in list(controller.pages):
    controller.close_page(token)
QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
if getattr(controller, "profile", None) is not None:
    controller.profile.deleteLater()
QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
for _ in range(10):
    app.processEvents()
    time.sleep(0.05)
temporary.cleanup()
print(json.dumps(report))
