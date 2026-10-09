"""Portable movie NFO export with original Japanese metadata preserved."""

import re
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
from datetime import date
from enum import StrEnum
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from jav_data.models import MediaAsset, Movie
from jav_data.storage import movie_root

router = APIRouter(prefix="/api", tags=["NFO export"])


class Profile(StrEnum):
    emby = "emby"


def normalized_date(value):
    if not value:
        return None
    text = unicodedata.normalize("NFKC", value)
    match = re.fullmatch(r"\s*(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})日?\s*", text)
    if match:
        try:
            return date(*map(int, match.groups())).isoformat()
        except ValueError:
            pass
    return None


def runtime_minutes(value):
    if not value:
        return None
    text = unicodedata.normalize("NFKC", value).strip()
    match = re.fullmatch(r"(\d+)\s*(?:分|min(?:utes)?)?", text, re.I)
    return int(match.group(1)) if match else None


def xml_text(value):
    text = str(value)
    if any(ord(c) < 32 and c not in "\t\n\r" for c in text):
        raise ValueError("Metadata contains invalid XML control characters")
    return text


def build_nfo(movie, assets, profile: Profile):
    root = ET.Element("movie")

    def add(name, value, parent=root, **attrs):
        if value is not None and value != "":
            ET.SubElement(parent, name, attrs).text = xml_text(value)

    add("title", movie.title)
    add("originaltitle", movie.title)
    add("plot", movie.video_intro)
    premiered = normalized_date(movie.product_release_date) or normalized_date(
        movie.streaming_release_date
    )
    add("premiered", premiered)
    add("releasedate", premiered)
    add("year", premiered[:4] if premiered else None)
    add("runtime", runtime_minutes(movie.runtime))
    add("studio", movie.maker)
    for director in movie.directors:
        add("director", director)
    for genre in movie.genres:
        add("genre", genre)
    for tag in movie.related_tags:
        add("tag", tag)
    if movie.series:
        add("set", movie.series)
    add("uniqueid", movie.distribution_product_id, type="dmm", default="true")
    add("uniqueid", movie.manufacturer_product_id, type="manufacturer")
    for order, link in enumerate(movie.cast):
        actor = ET.SubElement(root, "actor")
        add("name", link.actress.name, parent=actor)
        add("type", "Actor", parent=actor)
        add("sortorder", order, parent=actor)
    completed = [asset for asset in assets if asset.status == "completed"]
    image = next((a for a in completed if a.kind == "cover"), None)
    if image:
        add("thumb", image.filename.replace("\\", "/"), aspect="poster")
    # Unsupported source fields
    # are retained in an extension, while metadata.json remains the canonical record.
    original = ET.SubElement(root, "javdata", {"profile": profile.value})
    for field in (
        "streaming_release_date",
        "product_release_date",
        "runtime",
        "label",
        "series",
        "distribution_product_id",
        "manufacturer_product_id",
        "source_url",
    ):
        add(field, getattr(movie, field), parent=original)
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def export_bytes(session, settings, movie, profile):
    folder = movie_root(settings, session, movie) / movie.distribution_product_id
    assets = session.scalars(select(MediaAsset).where(MediaAsset.movie_id == movie.id)).all()
    assets = [a for a in assets if (folder / a.filename).is_file()]
    return build_nfo(movie, assets, profile)


def write_emby_nfo(session, settings, movie):
    """Atomically refresh the Emby file after metadata or artwork changes."""
    folder = movie_root(settings, session, movie) / movie.distribution_product_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "movie.nfo"
    content = export_bytes(session, settings, movie, Profile.emby)
    with tempfile.NamedTemporaryFile(dir=folder, suffix=".nfo.tmp", delete=False) as output:
        temporary = Path(output.name)
        output.write(content)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


@router.get("/movies/{movie_id}/nfo")
def download_nfo(movie_id: int, request: Request, profile: Profile = Profile.emby):
    with Session(request.app.state.engine) as session:
        movie = session.get(Movie, movie_id)
        if movie is None:
            raise HTTPException(404, "Movie not found")
        try:
            content = export_bytes(session, request.app.state.settings, movie, profile)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        return Response(
            content,
            media_type="application/xml",
            headers={"Content-Disposition": 'attachment; filename="movie.nfo"'},
        )


class ExportBatch(BaseModel):
    movie_ids: list[int] = Field(min_length=1, max_length=1000)
    profile: Profile = Profile.emby
    overwrite: bool = False


@router.post("/nfo/export")
def export_batch(payload: ExportBatch, request: Request):
    results = []
    with Session(request.app.state.engine) as session:
        for movie_id in dict.fromkeys(payload.movie_ids):
            movie = session.get(Movie, movie_id)
            if movie is None:
                results.append(
                    {"movie_id": movie_id, "status": "failed", "error": "Movie not found"}
                )
                continue
            folder = (
                movie_root(request.app.state.settings, session, movie)
                / movie.distribution_product_id
            )
            path = folder / "movie.nfo"
            if path.exists() and not payload.overwrite:
                results.append({"movie_id": movie_id, "status": "skipped", "path": str(path)})
                continue
            try:
                content = export_bytes(session, request.app.state.settings, movie, payload.profile)
                folder.mkdir(parents=True, exist_ok=True)
                if payload.overwrite:
                    temporary = path.with_suffix(".nfo.tmp")
                    temporary.write_bytes(content)
                    temporary.replace(path)
                else:
                    with path.open("xb") as output:
                        output.write(content)
                results.append({"movie_id": movie_id, "status": "exported", "path": str(path)})
            except (OSError, ValueError) as error:
                results.append({"movie_id": movie_id, "status": "failed", "error": str(error)})
    return {"results": results}
