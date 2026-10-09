"""Library registry; one shared database keeps permanent movie locations."""

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from jav_data.library_sync import sync_libraries
from jav_data.models import MediaAsset, Movie, ProductFolder, ScrapeJob, utc_now

router = APIRouter(prefix="/api/product-folders", tags=["Storage"])


def folders(session, settings=None):
    result = []
    for folder in session.scalars(select(ProductFolder).order_by(ProductFolder.id)):
        root = settings.library_dir if folder.path == "@library" and settings else Path(folder.path)
        result.append({"id": folder.id, "path": str(root), "label": root.name or str(root)})
    return result


def register_folder(session, settings, path):
    root = Path(path).expanduser()
    if not root.is_absolute():
        raise ValueError("Use an absolute library path")
    root = root.resolve()
    data = settings.data_dir.resolve()
    if root.is_relative_to(data) or data.is_relative_to(root):
        raise ValueError("Libraries must be separate from the database folder")
    for folder in session.scalars(select(ProductFolder)):
        existing = settings.library_dir if folder.path == "@library" else Path(folder.path)
        if os.path.normcase(str(root)) == os.path.normcase(str(existing)):
            return folder
        if root.is_relative_to(existing) or existing.is_relative_to(root):
            raise ValueError("Libraries must not overlap one another")
    root.mkdir(parents=True, exist_ok=True)
    folder = ProductFolder(path="@library" if root == settings.library_dir.resolve() else str(root))
    session.add(folder)
    session.flush()
    return folder


def movie_root(settings, session, movie):
    folder = (
        session.get(ProductFolder, movie.product_folder_id) if movie.product_folder_id else None
    )
    return Path(folder.path) if folder and folder.path != "@library" else settings.library_dir


class FolderInput(BaseModel):
    path: str = Field(min_length=1)


@router.get("")
def list_folders(request: Request):
    with Session(request.app.state.engine) as session:
        return folders(session, request.app.state.settings)


@router.post("", status_code=201)
def add_folder(payload: FolderInput, request: Request):
    with request.app.state.library_lock.scan(), Session(request.app.state.engine) as session:
        try:
            library = register_folder(session, request.app.state.settings, payload.path.strip())
            session.commit()
            report = sync_libraries(
                session, request.app.state.settings, [library], remove_missing=False
            )
        except (ValueError, OSError) as error:
            session.rollback()
            raise HTTPException(400, str(error)) from error
        result = folders(session, request.app.state.settings)
        for item in result:
            if item["id"] == library.id:
                item["scan"] = report
        return result


@router.post("/refresh")
def refresh_libraries(request: Request):
    with request.app.state.library_lock.scan(), Session(request.app.state.engine) as session:
        return sync_libraries(
            session,
            request.app.state.settings,
            session.scalars(select(ProductFolder).order_by(ProductFolder.id)).all(),
        )


@router.post("/{folder_id}/remove")
def remove_folder(folder_id: int, request: Request):
    # Wait for active scraping/downloads, then prevent new writes during removal.
    with request.app.state.library_lock.scan(), Session(request.app.state.engine) as session:
        library = session.get(ProductFolder, folder_id)
        if library is None:
            raise HTTPException(404, "Library not found")
        movie_ids = select(Movie.id).where(Movie.product_folder_id == folder_id)
        session.execute(
            update(ScrapeJob).where(ScrapeJob.movie_id.in_(movie_ids)).values(movie_id=None)
        )
        session.execute(
            update(ScrapeJob)
            .where(
                ScrapeJob.product_folder_id == folder_id,
                ScrapeJob.status.in_(["queued", "running", "awaiting_session"]),
            )
            .values(
                status="failed",
                error="Library removed; add the URL again to a library",
                updated_at=utc_now(),
            )
        )
        session.execute(
            update(ScrapeJob)
            .where(ScrapeJob.product_folder_id == folder_id)
            .values(product_folder_id=None)
        )
        session.execute(delete(MediaAsset).where(MediaAsset.movie_id.in_(movie_ids)))
        removed = session.execute(
            delete(Movie).where(Movie.product_folder_id == folder_id)
        ).rowcount
        session.delete(library)
        session.commit()
        return {"folders": folders(session, request.app.state.settings), "removed": removed}
