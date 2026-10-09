"""Library browsing, download controls and safe local media delivery."""

from pathlib import Path
from typing import Literal, get_args

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from jav_data.downloads import asset_path
from jav_data.models import Actress, MediaAsset, Movie, MovieActress, ProductFolder, ScrapeJob
from jav_data.movies import serialize
from jav_data.previews import cover_preview

router = APIRouter()

FIELD_LABELS = {
    "streaming_release_date": "Streaming Release Date",
    "product_release_date": "Product Release Date",
    "runtime": "Runtime",
    "actresses": "Actresses / Cast",
    "directors": "Directors",
    "series": "Series",
    "maker": "Maker",
    "label": "Label",
    "genres": "Genres",
    "related_tags": "Related Tags",
    "distribution_product_id": "Distribution Product ID",
    "manufacturer_product_id": "Manufacturer Product ID",
}

TagField = Literal["actresses", "directors", "series", "maker", "label", "genres", "related_tags"]
TAG_LABELS = {key: FIELD_LABELS[key] for key in get_args(TagField)}


def tag_match(field: TagField, value: str):
    """Compare one metadata value exactly, including individual JSON list entries."""
    if field == "actresses":
        return Movie.id.in_(
            select(MovieActress.movie_id).join(Actress).where(Actress.name == value)
        )
    column = getattr(Movie, field)
    if field in {"directors", "genres", "related_tags"}:
        entries = func.json_each(column).table_valued("value")
        return (
            select(1).select_from(entries).where(entries.c.value == value).correlate(Movie).exists()
        )
    return column == value


def media_info(asset):
    return {
        key: getattr(asset, key)
        for key in (
            "id",
            "movie_id",
            "kind",
            "filename",
            "status",
            "downloaded_bytes",
            "total_bytes",
            "width",
            "height",
            "attempts",
            "error",
        )
    }


