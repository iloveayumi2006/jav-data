"""Import on-disk movie metadata and reconcile missing records without deleting files."""

import json
import threading
from contextlib import contextmanager
from pathlib import Path

from PIL import Image
from sqlalchemy import delete, select, update

from jav_data.models import MediaAsset, Movie, ProductFolder, ScrapeJob, utc_now
from jav_data.movies import serialize, write_movie
from jav_data.schemas import MovieInput


class LibraryActivity:
    """Allow scrape/download concurrency; reconciliation waits for both to finish."""

    def __init__(self):
        self.condition = threading.Condition()
        self.active = 0
        self.scanning = False

    @contextmanager
    def work(self):
        with self.condition:
            self.condition.wait_for(lambda: not self.scanning)
            self.active += 1
        try:
            yield
        finally:
            with self.condition:
                self.active -= 1
                self.condition.notify_all()

    @contextmanager
    def scan(self):
        with self.condition:
            self.condition.wait_for(lambda: not self.scanning)
            self.scanning = True
            self.condition.notify_all()
            self.condition.wait_for(lambda: self.active == 0)
        try:
            yield
        finally:
            with self.condition:
                self.scanning = False
                self.condition.notify_all()


def sync_libraries(session, settings, libraries, remove_missing=True):
    report = {"added": 0, "updated": 0, "removed": 0, "skipped": 0, "warnings": []}

    def warning(message):
        report["skipped"] += 1
        if len(report["warnings"]) < 50:
            report["warnings"].append(message[:400])

    for library in libraries:
        root = settings.library_dir if library.path == "@library" else Path(library.path)
        try:
            # An offline drive is not an empty library. Do not create it here.
            root_identity = root.stat()
            children = list(root.iterdir())
        except OSError:
            warning(f"Library unavailable: {root}")
            continue
        present = set()
        uncertain = set()
        for folder in children:
            if folder.is_symlink():
                uncertain.add(folder.name.casefold())
                warning(f"Skipped linked folder: {folder.name}")
                continue
            try:
                if not folder.is_dir():
                    continue
                metadata = folder / "metadata.json"
                if not metadata.exists() and not metadata.is_symlink():
                    continue
                present.add(folder.name.casefold())
                if metadata.is_symlink() or metadata.stat().st_size > 1_000_000:
                    raise ValueError("metadata is linked or too large")
                data = json.loads(metadata.read_text(encoding="utf-8-sig"))
                if not isinstance(data, dict):
                    raise ValueError("metadata must be a JSON object")
                payload = MovieInput.model_validate(
                    {key: value for key, value in data.items() if key in MovieInput.model_fields}
                )
                if payload.distribution_product_id.casefold() != folder.name.casefold():
                    raise ValueError("folder name does not match distribution ID")
                movie = session.scalar(
                    select(Movie).where(
                        Movie.distribution_product_id == payload.distribution_product_id
                    )
                )
                moved = False
                if movie and movie.product_folder_id != library.id:
                    if not previous_metadata_removed(session, settings, movie):
                        raise ValueError("distribution ID belongs to another library")
                    movie.product_folder_id = library.id
                    moved = True
                new = movie is None
                if new:
                    movie = Movie(product_folder_id=library.id)
                current = (
                    None
                    if new
                    else serialize(movie).model_dump(
                        include=set(MovieInput.model_fields), mode="json"
                    )
                )
                incoming = payload.model_dump(mode="json")
                if new or moved or current != incoming:
                    write_movie(session, movie, payload)
                    report["added" if new else "updated"] += 1
                sync_cover(session, movie, folder)
                session.commit()
            except (ValueError, OSError) as error:
                session.rollback()
                uncertain.add(folder.name.casefold())
                warning(f"{folder.name}: {error}")
        if remove_missing:
            try:
                current_root = root.stat()
                if (root_identity.st_dev, root_identity.st_ino) != (
                    current_root.st_dev,
                    current_root.st_ino,
                ):
                    raise OSError("Library changed during scan")
            except OSError:
                warning(f"Library unavailable or changed during scan: {root}")
                continue
            known = present | uncertain
            movies = session.execute(
                select(Movie.id, Movie.distribution_product_id).where(
                    Movie.product_folder_id == library.id
                )
            ).all()
            for identifier, product_id in movies:
                if product_id.casefold() in known:
                    continue
                session.execute(
                    update(ScrapeJob).where(ScrapeJob.movie_id == identifier).values(movie_id=None)
                )
                session.execute(delete(MediaAsset).where(MediaAsset.movie_id == identifier))
                session.execute(delete(Movie).where(Movie.id == identifier))
                report["removed"] += 1
            session.commit()
    return report


def previous_metadata_removed(session, settings, movie):
    """Recognize a moved movie only when its former library is still accessible."""
    library = session.get(ProductFolder, movie.product_folder_id)
    root = settings.library_dir if library.path == "@library" else Path(library.path)
    try:
        before = root.stat()
        next(root.iterdir(), None)  # Verify directory access, including empty libraries.
        folder = root / movie.distribution_product_id
        metadata = folder / "metadata.json"
        if folder.is_symlink() or metadata.exists() or metadata.is_symlink():
            return False
        after = root.stat()
        return (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino)
    except OSError:
        return False


def sync_cover(session, movie, folder):
    cover = session.scalar(
        select(MediaAsset).where(MediaAsset.movie_id == movie.id, MediaAsset.kind == "cover")
    )
    candidates = [folder / cover.filename] if cover else []
    candidates.extend(
        folder / f"{movie.distribution_product_id}-fanart.{ext}"
        for ext in ("jpg", "jpeg", "png", "webp")
    )
    for path in dict.fromkeys(candidates):
        if (
            path.is_symlink()
            or not path.resolve().is_relative_to(folder.resolve())
            or not path.is_file()
        ):
            continue
        try:
            with Image.open(path) as image:
                width, height = image.size
        except (OSError, ValueError):
            continue
        if cover is None:
            cover = MediaAsset(movie_id=movie.id, kind="cover", filename=path.name)
            session.add(cover)
        cover.filename = path.name
        cover.status, cover.error = "completed", None
        cover.downloaded_bytes = cover.total_bytes = path.stat().st_size
        cover.width, cover.height = width, height
        cover.updated_at = utc_now()
        return
    if cover and cover.status == "completed":
        # Retain the row/history, but stop presenting a deleted or unreadable cover.
        cover.status = "failed"
        cover.error = "Cover missing or unreadable; refresh metadata/cover to download it again"
        cover.updated_at = utc_now()
