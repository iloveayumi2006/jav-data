"""Japanese metadata and ordered cast relationships."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jav_data.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ProductFolder(Base):
    __tablename__ = "product_folders"

    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(Text, unique=True)


class Movie(Base):
    __tablename__ = "movies"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_folder_id: Mapped[int | None] = mapped_column(ForeignKey("product_folders.id"))
    distribution_product_id: Mapped[str] = mapped_column(
        String(120, collation="NOCASE"), unique=True
    )
    title: Mapped[str] = mapped_column(Text)
    manufacturer_product_id: Mapped[str | None] = mapped_column(Text)
    streaming_release_date: Mapped[str | None] = mapped_column(Text)
    product_release_date: Mapped[str | None] = mapped_column(Text)
    runtime: Mapped[str | None] = mapped_column(Text)
    directors: Mapped[list[str]] = mapped_column(JSON, default=list)
    series: Mapped[str | None] = mapped_column(Text)
    maker: Mapped[str | None] = mapped_column(Text)
    label: Mapped[str | None] = mapped_column(Text)
    genres: Mapped[list[str]] = mapped_column(JSON, default=list)
    related_tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    video_intro: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    scraped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    cast: Mapped[list[MovieActress]] = relationship(
        cascade="all, delete-orphan", order_by="MovieActress.position", lazy="selectin"
    )


class Actress(Base):
    __tablename__ = "actresses"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)


class MovieActress(Base):
    __tablename__ = "movie_actresses"

    movie_id: Mapped[int] = mapped_column(
        ForeignKey("movies.id", ondelete="CASCADE"), primary_key=True
    )
    actress_id: Mapped[int] = mapped_column(ForeignKey("actresses.id"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer)
    actress: Mapped[Actress] = relationship(lazy="joined")


class ScrapeJob(Base):
    __tablename__ = "scrape_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_folder_id: Mapped[int | None] = mapped_column(ForeignKey("product_folders.id"))
    url: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    movie_id: Mapped[int | None] = mapped_column(ForeignKey("movies.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class MediaAsset(Base):
    __tablename__ = "media_assets"
    __table_args__ = (UniqueConstraint("movie_id", "filename"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    movie_id: Mapped[int] = mapped_column(ForeignKey("movies.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    filename: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    referer: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    downloaded_bytes: Mapped[int] = mapped_column(Integer, default=0)
    total_bytes: Mapped[int | None] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    history_hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
