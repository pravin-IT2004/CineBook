"""Seat availability and temporary seat holds.

Double-booking protection
-------------------------
Every claimed seat is one document in ``seat_locks`` with a UNIQUE index on (showtime_id, seat_id).
Whoever inserts that document first owns the seat; MongoDB rejects every other insert with a
DuplicateKeyError, no matter how many API workers or customers try at the same moment.

* A hold inserts locks with ``state="held"`` and an ``expires_at`` timestamp.
* An expired hold lock is reclaimed with an atomic ``delete_one`` that only matches while it is
  still expired, followed by a fresh insert (still protected by the unique index).
* Confirming a booking flips the caller's own held locks to ``state="booked"`` with a single
  conditional ``update_many`` (see booking_service).
* Expired locks are purged lazily on every availability check, by a background thread, and by a
  MongoDB TTL index on ``expires_at`` (booked locks have no ``expires_at`` so TTL never touches them).
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from bson import ObjectId
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from ..models.constants import HoldStatus, LockState, Role
from ..utils.errors import AppError, bad_request, not_found
from ..utils.ids import serialize, to_oid
from ..utils.timeutils import as_utc, utcnow
from .cinema_service import layout_seats
from .showtime_service import get_bookable_showtime
from .support_service import get_policy

log = logging.getLogger("cinebook.seats")


def purge_expired(db: Database, showtime_oid: Any | None = None) -> int:
    now = utcnow()
    q: dict[str, Any] = {"state": LockState.HELD, "expires_at": {"$lte": now}}
    hq: dict[str, Any] = {"status": HoldStatus.ACTIVE, "expires_at": {"$lte": now}}
    if showtime_oid is not None:
        q["showtime_id"] = showtime_oid
        hq["showtime_id"] = showtime_oid
    removed = db.seat_locks.delete_many(q).deleted_count
    db.seat_holds.update_many(hq, {"$set": {"status": HoldStatus.EXPIRED, "ended_at": now}})
    return removed


def price_seats(showtime: dict[str, Any], seat_ids: list[str]) -> list[dict[str, Any]]:
    """Server-side pricing. Prices come from the showtime document only, never from the client."""
    seats = layout_seats(showtime["layout"])
    items = []
    for sid in sorted(seat_ids, key=lambda s: (seats[s]["row"], seats[s]["number"])):
        cat = seats[sid]["category"]
        items.append({"seat_id": sid, "category": cat, "price": round(float(showtime["prices"][cat]), 2)})
    return items


def seat_map(db: Database, showtime_id: str, user: dict[str, Any] | None) -> dict[str, Any]:
    st = get_bookable_showtime(db, showtime_id)
    purge_expired(db, st["_id"])
    now = utcnow()
    states: dict[str, str] = {}
    my_hold_id = None
    for lock in db.seat_locks.find({"showtime_id": st["_id"]}):
        if lock["state"] == LockState.BOOKED:
            states[lock["seat_id"]] = "booked"
        elif lock.get("expires_at") and as_utc(lock["expires_at"]) > now:
            mine = user is not None and lock.get("user_id") == user["_id"]
            states[lock["seat_id"]] = "mine" if mine else "held"
            if mine:
                my_hold_id = lock["hold_id"]
    layout = st["layout"]
    aisles = set(layout.get("aisles_after") or [])
    blocked = set(layout.get("blocked_seats") or [])
    rows = []
    counts = {"available": 0, "booked": 0, "held": 0, "mine": 0, "blocked": 0}
    for r in layout["rows"]:
        seats = []
        for n in range(1, int(r["seats"]) + 1):
            sid = f"{r['row']}{n}"
            status = "blocked" if sid in blocked else states.get(sid, "available")
            counts[status] += 1
            seats.append({"seat_id": sid, "number": n, "status": status, "aisle_after": n in aisles})
        rows.append({"row": r["row"], "category": r["category"], "price": st["prices"][r["category"]], "seats": seats})
    hold = None
    if my_hold_id is not None:
        h = db.seat_holds.find_one({"_id": my_hold_id, "status": HoldStatus.ACTIVE})
        hold = present_hold(h) if h else None
    policy = get_policy(db)
    return {
        "showtime_id": str(st["_id"]),
        "prices": st["prices"],
        "rows": rows,
        "counts": counts,
        "capacity": st["capacity"],
        "my_hold": hold,
        "max_seats_per_booking": policy["max_seats_per_booking"],
        "hold_minutes": policy["hold_minutes"],
        "server_time": serialize(now),
    }


def present_hold(hold: dict[str, Any]) -> dict[str, Any]:
    out = serialize(hold)
    out["seconds_left"] = max(0, int((as_utc(hold["expires_at"]) - utcnow()).total_seconds()))
    return out


def _try_lock(db: Database, showtime_oid: Any, seat_id: str, user_oid: Any, hold_oid: Any, expires_at, now) -> bool:
    for _ in range(2):
        try:
            db.seat_locks.insert_one({
                "showtime_id": showtime_oid, "seat_id": seat_id, "state": LockState.HELD, "user_id": user_oid,
                "hold_id": hold_oid, "booking_id": None, "expires_at": expires_at, "created_at": now,
            })
            return True
        except DuplicateKeyError:
            # Seat already claimed. Reclaim it only if it is an *expired* hold (atomic, single winner).
            reclaimed = db.seat_locks.delete_one(
                {"showtime_id": showtime_oid, "seat_id": seat_id, "state": LockState.HELD, "expires_at": {"$lte": now}}
            ).deleted_count
            if not reclaimed:
                return False
    return False


def create_hold(db: Database, user: dict[str, Any], showtime_id: str, seat_ids: list[str]) -> dict[str, Any]:
    policy = get_policy(db)
    st = get_bookable_showtime(db, showtime_id)
    if len(seat_ids) > policy["max_seats_per_booking"]:
        raise bad_request(f"You can book at most {policy['max_seats_per_booking']} seats at a time", "too_many_seats")
    seats = layout_seats(st["layout"])
    unknown = [s for s in seat_ids if s not in seats]
    if unknown:
        raise bad_request(f"Seats do not exist in this screen: {', '.join(unknown)}", "invalid_seats")
    blocked = [s for s in seat_ids if seats[s]["blocked"]]
    if blocked:
        raise bad_request(f"Seats are not available for sale: {', '.join(blocked)}", "blocked_seats")

    # A customer keeps at most one active hold per showtime: release the previous one first.
    for old in db.seat_holds.find({"user_id": user["_id"], "showtime_id": st["_id"], "status": HoldStatus.ACTIVE}):
        _release(db, old, HoldStatus.RELEASED)

    now = utcnow()
    expires_at = now + timedelta(minutes=policy["hold_minutes"])
    hold_oid = ObjectId()
    unavailable = [s for s in seat_ids if not _try_lock(db, st["_id"], s, user["_id"], hold_oid, expires_at, now)]
    if unavailable:
        db.seat_locks.delete_many({"hold_id": hold_oid, "state": LockState.HELD})  # roll back partial hold
        raise AppError(409, f"Sorry, these seats were just taken by someone else: {', '.join(unavailable)}. "
                            "Please choose different seats.", "seats_unavailable", unavailable_seats=unavailable)
    items = price_seats(st, seat_ids)
    hold = {
        "_id": hold_oid,
        "user_id": user["_id"],
        "showtime_id": st["_id"],
        "seats": [i["seat_id"] for i in items],
        "line_items": items,
        "subtotal": round(sum(i["price"] for i in items), 2),
        "status": HoldStatus.ACTIVE,
        "expires_at": expires_at,
        "created_at": now,
    }
    db.seat_holds.insert_one(hold)
    log.info("Hold %s created for %d seats on showtime %s", hold_oid, len(items), st["_id"])
    return present_hold(hold)


def get_hold(db: Database, user: dict[str, Any], hold_id: str) -> dict[str, Any]:
    hold = db.seat_holds.find_one({"_id": to_oid(hold_id, "Seat hold")})
    if not hold or (hold["user_id"] != user["_id"] and user.get("role") != Role.ADMIN):
        raise not_found("Seat hold")
    if hold["status"] == HoldStatus.ACTIVE and as_utc(hold["expires_at"]) <= utcnow():
        _release(db, hold, HoldStatus.EXPIRED)
        hold = db.seat_holds.find_one({"_id": hold["_id"]})
    return present_hold(hold)


def _release(db: Database, hold: dict[str, Any], new_status: str) -> None:
    db.seat_locks.delete_many({"hold_id": hold["_id"], "state": LockState.HELD})
    db.seat_holds.update_one({"_id": hold["_id"], "status": HoldStatus.ACTIVE},
                             {"$set": {"status": new_status, "ended_at": utcnow()}})


def release_hold(db: Database, user: dict[str, Any], hold_id: str) -> dict[str, Any]:
    hold = db.seat_holds.find_one({"_id": to_oid(hold_id, "Seat hold")})
    if not hold or (hold["user_id"] != user["_id"] and user.get("role") != Role.ADMIN):
        raise not_found("Seat hold")
    if hold["status"] == HoldStatus.ACTIVE:
        _release(db, hold, HoldStatus.RELEASED)
    return present_hold(db.seat_holds.find_one({"_id": hold["_id"]}))