@router.get("/api/library")
def browse(
    request: Request,
    q: str = "",
    filter_field: TagField | None = None,
    filter_value: str | None = None,
    page: int = Query(1, ge=1),
    sort: Literal[
        "newest",
        "title_asc",
        "title_desc",
        "release_date_asc",
        "release_date_desc",
        "product_id_asc",
        "product_id_desc",
        "actresses_asc",
        "actresses_desc",
        "maker_asc",
        "maker_desc",
    ] = "newest",
):
    if (filter_field is None) != (filter_value is None) or (
        filter_value is not None and not filter_value.strip()
    ):
        raise HTTPException(400, "Choose a metadata field and a non-empty value together")
    with Session(request.app.state.engine) as session:
        query = select(Movie)
        if filter_field is not None:
            query = query.where(tag_match(filter_field, filter_value))
        if q.strip():
            term = q.strip()
            query = query.where(
                or_(
                    Movie.title.contains(term, autoescape=True),
                    Movie.distribution_product_id.contains(term, autoescape=True),
                    Movie.manufacturer_product_id.contains(term, autoescape=True),
                    Movie.maker.contains(term, autoescape=True),
                    Movie.series.contains(term, autoescape=True),
                    Movie.id.in_(
                        select(MovieActress.movie_id)
                        .join(Actress)
                        .where(Actress.name.contains(term, autoescape=True))
                    ),
                )
            )
        total = session.scalar(select(func.count()).select_from(query.subquery()))
        if sort == "newest":
            ordering = [Movie.id.desc()]
        else:
            field, direction = sort.rsplit("_", 1)
            cast_names = (
                select(Actress.name.label("name"))
                .select_from(MovieActress)
                .join(Actress)
                .where(MovieActress.movie_id == Movie.id)
                .order_by(MovieActress.position)
                .correlate(Movie)
                .subquery()
            )
            cast = select(func.group_concat(cast_names.c.name, " · ")).scalar_subquery()
            release_date = func.date(func.replace(Movie.streaming_release_date, "/", "-"))
            value = {
                "title": Movie.title,
                "release_date": release_date,
                "product_id": Movie.distribution_product_id,
                "actresses": cast,
                "maker": Movie.maker,
            }[field]
            key = func.lower(func.coalesce(value, ""))
            ordering = [
                key == "",  # Missing values remain at the end in both directions.
                key.asc() if direction == "asc" else key.desc(),
                Movie.id.asc(),
            ]
        movies = session.scalars(query.order_by(*ordering).offset((page - 1) * 24).limit(24)).all()
        covers = {}
        if movies:
            for asset in session.scalars(
                select(MediaAsset)
                .where(
                    MediaAsset.movie_id.in_([movie.id for movie in movies]),
                    MediaAsset.kind == "cover",
                    MediaAsset.status == "completed",
                )
                .order_by(MediaAsset.id.desc())
            ):
                covers.setdefault(
                    asset.movie_id,
                    {
                        "id": asset.id,
                        "version": asset.updated_at.isoformat(),
                    },
                )
        return {
            "items": [
                dict(serialize(movie).model_dump(mode="json"), cover=covers.get(movie.id))
                for movie in movies
            ],
            "total": total,
            "page": page,
            "pages": max(1, (total + 23) // 24),
        }


@router.get("/api/media-assets")
def assets(
    request: Request,
    movie_id: int | None = None,
    limit: int = Query(200, ge=1, le=1000),
    history: bool = False,
):
    with Session(request.app.state.engine) as session:
        query = select(MediaAsset)
        if movie_id is not None:
            query = query.where(MediaAsset.movie_id == movie_id)
        if history:
            query = query.where(MediaAsset.history_hidden.is_(False))
        return [
            media_info(a)
            for a in session.scalars(query.order_by(MediaAsset.id.desc()).limit(limit))
        ]


@router.post("/api/download-history/clear")
def clear_download_history(request: Request):
    with Session(request.app.state.engine) as session:
        result = session.execute(
            update(MediaAsset)
            .where(
                MediaAsset.status.in_(["completed", "failed", "unavailable"]),
                MediaAsset.history_hidden.is_(False),
            )
            .values(history_hidden=True)
        )
        session.commit()
        return {"cleared": result.rowcount}


@router.get("/api/downloads")
def download_status(request: Request):
    return {"paused": request.app.state.downloader.paused, "backend": "built-in HTTP"}


@router.post("/api/downloads/{action}")
def download_action(action: str, request: Request):
    if action not in {"pause", "resume"}:
        raise HTTPException(404, "Unknown download action")
    request.app.state.downloader.paused = action == "pause"
    return {"paused": request.app.state.downloader.paused}


@router.post("/api/media-assets/{asset_id}/retry")
def retry_asset(asset_id: int, request: Request):
    with Session(request.app.state.engine) as session:
        asset = session.get(MediaAsset, asset_id)
        if asset is None:
            raise HTTPException(404, "Media not found")
        if asset.status in {"queued", "downloading"}:
            raise HTTPException(409, "Download is already active")
        if not asset.url:
            raise HTTPException(409, "Refresh product sources first")
        asset.status, asset.error, asset.history_hidden = "queued", None, False
        session.commit()
        return media_info(asset)


@router.post("/api/movies/{movie_id}/refresh-media")
def refresh_media(movie_id: int, request: Request):
    with Session(request.app.state.engine) as session:
        movie = session.get(Movie, movie_id)
        if movie is None:
            raise HTTPException(404, "Movie not found")
        if not movie.source_url:
            raise HTTPException(409, "Movie has no product URL")
        job = session.scalar(
            select(ScrapeJob).where(
                ScrapeJob.url == movie.source_url,
                ScrapeJob.status.in_(["queued", "running", "awaiting_session"]),
            )
        )
        if job is None:
            job = ScrapeJob(url=movie.source_url, product_folder_id=movie.product_folder_id)
            session.add(job)
        session.commit()
        return {"job_id": job.id, "status": job.status}


@router.get("/media/{asset_id}")
def serve_media(asset_id: int, request: Request, preview: bool = False):
    settings = request.app.state.settings
    with Session(request.app.state.engine) as session:
        result = session.execute(
            select(MediaAsset.filename, Movie.distribution_product_id, ProductFolder.path)
            .join(Movie, Movie.id == MediaAsset.movie_id)
            .outerjoin(ProductFolder, ProductFolder.id == Movie.product_folder_id)
            .where(
                MediaAsset.id == asset_id,
                MediaAsset.kind == "cover",
                MediaAsset.status == "completed",
            )
        ).first()
        if result is None:
            raise HTTPException(404, "Media is not downloaded")
        filename, product_id, folder = result
        root = Path(folder) if folder and folder != "@library" else settings.library_dir
        try:
            path = asset_path(settings, product_id, filename, root)
        except ValueError as error:
            raise HTTPException(404, "Invalid media path") from error
    if not path.is_file():
        raise HTTPException(404, "Media file is missing; retry its download")
    if preview:
        try:
            path = cover_preview(path, settings.data_dir, asset_id)
        except (OSError, ValueError) as error:
            raise HTTPException(422, "Cover preview could not be generated") from error
    return FileResponse(path)
