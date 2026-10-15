"""Movie catalogue, search, watchlist, recently viewed and reviews."""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from ..models.constants import BookingStatus, MovieStatus
from ..utils.errors import AppError, bad_request, not_found
from ..utils.ids import serialize, to_oid
from ..utils.timeutils import utcnow
from .support_service import audit, get_policy

DEFAULT_POSTER_COLORS = ["#E50914", "#1F1F2E"]


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "movie"


def _date_to_dt(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=timezone.utc)


def _movie_doc(data: dict[str, Any]) -> dict[str, Any]:
    doc = dict(data)
    if isinstance(doc.get("release_date"), date) and not isinstance(doc["release_date"], datetime):
        doc["release_date"] = _date_to_dt(doc["release_date"])
    if "poster_colors" in doc and not doc["poster_colors"]:
        doc["poster_colors"] = DEFAULT_POSTER_COLORS
    return doc


def bookable_showtime_filter(db: Database) -> dict[str, Any]:
    cutoff = get_policy(db)["booking_cutoff_minutes"]
    return {"is_published": True, "start_time": {"$gt": utcnow() + timedelta(minutes=cutoff)}}


def movies_with_upcoming_shows(db: Database) -> list[Any]:
    return db.showtimes.distinct("movie_id", bookable_showtime_filter(db))


def present(movie: dict[str, Any]) -> dict[str, Any]:
    out = serialize(movie)
    out["status_label"] = MovieStatus.LABELS.get(movie.get("status"), movie.get("status"))
    out.setdefault("poster_colors", DEFAULT_POSTER_COLORS)
    return out


