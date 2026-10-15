"""Admin analytics computed from live MongoDB data."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from pymongo.database import Database

from ..models.constants import BookingStatus, LockState, Role
from ..utils.ids import to_oid
from ..utils.timeutils import local_day_bounds_utc, to_local, utcnow


def _r(x: float | None) -> float:
    return round(float(x or 0), 2)


def dashboard(db: Database, *, date_from: date | None = None, date_to: date | None = None,
              movie_id: str | None = None, cinema_id: str | None = None, status: str | None = None) -> dict[str, Any]:
    match: dict[str, Any] = {"status": {"$in": [BookingStatus.CONFIRMED, BookingStatus.CANCELLED,
                                                BookingStatus.PENDING, BookingStatus.FAILED]}}
    rng: dict[str, Any] = {}
    if date_from:
        rng["$gte"] = local_day_bounds_utc(date_from)[0]
    if date_to:
        rng["$lte"] = local_day_bounds_utc(date_to)[1]
    if rng:
        match["created_at"] = rng
    if movie_id:
        match["movie_snapshot.movie_id"] = to_oid(movie_id, "Movie")
    if cinema_id:
        match["cinema_snapshot.cinema_id"] = to_oid(cinema_id, "Cinema")
    if status:
        match["status"] = status
    # Revenue figures always use confirmed bookings within the other filters.
    confirmed = {**match, "status": BookingStatus.CONFIRMED} if status in (None, BookingStatus.CONFIRMED) else None

    status_counts = {s: 0 for s in BookingStatus.ALL}
    for row in db.bookings.aggregate([{"$match": match}, {"$group": {"_id": "$status", "n": {"$sum": 1}}}]):
        status_counts[row["_id"]] = row["n"]

    totals = {"tickets": 0, "gross": 0.0, "discount": 0.0, "net": 0.0, "bookings": 0}
    top_movies: list[dict] = []
    categories: list[dict] = []
    coupons: list[dict] = []
    daily: dict[str, dict[str, float]] = defaultdict(lambda: {"bookings": 0, "tickets": 0, "revenue": 0.0})
    monthly: dict[str, dict[str, float]] = defaultdict(lambda: {"bookings": 0, "tickets": 0, "revenue": 0.0})
    slots: dict[str, int] = defaultdict(int)
    if confirmed is not None:
        # One streaming pass over confirmed bookings (projection keeps it light). Monetary sums are done in
        # Python so results are identical on every MongoDB-compatible server and version.
        movies_acc: dict[str, dict[str, float]] = defaultdict(lambda: {"bookings": 0, "tickets": 0, "revenue": 0.0})
        cats_acc: dict[str, dict[str, float]] = defaultdict(lambda: {"tickets": 0, "revenue": 0.0})
        coupons_acc: dict[str, dict[str, float]] = defaultdict(lambda: {"uses": 0, "discount": 0.0, "revenue": 0.0})
        projection = {"created_at": 1, "seat_count": 1, "subtotal": 1, "discount": 1, "total": 1, "show_start": 1,
                      "seats": 1, "offer.code": 1, "movie_snapshot.title": 1}
        for b in db.bookings.find(confirmed, projection):
            totals["bookings"] += 1
            totals["tickets"] += b["seat_count"]
            totals["gross"] += b["subtotal"]
            totals["discount"] += b["discount"]
            totals["net"] += b["total"]
            mv = movies_acc[b["movie_snapshot"]["title"]]
            mv["bookings"] += 1
            mv["tickets"] += b["seat_count"]
            mv["revenue"] += b["total"]
            for seat in b["seats"]:
                cats_acc[seat["category"]]["tickets"] += 1
                cats_acc[seat["category"]]["revenue"] += seat["price"]
            if b.get("offer"):
                cp = coupons_acc[b["offer"]["code"]]
                cp["uses"] += 1
                cp["discount"] += b["discount"]
                cp["revenue"] += b["total"]
            created = to_local(b["created_at"])
            for bucket, key in ((daily, created.strftime("%Y-%m-%d")), (monthly, created.strftime("%Y-%m"))):
                bucket[key]["bookings"] += 1
                bucket[key]["tickets"] += b["seat_count"]
                bucket[key]["revenue"] = _r(bucket[key]["revenue"] + b["total"])
            slots[to_local(b["show_start"]).strftime("%H:%M")] += b["seat_count"]
        totals = {k: (v if k in ("tickets", "bookings") else _r(v)) for k, v in totals.items()}
        top_movies = sorted(({"movie": k, "bookings": v["bookings"], "tickets": v["tickets"], "revenue": _r(v["revenue"])}
                             for k, v in movies_acc.items()), key=lambda x: x["tickets"], reverse=True)[:10]
        categories = sorted(({"category": k, "tickets": v["tickets"], "revenue": _r(v["revenue"])}
                             for k, v in cats_acc.items()), key=lambda x: x["tickets"], reverse=True)
        coupons = sorted(({"code": k, "uses": v["uses"], "discount": _r(v["discount"]), "revenue": _r(v["revenue"])}
                          for k, v in coupons_acc.items()), key=lambda x: x["uses"], reverse=True)

    # Occupancy per show (shows that have bookings, or upcoming shows), most recent first.
    st_q: dict[str, Any] = {}
    if movie_id:
        st_q["movie_id"] = to_oid(movie_id, "Movie")
    if cinema_id:
        st_q["cinema_id"] = to_oid(cinema_id, "Cinema")
    booked_by_show = {r["_id"]: r["n"] for r in db.seat_locks.aggregate([
        {"$match": {"state": LockState.BOOKED}}, {"$group": {"_id": "$showtime_id", "n": {"$sum": 1}}}])}
    show_docs = list(db.showtimes.find({**st_q, "$or": [{"_id": {"$in": list(booked_by_show)}},
                                                         {"start_time": {"$gte": utcnow()}}]})
                     .sort("start_time", 1).limit(200))
    movies = {m["_id"]: m["title"] for m in db.movies.find({"_id": {"$in": [s["movie_id"] for s in show_docs]}},
                                                            {"title": 1})}
    cinemas = {c["_id"]: c["name"] for c in db.cinemas.find({}, {"name": 1})}
    occupancy = []
    for s in show_docs:
        booked = booked_by_show.get(s["_id"], 0)
        occupancy.append({
            "showtime_id": str(s["_id"]),
            "label": f"{movies.get(s['movie_id'], '?')} · {to_local(s['start_time']).strftime('%d %b %I:%M %p')}",
            "movie": movies.get(s["movie_id"], "?"),
            "cinema": cinemas.get(s["cinema_id"], "?"),
            "start": to_local(s["start_time"]).isoformat(),
            "booked": booked,
            "capacity": s["capacity"],
            "occupancy_percent": round(booked / s["capacity"] * 100, 1) if s["capacity"] else 0.0,
        })
    occupancy.sort(key=lambda o: o["occupancy_percent"], reverse=True)
    total_cap = sum(o["capacity"] for o in occupancy if o["booked"])
    avg_occ = round(sum(o["booked"] for o in occupancy) / total_cap * 100, 1) if total_cap else 0.0

    now = utcnow()
    return {
        "generated_at": now,
        "counts": {
            "customers": db.users.count_documents({"role": Role.CUSTOMER}),
            "movies": db.movies.count_documents({}),
            "published_movies": db.movies.count_documents({"is_published": True}),
            "cinemas": db.cinemas.count_documents({}),
            "screens": db.screens.count_documents({}),
            "showtimes": db.showtimes.count_documents({}),
            "upcoming_showtimes": db.showtimes.count_documents({"start_time": {"$gt": now}}),
            "bookings": sum(status_counts.values()),
            "active_offers": db.offers.count_documents({"is_active": True, "end_date": {"$gte": now}}),
        },
        "status_counts": status_counts,
        "sales": {**totals, "average_occupancy_percent": avg_occ,
                  "average_booking_value": _r(totals["net"] / totals["bookings"]) if totals["bookings"] else 0.0},
        "top_movies": top_movies,
        "popular_showtimes": sorted(({"time": k, "tickets": v} for k, v in slots.items()),
                                    key=lambda x: x["tickets"], reverse=True)[:10],
        "occupancy": occupancy[:25],
        "seat_categories": categories,
        "daily_trend": [{"date": k, **v} for k, v in sorted(daily.items())],
        "monthly_trend": [{"month": k, **v} for k, v in sorted(monthly.items())],
        "coupons": coupons,
    }
