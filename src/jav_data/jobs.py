"""Persistent pasted-URL jobs and single-owner browser session worker."""

import json
import queue
import threading
import time
from concurrent.futures import Future
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from jav_data.library_sync import LibraryActivity
from jav_data.media import discover_images
from jav_data.models import MediaAsset, Movie, ScrapeJob, utc_now
from jav_data.movies import serialize, write_movie
from jav_data.nfo import write_emby_nfo
from jav_data.schemas import MovieInput
from jav_data.scraper import SessionRequired, parse_product, product_url
from jav_data.storage import movie_root


class ScrapeWorker:
    def __init__(self, settings, engine, browser_factory=None, library_lock=None):
        self.library_lock = library_lock or LibraryActivity()
        self.settings = settings
        self.engine = engine
        self.browser_factory = browser_factory
        self.commands = queue.Queue()
        self.state = "closed"
        self.browser = None
        self.auth_page = None
        self.stopping = threading.Event()
        self.next_scrape_at = 0.0
        self.thread = threading.Thread(target=self.run, name="jav-data-browser", daemon=True)

    def start(self):
        with Session(self.engine) as session:
            for job in session.scalars(select(ScrapeJob).where(ScrapeJob.status == "running")):
                job.status = "queued"
                job.error = "Interrupted by app restart; queued again"
            session.commit()
        self.thread.start()

    def command(self, action):
        future = Future()
        self.commands.put((action, future))
        return future

    def stop(self):
        self.stopping.set()
        self.thread.join(timeout=65)

    def close_browser(self):
        if self.browser:
            try:
                self.browser.storage_state(
                    path=str(self.settings.data_dir / "browser-session.json")
                )
                self.browser.close()
            except Exception:
                pass
        self.browser = None
        self.auth_page = None
        self.state = "closed"

    def ensure_browser(self):
        if self.browser:
            return
        if self.browser_factory is None:
            raise ValueError("Start the desktop app to use its embedded website browser.")
        self.browser = self.browser_factory()

    def browser_closed(self, *args):
        self.browser = None
        self.auth_page = None
        self.state = "closed"

    def run(self):
        try:
            while not self.stopping.is_set():
                try:
                    action, future = self.commands.get(timeout=0.5)
                except queue.Empty:
                    if self.state == "ready" and time.monotonic() >= self.next_scrape_at:
                        self.process_next()
                    continue
                try:
                    if callable(action):
                        if not self.browser or self.state != "ready":
                            raise ValueError(
                                "Complete Website Authentication and mark the session ready first."
                            )
                        result = action(self.browser)
                        if not future.done():
                            future.set_result(result)
                        continue
                    elif action in {"open", "open:dmm", "open:mgs"}:
                        self.ensure_browser()
                        if self.auth_page is None or self.auth_page.is_closed():
                            self.auth_page = self.browser.new_page()
                        if action == "open:mgs":
                            target = "https://www.mgstage.com/"
                        elif action == "open:dmm":
                            target = "https://video.dmm.co.jp/av/"
                        else:
                            with Session(self.engine) as session:
                                first = session.scalar(
                                    select(ScrapeJob)
                                    .where(ScrapeJob.status == "queued")
                                    .order_by(ScrapeJob.id)
                                )
                                target = first.url if first else "https://video.dmm.co.jp/av/"
                        self.auth_page.goto(target, timeout=45000)
                        self.auth_page.bring_to_front()
                        self.state = "awaiting_confirmation"
                    elif action == "ready":
                        if not self.browser:
                            raise ValueError("Open the session browser first")
                        self.state = "ready"
                        self.browser.storage_state(
                            path=str(self.settings.data_dir / "browser-session.json")
                        )
                    elif action == "close":
                        self.state = "closed"
                        if self.browser:
                            self.browser.storage_state(
                                path=str(self.settings.data_dir / "browser-session.json")
                            )
                        if self.auth_page and not self.auth_page.is_closed():
                            self.auth_page.close()
                        self.auth_page = None
                    if not future.done():
                        future.set_result({"status": self.state})
                except Exception as error:
                    if action in {"open", "open:dmm", "open:mgs"}:
                        self.close_browser()
                    if not future.done():
                        future.set_exception(
                            ValueError(
                                str(error)
                                if isinstance(error, ValueError)
                                else "Browser operation failed. Check the embedded browser/network."
                            )
                        )
        finally:
            self.close_browser()

    def process_next(self):
        with self.library_lock.work():
            return self._process_next()

    def _process_next(self):
        with Session(self.engine) as session:
            job = session.scalar(
                select(ScrapeJob).where(ScrapeJob.status == "queued").order_by(ScrapeJob.id)
            )
            if job is None:
                return
            job_id, url = job.id, job.url
            target_folder_id = job.product_folder_id
            job.status, job.error = "running", None
            job.attempts += 1
            session.commit()
        page = None
        try:
            page = self.browser.new_page()
            response = page.goto(url, wait_until="domcontentloaded", timeout=45000)
            if response and response.status >= 400:
                raise ValueError(f"Product page returned HTTP {response.status}")
            try:
                page.wait_for_function(
                    "() => /配信品番|収録時間|年齢認証|年齢確認/.test(document.body.innerText)",
                    timeout=10000,
                )
            except Exception:
                pass
            final_url = page.url
            if "accounts.dmm" in final_url or "age_check" in final_url:
                raise SessionRequired(
                    "Complete age confirmation/login, mark session ready, then retry"
                )
            product_url(final_url)  # Do not scrape unexpected redirects.
            html = page.content()
            metadata = parse_product(html, url)
            if urlsplit(url).hostname in {"www.mgstage.com", "mgstage.com"}:
                from jav_data.mgs import discover_cover

                images = discover_cover(html, metadata.distribution_product_id)
            else:
                images = discover_images(html, metadata.distribution_product_id)
            with Session(self.engine) as session:
                movie = session.scalar(
                    select(Movie).where(
                        Movie.distribution_product_id == metadata.distribution_product_id
                    )
                )
                if movie:
                    old_source = (
                        "mgs"
                        if urlsplit(movie.source_url or "").hostname
                        in {"www.mgstage.com", "mgstage.com"}
                        else "dmm"
                    )
                    new_source = (
                        "mgs"
                        if urlsplit(url).hostname in {"www.mgstage.com", "mgstage.com"}
                        else "dmm"
                    )
                    if old_source != new_source or (
                        new_source == "mgs"
                        and movie.manufacturer_product_id != metadata.manufacturer_product_id
                    ):
                        raise ValueError(
                            "Distribution ID conflict with an existing product; "
                            "no files were changed"
                        )
                    # A missing field on a page must not erase previously saved metadata.
                    old = serialize(movie).model_dump(include=set(MovieInput.model_fields))
                    changes = metadata.model_dump(exclude_unset=True)
                    old.update(changes)
                    metadata = MovieInput.model_validate(old)
                else:
                    movie = Movie(product_folder_id=target_folder_id)
                write_movie(session, movie, metadata)
                for source in images:
                    asset_filter = MediaAsset.kind == "cover"
                    asset = session.scalar(
                        select(MediaAsset).where(
                            MediaAsset.movie_id == movie.id,
                            asset_filter,
                        )
                    )
                    if asset is None:
                        asset = MediaAsset(movie_id=movie.id, **source, referer=url)
                        session.add(asset)
                    else:
                        changed_source = asset.url != source["url"]
                        changed_filename = asset.filename != source["filename"]
                        if asset.status != "downloading":
                            asset.filename = source["filename"]
                        asset.url, asset.referer = source["url"], url
                        if asset.status != "downloading" and (
                            asset.status != "completed"
                            or changed_source
                            or changed_filename
                            or not (
                                movie_root(self.settings, session, movie)
                                / movie.distribution_product_id
                                / asset.filename
                            ).is_file()
                        ):
                            asset.status, asset.error, asset.history_hidden = "queued", None, False
                session.commit()
                record = serialize(movie)
                folder = movie_root(self.settings, session, movie) / movie.distribution_product_id
                folder.mkdir(parents=True, exist_ok=True)
                temporary = folder / "metadata.json.tmp"
                temporary.write_text(
                    json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                temporary.replace(folder / "metadata.json")
                write_emby_nfo(session, self.settings, movie)
                job = session.get(ScrapeJob, job_id)
                job.status, job.movie_id, job.error = "completed", movie.id, None
                job.updated_at = utc_now()
                session.commit()
        except SessionRequired as error:
            self.state = "awaiting_confirmation"
            self.finish_error(job_id, "awaiting_session", str(error))
        except Exception as error:
            # Never persist exception text containing cookies or signed redirect URLs.
            message = (
                str(error)
                if isinstance(error, ValueError)
                else "Scrape failed; check browser/network and retry"
            )
            self.finish_error(job_id, "failed", message[:300])
        finally:
            self.next_scrape_at = time.monotonic() + 2
            if page:
                try:
                    page.close()
                except Exception:
                    self.close_browser()

    def finish_error(self, job_id, status, message):
        with Session(self.engine) as session:
            job = session.get(ScrapeJob, job_id)
            job.status, job.error, job.updated_at = status, message, utc_now()
            session.commit()
