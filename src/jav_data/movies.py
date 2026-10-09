"""Transactional movie storage and a small API for module 2 verification."""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from jav_data.models import Actress, Movie, MovieActress, ProductFolder, utc_now
from jav_data.schemas import ActressOutput, MovieInput, MovieOutput

router = APIRouter(prefix="/api", tags=["Metadata"])


def as_utc(value: datetime | None) -> datetime | None:
    # SQLite does not retain timezone information for datetime columns.
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def serialize(movie: Movie) -> MovieOutput:
    values = {key: getattr(movie, key) for key in MovieInput.model_fields if key != "actresses"}
    values["scraped_at"] = as_utc(movie.scraped_at)
    return MovieOutput(
        **values,
        actresses=[link.actress.name for link in movie.cast],
        cast=[ActressOutput.model_validate(link.actress) for link in movie.cast],
        id=movie.id,
        product_folder_id=movie.product_folder_id,
        created_at=as_utc(movie.created_at),
        updated_at=as_utc(movie.updated_at),
    )


def write_movie(session: Session, movie: Movie, payload: MovieInput) -> None:
    existing = session.scalar(
        select(Movie).where(
            func.lower(Movie.distribution_product_id) == payload.distribution_product_id.lower()
        )
    )
    if existing is not None and existing.id != movie.id:
        raise HTTPException(409, "Distribution product ID already exists")
    values = payload.model_dump(mode="python", exclude={"actresses"})
    values["source_url"] = str(payload.source_url) if payload.source_url else None
    for key, value in values.items():
        setattr(movie, key, value)
    movie.updated_at = utc_now()
    if movie.product_folder_id is None:
        movie.product_folder_id = session.scalar(
            select(ProductFolder.id).order_by(ProductFolder.id)
        )
        if movie.product_folder_id is None:
            raise HTTPException(400, "Add a library folder in Database & Library first")
    session.add(movie)
    movie.cast.clear()
    session.flush()
    for position, name in enumerate(payload.actresses):
        actress = session.scalar(select(Actress).where(Actress.name == name))
        if actress is None:
            actress = Actress(name=name)
            session.add(actress)
            session.flush()
        movie.cast.append(MovieActress(actress=actress, position=position))
    session.commit()


def save(session: Session, movie: Movie, payload: MovieInput) -> MovieOutput:
    try:
        write_movie(session, movie, payload)
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(409, "Metadata conflicts with an existing record; retry") from error
    return serialize(movie)


@router.post("/movies", response_model=MovieOutput, status_code=201)
def create_movie(payload: MovieInput, request: Request):
    with Session(request.app.state.engine) as session:
        return save(session, Movie(), payload)


@router.get("/movies", response_model=list[MovieOutput])
def list_movies(
    request: Request, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)
):
    with Session(request.app.state.engine) as session:
        movies = session.scalars(select(Movie).order_by(Movie.id).offset(offset).limit(limit)).all()
        return [serialize(movie) for movie in movies]


@router.get("/movies/{movie_id}", response_model=MovieOutput)
def get_movie(movie_id: int, request: Request):
    with Session(request.app.state.engine) as session:
        movie = session.get(Movie, movie_id)
        if movie is None:
            raise HTTPException(404, "Movie not found")
        return serialize(movie)


@router.put("/movies/{movie_id}", response_model=MovieOutput)
def replace_movie(movie_id: int, payload: MovieInput, request: Request):
    """Replace all metadata. Omitted optional fields become empty."""
    with Session(request.app.state.engine) as session:
        movie = session.get(Movie, movie_id)
        if movie is None:
            raise HTTPException(404, "Movie not found")
        return save(session, movie, payload)


@router.get("/actresses", response_model=list[ActressOutput])
def list_actresses(
    request: Request, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)
):
    with Session(request.app.state.engine) as session:
        query = select(Actress).order_by(Actress.id).offset(offset).limit(limit)
        return session.scalars(query).all()
