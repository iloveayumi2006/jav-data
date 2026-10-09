"""Convert an existing library to the cover naming used by Emby export."""

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from jav_data.models import MediaAsset, Movie
from jav_data.nfo import write_emby_nfo
from jav_data.storage import movie_root


def convert_library(settings, engine):
    results = []
    with Session(engine) as session:
        for movie in session.scalars(select(Movie).order_by(Movie.id)):
            renamed = 0
            try:
                folder = movie_root(settings, session, movie) / movie.distribution_product_id
                for asset in session.scalars(
                    select(MediaAsset).where(
                        MediaAsset.movie_id == movie.id, MediaAsset.kind == "cover"
                    )
                ):
                    old = folder / asset.filename
                    suffix = Path(asset.filename).suffix.lower()
                    target = f"{movie.distribution_product_id}-fanart{suffix}"
                    new = folder / target
                    if old.name != target:
                        if old.exists():
                            if new.exists():
                                raise ValueError(f"Destination already exists: {new}")
                            old.rename(new)
                            renamed += 1
                        asset.filename = target
                session.commit()
                path = write_emby_nfo(session, settings, movie)
                results.append({"id": movie.id, "renamed": renamed, "nfo": str(path)})
            except (OSError, ValueError) as error:
                session.rollback()
                results.append({"id": movie.id, "error": str(error)})
    return results
