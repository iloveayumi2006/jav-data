"""Cover-only HTTP downloads with private cookie scoping and atomic verified writes."""

import json
import threading
import time
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from jav_data.library_sync import LibraryActivity
from jav_data.media import trusted_media_url
from jav_data.models import MediaAsset, Movie, utc_now
from jav_data.nfo import write_emby_nfo
from jav_data.storage import movie_root


def request_headers(settings, url, referer):
    headers = {"User-Agent": "Mozilla/5.0", "Referer": referer or "https://video.dmm.co.jp/"}
    path = settings.data_dir / "browser-session.json"
    if path.exists():
        state = json.loads(path.read_text(encoding="utf-8"))
        target = urlsplit(url)
        cookies = []
        for cookie in state.get("cookies", []):
            domain = cookie.get("domain", "")
            host = target.hostname or ""
            domain_matches = host == domain.lstrip(".") or (
                domain.startswith(".") and host.endswith(domain)
            )
            if (
                domain_matches
                and target.path.startswith(cookie.get("path", "/"))
                and (cookie.get("expires", -1) <= 0 or cookie["expires"] > time.time())
            ):
                cookies.append(cookie["name"] + "=" + cookie["value"])
        if cookies:
            headers["Cookie"] = "; ".join(cookies)
    if any("\r" in value or "\n" in value for value in headers.values()):
        raise ValueError("Invalid media request header")
    return headers


def asset_path(settings, product_id, filename, product_root=None):
    root = ((product_root or settings.library_dir) / product_id).resolve()
    path = (root / filename).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError("Invalid media file path")
    return path


class CoverRedirect(HTTPRedirectHandler):
    def __init__(self, settings, referer):
        self.settings, self.referer = settings, referer

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        trusted_media_url(newurl)
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected:
            redirected.remove_header("Cookie")
            for key, value in request_headers(self.settings, newurl, self.referer).items():
                redirected.add_header(key, value)
        return redirected


class DownloadWorker:
    def __init__(self, settings, engine, library_lock=None):
        self.library_lock = library_lock or LibraryActivity()
        self.settings, self.engine = settings, engine
        self.stopping = threading.Event()
        self.paused = False
        self.thread = threading.Thread(target=self.run, name="jav-data-covers", daemon=True)

    def start(self):
        with Session(self.engine) as session:
            for asset in session.scalars(
                select(MediaAsset).where(MediaAsset.status == "downloading")
            ):
                asset.status = "queued"
                asset.error = "Interrupted; queued again"
            session.commit()
        self.thread.start()

    def stop(self):
        self.stopping.set()
        self.thread.join(timeout=20)

    def run(self):
        while not self.stopping.wait(0.5):
            if not self.paused:
                self.process_next()

    def update(self, asset_id, **values):
        with Session(self.engine) as session:
            asset = session.get(MediaAsset, asset_id)
            for key, value in values.items():
                setattr(asset, key, value)
            asset.updated_at = utc_now()
            session.commit()

    def process_next(self):
        with self.library_lock.work():
            return self._process_next()

    def _process_next(self):
        with Session(self.engine) as session:
            asset = session.scalar(
                select(MediaAsset)
                .where(MediaAsset.status == "queued", MediaAsset.kind == "cover")
                .order_by(MediaAsset.id)
            )
            if asset is None:
                return
            movie = session.get(Movie, asset.movie_id)
            asset_id, url, referer = asset.id, asset.url, asset.referer
            destination = asset_path(
                self.settings,
                movie.distribution_product_id,
                asset.filename,
                movie_root(self.settings, session, movie),
            )
            asset.status, asset.error = "downloading", None
            asset.attempts += 1
            session.commit()
        part = destination.with_name(destination.name + ".part")
        try:
            trusted_media_url(url)
            destination.parent.mkdir(parents=True, exist_ok=True)
            request = Request(url, headers=request_headers(self.settings, url, referer))
            opener = build_opener(CoverRedirect(self.settings, referer))
            size = 0
            with opener.open(request, timeout=15) as response, part.open("wb") as output:
                total = int(response.headers.get("Content-Length", "0")) or None
                if total and total > 50_000_000:
                    raise ValueError("Cover exceeds the 50 MB download limit")
                self.update(asset_id, total_bytes=total, downloaded_bytes=0)
                last_progress = time.monotonic()
                while chunk := response.read(65536):
                    if self.stopping.is_set() or self.paused:
                        self.update(asset_id, status="queued", error="Download paused")
                        return
                    size += len(chunk)
                    if size > 50_000_000:
                        raise ValueError("Cover exceeds the 50 MB download limit")
                    output.write(chunk)
                    if time.monotonic() - last_progress >= 0.25:
                        self.update(asset_id, downloaded_bytes=size)
                        last_progress = time.monotonic()
                if total and size != total:
                    raise ValueError("Cover download was incomplete")
            with Image.open(part) as image:
                image.verify()
            with Image.open(part) as image:
                width, height = image.size
                if min(width, height) < 100:
                    raise ValueError("DMM returned a small placeholder, not a cover")
            part.replace(destination)
            self.update(
                asset_id,
                status="completed",
                error=None,
                downloaded_bytes=size,
                total_bytes=size,
                width=width,
                height=height,
            )
            with Session(self.engine) as session:
                movie = session.get(Movie, session.get(MediaAsset, asset_id).movie_id)
                write_emby_nfo(session, self.settings, movie)
        except Exception:
            self.update(
                asset_id,
                status="failed",
                error="Cover download failed; check the connection/session and retry",
            )
        finally:
            if part.exists():
                part.unlink()
