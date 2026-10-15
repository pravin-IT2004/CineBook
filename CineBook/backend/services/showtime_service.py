"""Showtime scheduling and listing."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from pymongo import ASCENDING
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from ..models.constants import BookingStatus, LockState, MovieStatus
from ..utils.errors import AppError, bad_request, conflict, not_found
from ..utils.ids import serialize, to_oid
from ..utils.timeutils import as_utc, local_day_bounds_utc, local_to_utc, to_local, utcnow
from .cinema_service import get_screen, layout_capacity
from .support_service import audit, get_policy


def taken_seat_count(db: Database, showtime_oid: Any) -> int:
    now = utcnow()
    return db.seat_locks.count_documents(
        {"showtime_id": showtime_oid, "$or": [{"state": LockState.BOOKED}, {"expires_at": {"$gt": now}}]}
    )


def booked_seat_count(db: Database, showtime_oid: Any) -> int:
    return db.seat_locks.count_documents({"showtime_id": showtime_oid, "state": LockState.BOOKED})


def present(db: Database, st: dict[str, Any], *, movie: dict | None = None, screen: dict | None = None,
            cinema: dict | None = None, include_layout: bool = False) -> dict[str, Any]:
    out = serialize({k: v for k, v in st.items() if include_layout or k != "layout"})
    taken = taken_seat_count(db, st["_id"])
    out["seats_available"] = max(0, st["capacity"] - taken)
    out["seats_booked"] = booked_seat_count(db, st["_id"])
    out["occupancy_percent"] = round(out["seats_booked"] / st["capacity"] * 100, 1) if st["capacity"] else 0
    local = to_local(st["start_time"])
    out["local_date"] = local.date().isoformat()
    out["local_time"] = local.strftime("%I:%M %p").lstrip("0")
    if movie:
        out["movie_title"] = movie["title"]
        out["movie_duration"] = movie["duration_minutes"]
    if screen:
        out["screen_name"] = screen["name"]
        out["screen_type"] = screen.get("screen_type")
    if cinema:
        out["cinema_name"] = cinema["name"]
        out["cinema_city"] = cinema.get("city")
    return out


def _lookup_maps(db: Database, shows: list[dict[str, Any]]):
    movies = {m["_id"]: m for m in db.movies.find({"_id": {"$in": list({s["movie_id"] for s in shows})}})}
    screens = {s["_id"]: s for s in db.screens.find({"_id": {"$in": list({s["screen_id"] for s in shows})}})}
    cinemas = {c["_id"]: c for c in db.cinemas.find({"_id": {"$in": list({s["cinema_id"] for s in shows})}})}
    return movies, screens, cinemas


def get_bookable_showtime(db: Database, showtime_id: Any) -> dict[str, Any]:
    st = db.showtimes.find_one({"_id": to_oid(showtime_id, "Showtime")})
    if not st or not st.get("is_published"):
        raise not_found("Showtime")
    movie = db.movies.find_one({"_id": st["movie_id"]})
    cinema = db.cinemas.find_one({"_id": st["cinema_id"]})
    if not movie or not movie.get("is_published") or movie.get("status") == MovieStatus.ARCHIVED:
        raise not_found("Showtime")
    if not cinema or not cinema.get("is_active", True):
        raise AppError(409, "This cinema is not accepting bookings right now", "cinema_inactive")
    cutoff = get_policy(db)["booking_cutoff_minutes"]
    if as_utc(st["start_time"]) <= utcnow() + timedelta(minutes=cutoff):
        raise AppError(409, f"Online booking for this show closed {cutoff} minutes before the start time",
                       "booking_closed")
    return st


def get_showtime_details(db: Database, showtime_id: str, *, admin: bool = False) -> dict[str, Any]:
    st = db.showtimes.find_one({"_id": to_oid(showtime_id, "Showtime")}) if admin else get_bookable_showtime(db, showtime_id)
    if not st:
        raise not_found("Showtime")
    movie = db.movies.find_one({"_id": st["movie_id"]})
    screen = db.screens.find_one({"_id": st["screen_id"]})
    cinema = db.cinemas.find_one({"_id": st["cinema_id"]})
    out = present(db, st, movie=movie, screen=screen or {"name": "?"}, cinema=cinema or {"name": "?"})
    if cinema:
        out["cinema_address"] = cinema.get("address")
    if movie:
        out["movie"] = {"id": str(movie["_id"]), "title": movie["title"], "certificate": movie.get("certificate"),
                        "duration_minutes": movie["duration_minutes"], "poster_url": movie.get("poster_url"),
                        "poster_colors": movie.get("poster_colors"), "genres": movie.get("genres", [])}
    return out


def list_for_movie(db: Database, movie_id: str, *, day: date | None = None, cinema_id: str | None = None) -> dict[str, Any]:
    movie = db.movies.find_one({"_id": to_oid(movie_id, "Movie")})
    if not movie or not movie.get("is_published") or movie.get("status") == MovieStatus.ARCHIVED:
        raise not_found("Movie")
    cutoff = get_policy(db)["booking_cutoff_minutes"]
    base: dict[str, Any] = {
        "movie_id": movie["_id"],
        "is_published": True,
        "start_time": {"$gt": utcnow() + timedelta(minutes=cutoff)},
    }
    active_cinemas = {c["_id"]: c for c in db.cinemas.find({"is_active": True})}
    base["cinema_id"] = {"$in": list(active_cinemas)}
    if cinema_id:
        cid = to_oid(cinema_id, "Cinema")
        base["cinema_id"] = cid if cid in active_cinemas else None
    all_shows = list(db.showtimes.find(base).sort("start_time", ASCENDING))
    dates = sorted({to_local(s["start_time"]).date().isoformat() for s in all_shows})
    if day is None and dates:
        day = date.fromisoformat(dates[0])
    shows = all_shows
    if day:
        lo, hi = local_day_bounds_utc(day)
        shows = [s for s in all_shows if lo <= as_utc(s["start_time"]) <= hi]
    _, screens, _ = _lookup_maps(db, shows) if shows else ({}, {}, {})
    grouped: dict[Any, dict[str, Any]] = {}
    for s in shows:
        c = active_cinemas[s["cinema_id"]]
        g = grouped.setdefault(c["_id"], {"cinema": serialize({k: c.get(k) for k in ("_id", "name", "city", "address",
                                                                                      "amenities", "code")}),
                                          "shows": []})
        g["shows"].append(present(db, s, screen=screens.get(s["screen_id"], {"name": "?"})))
    return {
        "movie_id": str(movie["_id"]),
        "dates": dates,
        "selected_date": day.isoformat() if day else None,
        "cinemas": sorted(grouped.values(), key=lambda g: g["cinema"]["name"]),
    }


# ---------------------------------------------------------------- admin
def _build_doc(db: Database, data: dict[str, Any], start_utc: datetime) -> dict[str, Any]:
    movie = db.movies.find_one({"_id": to_oid(data["movie_id"], "Movie")})
    if not movie:
        raise not_found("Movie")
    if movie.get("status") == MovieStatus.ARCHIVED:
        raise bad_request("Archived movies cannot be scheduled", "movie_archived")
    screen = get_screen(db, data["screen_id"])
    if not screen.get("is_active", True):
        raise bad_request("This screen is inactive", "screen_inactive")
    if data["language"] not in movie.get("languages", []):
        raise bad_request(f"Language must be one of the movie's languages: {', '.join(movie['languages'])}",
                          "invalid_language")
    if start_utc <= utcnow():
        raise bad_request("Showtimes must be scheduled in the future", "past_showtime")
    policy = get_policy(db)
    end_utc = start_utc + timedelta(minutes=movie["duration_minutes"])
    buffer = timedelta(minutes=policy["cleaning_buffer_minutes"])
    clash = db.showtimes.find_one(
        {"screen_id": screen["_id"], "start_time": {"$lt": end_utc + buffer}, "end_time": {"$gt": start_utc - buffer}}
    )
    if clash:
        when = to_local(clash["start_time"]).strftime("%d %b %I:%M %p")
        raise conflict(f"Screen '{screen['name']}' already has a show at {when} that overlaps this time "
                       f"(including a {policy['cleaning_buffer_minutes']}-minute cleaning buffer)", "showtime_overlap")
    now = utcnow()
    return {
        "movie_id": movie["_id"],
        "cinema_id": screen["cinema_id"],
        "screen_id": screen["_id"],
        "start_time": start_utc,
        "end_time": end_utc,
        "language": data["language"],
        "format": data.get("format") or screen.get("screen_type", "2D"),
        "prices": data.get("prices") or screen.get("default_prices") or policy["default_prices"],
        "layout": screen["layout"],  # snapshot: later layout edits never affect sold seats
        "capacity": layout_capacity(screen["layout"]),
        "is_published": data.get("is_published", True),
        "created_at": now,
        "updated_at": now,
    }


def create_showtime(db: Database, actor: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    doc = _build_doc(db, data, local_to_utc(data["start_time"]))
    try:
        db.showtimes.insert_one(doc)
    except DuplicateKeyError:
        raise conflict("A show already starts at this time on this screen", "showtime_overlap") from None
    audit(db, actor, "showtime.create", "showtime", doc["_id"], {"start": str(doc["start_time"])})
    return get_showtime_details(db, str(doc["_id"]), admin=True)


def bulk_create(db: Database, actor: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    created, skipped = [], []
    for d in data["dates"]:
        for t in data["times"]:
            hh, mm = (int(x) for x in t.split(":"))
            local_dt = datetime(d.year, d.month, d.day, hh, mm)
            try:
                doc = _build_doc(db, data, local_to_utc(local_dt))
                db.showtimes.insert_one(doc)
                created.append(str(doc["_id"]))
            except AppError as exc:
                skipped.append({"when": local_dt.strftime("%Y-%m-%d %H:%M"), "reason": exc.detail})
            except DuplicateKeyError:
                skipped.append({"when": local_dt.strftime("%Y-%m-%d %H:%M"), "reason": "Duplicate start time"})
    audit(db, actor, "showtime.bulk_create", "showtime", None, {"created": len(created), "skipped": len(skipped)})
    return {"created": len(created), "created_ids": created, "skipped": skipped}


def admin_list(db: Database, *, movie_id: str | None, cinema_id: str | None, date_from: date | None,
               date_to: date | None, upcoming_only: bool, page: int, page_size: int) -> tuple[list[dict], int]:
    q: dict[str, Any] = {}
    if movie_id:
        q["movie_id"] = to_oid(movie_id, "Movie")
    if cinema_id:
        q["cinema_id"] = to_oid(cinema_id, "Cinema")
    rng: dict[str, Any] = {}
    if date_from:
        rng["$gte"] = local_day_bounds_utc(date_from)[0]
    if date_to:
        rng["$lte"] = local_day_bounds_utc(date_to)[1]
    if upcoming_only:
        rng["$gte"] = max(rng.get("$gte", utcnow()), utcnow())
    if rng:
        q["start_time"] = rng
    total = db.showtimes.count_documents(q)
    shows = list(db.showtimes.find(q).sort("start_time", ASCENDING).skip((page - 1) * page_size).limit(page_size))
    movies, screens, cinemas = _lookup_maps(db, shows) if shows else ({}, {}, {})
    items = [present(db, s, movie=movies.get(s["movie_id"]), screen=screens.get(s["screen_id"]),
                     cinema=cinemas.get(s["cinema_id"])) for s in shows]
    return items, total


def update_showtime(db: Database, actor: dict[str, Any], showtime_id: str, data: dict[str, Any]) -> dict[str, Any]:
    oid = to_oid(showtime_id, "Showtime")
    st = db.showtimes.find_one({"_id": oid})
    if not st:
        raise not_found("Showtime")
    changes = {k: v for k, v in data.items() if v is not None}
    if "language" in changes:
        movie = db.movies.find_one({"_id": st["movie_id"]}) or {}
        if changes["language"] not in movie.get("languages", []):
            raise bad_request("Language must be one of the movie's languages", "invalid_language")
    if changes:
        changes["updated_at"] = utcnow()
        db.showtimes.update_one({"_id": oid}, {"$set": changes})
        audit(db, actor, "showtime.update", "showtime", oid, {k: str(v) for k, v in changes.items()})
    return get_showtime_details(db, showtime_id, admin=True)


def delete_showtime(db: Database, actor: dict[str, Any], showtime_id: str) -> None:
    oid = to_oid(showtime_id, "Showtime")
    if not db.showtimes.find_one({"_id": oid}):
        raise not_found("Showtime")
    if db.bookings.count_documents({"showtime_id": oid, "status": {"$in": [BookingStatus.CONFIRMED,
                                                                          BookingStatus.PENDING]}}, limit=1):
        raise conflict("This showtime has active bookings. Unpublish it instead, or cancel the bookings first.",
                       "has_bookings")
    db.seat_locks.delete_many({"showtime_id": oid})
    db.seat_holds.delete_many({"showtime_id": oid})
    db.showtimes.delete_one({"_id": oid})
    audit(db, actor, "showtime.delete", "showtime", oid)
