"""English field names; original Japanese values are never translated."""

import re
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class MovieInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    distribution_product_id: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1)
    manufacturer_product_id: str | None = None
    streaming_release_date: str | None = None
    product_release_date: str | None = None
    runtime: str | None = None
    actresses: list[str] = Field(default_factory=list)
    directors: list[str] = Field(default_factory=list)
    series: str | None = None
    maker: str | None = None
    label: str | None = None
    genres: list[str] = Field(default_factory=list)
    related_tags: list[str] = Field(default_factory=list)
    video_intro: str | None = None
    source_url: HttpUrl | None = None
    scraped_at: datetime | None = None

    @field_validator("distribution_product_id")
    @classmethod
    def safe_product_id(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value) or value.endswith("."):
            raise ValueError("Product ID must be a Windows-safe identifier")
        stem = value.split(".", 1)[0].upper()
        reserved = {"CON", "PRN", "AUX", "NUL"}
        reserved.update(f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10))
        if stem in reserved:
            raise ValueError("Product ID is a reserved Windows filename")
        return value

    @field_validator("title")
    @classmethod
    def nonblank_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Title cannot be blank")
        return value

    @field_validator("actresses", "directors", "genres", "related_tags")
    @classmethod
    def ordered_unique_values(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("List entries cannot be blank")
        return list(dict.fromkeys(values))

    @field_validator("scraped_at")
    @classmethod
    def utc_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            if value.tzinfo is None:
                raise ValueError("Scraped timestamp must include a timezone")
            return value.astimezone(timezone.utc)
        return value


class ActressOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str


class MovieOutput(MovieInput):
    id: int
    created_at: datetime
    updated_at: datetime
    cast: list[ActressOutput]
    product_folder_id: int | None