# ---------------------------------------------------------------- customer-facing
def list_movies(db: Database, *, q: str | None = None, genre: str | None = None, language: str | None = None,
                status: str | None = None, availability: str | None = None, page: int = 1, page_size: int = 12,
                include_unpublished: bool = False) -> tuple[list[dict[str, Any]], int]:
    query: dict[str, Any] = {}
    if not include_unpublished:
        query["is_published"] = True
        query["status"] = {"$ne": MovieStatus.ARCHIVED}
    if q:
        query["title"] = {"$regex": re.escape(q.strip()), "$options": "i"}
    if genre:
        query["genres"] = genre
    if language:
        query["languages"] = language
    if status:
        if status not in MovieStatus.ALL:
            raise bad_request("Unknown movie status filter")
        query["status"] = status if include_unpublished or status != MovieStatus.ARCHIVED else "__hidden__"
    upcoming_ids = set(movies_with_upcoming_shows(db))
    if availability == "with_shows":
        query["_id"] = {"$in": list(upcoming_ids)}
    elif availability == "no_shows":
        query["_id"] = {"$nin": list(upcoming_ids)}
    total = db.movies.count_documents(query)
    cursor = (
        db.movies.find(query)
        .sort([("status", DESCENDING), ("release_date", DESCENDING), ("title", ASCENDING)])
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    items = []
    for m in cursor:
        item = present(m)
        item["has_shows"] = m["_id"] in upcoming_ids
        items.append(item)
    return items, total


def filter_options(db: Database) -> dict[str, list[str]]:
    base = {"is_published": True, "status": {"$ne": MovieStatus.ARCHIVED}}
    return {
        "genres": sorted(g for g in db.movies.distinct("genres", base) if g),
        "languages": sorted(lang for lang in db.movies.distinct("languages", base) if lang),
    }


def get_movie(db: Database, movie_id: str, *, admin: bool = False, viewer: dict[str, Any] | None = None) -> dict[str, Any]:
    movie = db.movies.find_one({"_id": to_oid(movie_id, "Movie")})
    if not movie or (not admin and (not movie.get("is_published") or movie.get("status") == MovieStatus.ARCHIVED)):
        raise not_found("Movie")
    out = present(movie)
    out["has_shows"] = db.showtimes.count_documents({**bookable_showtime_filter(db), "movie_id": movie["_id"]}) > 0
    if viewer is not None:
        _record_view(db, viewer, movie["_id"])
        out["in_watchlist"] = movie["_id"] in (viewer.get("favourites") or [])
    return out


def _record_view(db: Database, user: dict[str, Any], movie_id: Any) -> None:
    recent = [m for m in (user.get("recently_viewed") or []) if m != movie_id]
    db.users.update_one({"_id": user["_id"]}, {"$set": {"recently_viewed": [movie_id, *recent][:10]}})


def movies_by_ids(db: Database, ids: list[Any]) -> list[dict[str, Any]]:
    if not ids:
        return []
    found = {m["_id"]: m for m in db.movies.find({"_id": {"$in": ids}, "is_published": True})}
    return [present(found[i]) for i in ids if i in found]


def set_watchlist(db: Database, user: dict[str, Any], movie_id: str, add: bool) -> list[str]:
    oid = to_oid(movie_id, "Movie")
    if add:
        if not db.movies.find_one({"_id": oid, "is_published": True}):
            raise not_found("Movie")
        db.users.update_one({"_id": user["_id"]}, {"$addToSet": {"favourites": oid}})
    else:
        db.users.update_one({"_id": user["_id"]}, {"$pull": {"favourites": oid}})
    fresh = db.users.find_one({"_id": user["_id"]}) or {}
    return [str(x) for x in fresh.get("favourites", [])]


# ---------------------------------------------------------------- reviews
def list_reviews(db: Database, movie_id: str, page: int, page_size: int) -> tuple[list[dict[str, Any]], int]:
    oid = to_oid(movie_id, "Movie")
    q = {"movie_id": oid}
    total = db.reviews.count_documents(q)
    items = db.reviews.find(q).sort("created_at", DESCENDING).skip((page - 1) * page_size).limit(page_size)
    return [serialize({k: v for k, v in r.items() if k != "user_id"}) for r in items], total


def can_review(db: Database, user: dict[str, Any], movie_oid: Any) -> bool:
    return (
        db.bookings.count_documents(
            {
                "user_id": user["_id"],
                "movie_snapshot.movie_id": movie_oid,
                "status": BookingStatus.CONFIRMED,
                "show_start": {"$lte": utcnow()},
            },
            limit=1,
        )
        > 0
    )


def upsert_review(db: Database, user: dict[str, Any], movie_id: str, rating: int, comment: str) -> dict[str, Any]:
    oid = to_oid(movie_id, "Movie")
    if not db.movies.find_one({"_id": oid}):
        raise not_found("Movie")
    if not can_review(db, user, oid):
        raise AppError(403, "You can review a movie after attending a confirmed show for it", "review_not_allowed")
    now = utcnow()
    db.reviews.update_one(
        {"movie_id": oid, "user_id": user["_id"]},
        {
            "$set": {"rating": rating, "comment": comment.strip(), "user_name": user["name"].split()[0], "updated_at": now},
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    _refresh_rating(db, oid)
    return serialize(db.reviews.find_one({"movie_id": oid, "user_id": user["_id"]}, {"user_id": 0}))


def _refresh_rating(db: Database, movie_oid: Any) -> None:
    ratings = [r["rating"] for r in db.reviews.find({"movie_id": movie_oid}, {"rating": 1})]
    avg, n = (round(sum(ratings) / len(ratings), 2), len(ratings)) if ratings else (None, 0)
    db.movies.update_one({"_id": movie_oid}, {"$set": {"avg_user_rating": avg, "review_count": n}})


# ---------------------------------------------------------------- admin
def create_movie(db: Database, actor: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    now = utcnow()
    doc = _movie_doc(data)
    base = slugify(f"{data['title']}-{data['release_date'].year}")
    doc.update({"avg_user_rating": None, "review_count": 0, "created_at": now, "updated_at": now})
    for i in range(50):
        doc["slug"] = base if i == 0 else f"{base}-{i + 1}"
        try:
            doc.pop("_id", None)
            db.movies.insert_one(doc)
            break
        except DuplicateKeyError:
            continue
    else:
        raise AppError(409, "Could not generate a unique slug for this movie", "conflict")
    audit(db, actor, "movie.create", "movie", doc["_id"], {"title": doc["title"]})
    return present(doc)


def update_movie(db: Database, actor: dict[str, Any], movie_id: str, data: dict[str, Any]) -> dict[str, Any]:
    oid = to_oid(movie_id, "Movie")
    changes = _movie_doc({k: v for k, v in data.items() if v is not None})
    if not db.movies.find_one({"_id": oid}):
        raise not_found("Movie")
    if changes:
        changes["updated_at"] = utcnow()
        db.movies.update_one({"_id": oid}, {"$set": changes})
        audit(db, actor, "movie.update", "movie", oid, {k: str(v) for k, v in changes.items() if k != "updated_at"})
    return present(db.movies.find_one({"_id": oid}))


def delete_movie(db: Database, actor: dict[str, Any], movie_id: str) -> dict[str, Any]:
    oid = to_oid(movie_id, "Movie")
    movie = db.movies.find_one({"_id": oid})
    if not movie:
        raise not_found("Movie")
    in_use = db.showtimes.count_documents({"movie_id": oid}, limit=1) or db.bookings.count_documents(
        {"movie_snapshot.movie_id": oid}, limit=1
    )
    if in_use:
        db.movies.update_one({"_id": oid}, {"$set": {"status": MovieStatus.ARCHIVED, "is_published": False,
                                                     "updated_at": utcnow()}})
        audit(db, actor, "movie.archive", "movie", oid, {"title": movie["title"]})
        return {"deleted": False, "archived": True,
                "message": "Movie has showtimes or bookings, so it was archived and unpublished instead of deleted."}
    db.movies.delete_one({"_id": oid})
    db.reviews.delete_many({"movie_id": oid})
    audit(db, actor, "movie.delete", "movie", oid, {"title": movie["title"]})
    return {"deleted": True, "archived": False, "message": "Movie deleted"}
