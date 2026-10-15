"""Schemas for movies, cinemas, screens and showtimes."""
from __future__ import annotations

import re
from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from ..models.constants import CERTIFICATES, SCREEN_TYPES, SEAT_CATEGORIES, MovieStatus
from .common import Flexible

ROW_RE = re.compile(r"^[A-Z]{1,2}$")
SEAT_RE = re.compile(r"^[A-Z]{1,2}[0-9]{1,2}$")
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _clean_list(values: list[str]) -> list[str]:
    seen, out = set(), []
    for v in values:
        v = " ".join(str(v).split())
        if v and v.lower() not in seen:
            seen.add(v.lower())
            out.append(v)
    return out


class MovieIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    genres: list[str] = Field(min_length=1, max_length=8)
    languages: list[str] = Field(min_length=1, max_length=8)
    duration_minutes: int = Field(ge=30, le=400)
    certificate: str = "UA"
    release_date: date
    status: str = MovieStatus.NOW_SHOWING
    rating: float | None = Field(default=None, ge=0, le=10, description="Critic rating out of 10")
    poster_url: str | None = Field(default=None, max_length=500)
    poster_colors: list[str] = Field(default_factory=list, max_length=3)
    cast: list[str] = Field(default_factory=list, max_length=12)
    director: str | None = Field(default=None, max_length=80)
    is_published: bool = False

    @field_validator("genres", "languages", "cast")
    @classmethod
    def _lists(cls, v: list[str]) -> list[str]:
        return _clean_list(v)

    @field_validator("certificate")
    @classmethod
    def _cert(cls, v: str) -> str:
        if v not in CERTIFICATES:
            raise ValueError(f"Certificate must be one of {', '.join(CERTIFICATES)}")
        return v

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        if v not in MovieStatus.ALL:
            raise ValueError(f"Status must be one of {', '.join(MovieStatus.ALL)}")
        return v

    @field_validator("poster_url")
    @classmethod
    def _poster(cls, v: str | None) -> str | None:
        if not v:
            return None
        if not v.startswith(("http://", "https://")):
            raise ValueError("Poster URL must start with http:// or https://")
        return v

    @field_validator("poster_colors")
    @classmethod
    def _colors(cls, v: list[str]) -> list[str]:
        for c in v:
            if not HEX_RE.match(c):
                raise ValueError("Poster colours must be hex values like #E50914")
        return v


class MovieUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    genres: list[str] | None = Field(default=None, min_length=1, max_length=8)
    languages: list[str] | None = Field(default=None, min_length=1, max_length=8)
    duration_minutes: int | None = Field(default=None, ge=30, le=400)
    certificate: str | None = None
    release_date: date | None = None
    status: str | None = None
    rating: float | None = Field(default=None, ge=0, le=10)
    poster_url: str | None = Field(default=None, max_length=500)
    poster_colors: list[str] | None = None
    cast: list[str] | None = None
    director: str | None = Field(default=None, max_length=80)
    is_published: bool | None = None

    @field_validator("genres", "languages", "cast")
    @classmethod
    def _lists(cls, v: list[str] | None) -> list[str] | None:
        return _clean_list(v) if v is not None else v

    @field_validator("certificate")
    @classmethod
    def _cert(cls, v: str | None) -> str | None:
        if v is not None and v not in CERTIFICATES:
            raise ValueError(f"Certificate must be one of {', '.join(CERTIFICATES)}")
        return v

    @field_validator("status")
    @classmethod
    def _status(cls, v: str | None) -> str | None:
        if v is not None and v not in MovieStatus.ALL:
            raise ValueError(f"Status must be one of {', '.join(MovieStatus.ALL)}")
        return v

    @field_validator("poster_url")
    @classmethod
    def _poster(cls, v: str | None) -> str | None:
        if v and not v.startswith(("http://", "https://")):
            raise ValueError("Poster URL must start with http:// or https://")
        return v


class MovieOut(Flexible):
    id: str
    title: str
    slug: str
    genres: list[str]
    languages: list[str]
    duration_minutes: int
    status: str
    is_published: bool


class CinemaIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    code: str = Field(min_length=2, max_length=12, pattern="^[A-Z0-9-]+$")
    city: str = Field(min_length=2, max_length=60)
    address: str = Field(default="", max_length=200)
    amenities: list[str] = Field(default_factory=list, max_length=12)
    is_active: bool = True


class CinemaUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    city: str | None = Field(default=None, min_length=2, max_length=60)
    address: str | None = Field(default=None, max_length=200)
    amenities: list[str] | None = None
    is_active: bool | None = None


class LayoutRowIn(BaseModel):
    row: str
    seats: int = Field(ge=1, le=40)
    category: str = "regular"

    @field_validator("row")
    @classmethod
    def _row(cls, v: str) -> str:
        v = v.strip().upper()
        if not ROW_RE.match(v):
            raise ValueError("Row labels must be 1-2 letters (A, B, ... AA)")
        return v

    @field_validator("category")
    @classmethod
    def _cat(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in SEAT_CATEGORIES:
            raise ValueError(f"Seat category must be one of {', '.join(SEAT_CATEGORIES)}")
        return v


class LayoutIn(BaseModel):
    rows: list[LayoutRowIn] = Field(min_length=1, max_length=30)
    aisles_after: list[int] = Field(default_factory=list, description="Seat numbers after which an aisle gap is drawn")
    blocked_seats: list[str] = Field(default_factory=list, description="Seats that can never be sold, e.g. A1")

    @model_validator(mode="after")
    def _check(self) -> "LayoutIn":
        labels = [r.row for r in self.rows]
        if len(set(labels)) != len(labels):
            raise ValueError("Each row label must be unique")
        valid = {f"{r.row}{n}" for r in self.rows for n in range(1, r.seats + 1)}
        self.blocked_seats = sorted({s.strip().upper() for s in self.blocked_seats if s.strip()})
        bad = [s for s in self.blocked_seats if s not in valid]
        if bad:
            raise ValueError(f"Blocked seats not in layout: {', '.join(bad)}")
        self.aisles_after = sorted({a for a in self.aisles_after if a > 0})
        return self


class PricesIn(BaseModel):
    regular: float = Field(ge=0, le=10000)
    premium: float = Field(ge=0, le=10000)
    recliner: float = Field(ge=0, le=10000)


class ScreenIn(BaseModel):
    cinema_id: str
    name: str = Field(min_length=1, max_length=40)
    screen_type: str = "2D"
    layout: LayoutIn
    default_prices: PricesIn | None = None

    @field_validator("screen_type")
    @classmethod
    def _type(cls, v: str) -> str:
        if v not in SCREEN_TYPES:
            raise ValueError(f"Screen type must be one of {', '.join(SCREEN_TYPES)}")
        return v


class ScreenUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=40)
    screen_type: str | None = None
    layout: LayoutIn | None = None
    default_prices: PricesIn | None = None
    is_active: bool | None = None


class ShowtimeIn(BaseModel):
    movie_id: str
    screen_id: str
    start_time: datetime = Field(description="Local cinema time (APP_TIMEZONE) unless an offset is included")
    language: str = Field(min_length=1, max_length=30)
    format: str = Field(default="2D", max_length=20)
    prices: PricesIn | None = None
    is_published: bool = True


class ShowtimeBulkIn(BaseModel):
    movie_id: str
    screen_id: str
    dates: list[date] = Field(min_length=1, max_length=31)
    times: list[str] = Field(min_length=1, max_length=8, description="24h times, e.g. 10:30")
    language: str = Field(min_length=1, max_length=30)
    format: str = Field(default="2D", max_length=20)
    prices: PricesIn | None = None
    is_published: bool = True

    @field_validator("times")
    @classmethod
    def _times(cls, v: list[str]) -> list[str]:
        for t in v:
            if not re.match(r"^([01]?\d|2[0-3]):[0-5]\d$", t.strip()):
                raise ValueError(f"Invalid time '{t}'. Use HH:MM in 24-hour format")
        return [t.strip() for t in v]


class ShowtimeUpdateIn(BaseModel):
    prices: PricesIn | None = None
    is_published: bool | None = None
    language: str | None = None
    format: str | None = None


class ReviewIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=600)


SEAT_ID_PATTERN = SEAT_RE
