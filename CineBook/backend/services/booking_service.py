"""Booking confirmation, history, cancellation and cleanup.

Confirmation steps (all values are recomputed on the server):
  1. Load the caller's ACTIVE, unexpired hold.
  2. Re-validate the showtime (published, not started, booking window open).
  3. Price seats from the showtime document and validate the coupon.
  4. Insert the booking as PENDING.
  5. Reserve coupon usage atomically (global + per-customer counters).
  6. Flip the hold's seat locks from HELD to BOOKED with one conditional update_many. If fewer
     locks than seats were flipped, the hold expired/was reclaimed -> the booking fails.
  7. Mark the booking CONFIRMED and the hold CONVERTED; record the coupon redemption.

On a replica set (transactions supported) steps 4-7 run inside a multi-document transaction.
On a standalone server they run as atomic single-document operations and any failure triggers
compensating actions, so a failed booking never leaves seats or coupon usage behind.
"""
from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import Any

from bson import ObjectId
from pymongo import DESCENDING, ReturnDocument
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from ..database import get_client, transactions_enabled
from ..models.constants import BookingStatus, HoldStatus, LockState, Role
from ..utils.errors import AppError, conflict, not_found
from ..utils.ids import new_booking_reference, serialize, to_oid
from ..utils.timeutils import as_utc, local_day_bounds_utc, to_local, utcnow
from . import offer_service
from .showtime_service import get_bookable_showtime
from .support_service import audit, get_policy, notify

log = logging.getLogger("cinebook.bookings")

PAYMENT_NOTE = ("No online payment gateway is integrated. The amount shown is payable at the cinema "
                "counter before the show.")
OFFER_ERROR_CODES = {"offer_exhausted", "offer_user_limit", "offer_invalid"}


# ---------------------------------------------------------------- presentation
def present(db: Database, b: dict[str, Any]) -> dict[str, Any]:
    out = serialize(b)
    now = utcnow()
    start = as_utc(b["show_start"])
    out["is_upcoming"] = start > now
    out["local_show_date"] = to_local(start).strftime("%a, %d %b %Y")
    out["local_show_time"] = to_local(start).strftime("%I:%M %p").lstrip("0")
    out["can_cancel"], out["cancel_reason"] = cancellation_check(db, b)
    out["can_review"] = b["status"] == BookingStatus.CONFIRMED and start <= now
    return out


def cancellation_check(db: Database, b: dict[str, Any], *, by_admin: bool = False) -> tuple[bool, str]:
    if b["status"] != BookingStatus.CONFIRMED:
        return False, f"Booking is {b['status']}"
    now = utcnow()
    start = as_utc(b["show_start"])
    if start <= now:
        return False, "The show has already started"
    if by_admin:
        return True, "Administrator cancellation"
    policy = get_policy(db)
    if not policy["cancellations_enabled"]:
        return False, "Online cancellations are currently disabled"
    if start - now < timedelta(hours=policy["cancellation_cutoff_hours"]):
        return False, f"Cancellations close {policy['cancellation_cutoff_hours']:g} hours before the show"
    return True, f"Cancellable until {policy['cancellation_cutoff_hours']:g} hours before the show"


def policy_summary(db: Database) -> dict[str, Any]:
    p = get_policy(db)
    return {
        **p,
        "text": (
            f"Seats are held for {p['hold_minutes']} minutes while you check out. "
            + (f"Bookings can be cancelled up to {p['cancellation_cutoff_hours']:g} hours before the show; "
               f"a simulated refund of {p['refund_percent']}% of the booking amount is recorded as pending. "
               if p["cancellations_enabled"] else "Online cancellations are currently disabled. ")
            + "No online payment is collected, so no money is actually refunded by this application."
        ),
    }


def _get_for_actor(db: Database, actor: dict[str, Any], booking_id: str) -> dict[str, Any]:
    b = db.bookings.find_one({"_id": to_oid(booking_id, "Booking")})
    # Customers can only see their own bookings. 404 (not 403) avoids revealing that the id exists.
    if not b or (actor.get("role") != Role.ADMIN and b["user_id"] != actor["_id"]):
        raise not_found("Booking")
    return b


def get_booking(db: Database, actor: dict[str, Any], booking_id: str) -> dict[str, Any]:
    return _get_for_actor(db, actor, booking_id)


# ---------------------------------------------------------------- create
def create_booking(db: Database, user: dict[str, Any], hold_id: str, offer_code: str | None) -> dict[str, Any]:
    hold = db.seat_holds.find_one({"_id": to_oid(hold_id, "Seat hold")})
    if not hold or hold["user_id"] != user["_id"]:
        raise not_found("Seat hold")
    if hold["status"] == HoldStatus.CONVERTED:
        raise conflict("These seats have already been booked with this hold", "hold_used",
                       booking_id=str(hold.get("booking_id")))
    if hold["status"] != HoldStatus.ACTIVE or as_utc(hold["expires_at"]) <= utcnow():
        db.seat_locks.delete_many({"hold_id": hold["_id"], "state": LockState.HELD})
        db.seat_holds.update_one({"_id": hold["_id"], "status": HoldStatus.ACTIVE},
                                 {"$set": {"status": HoldStatus.EXPIRED, "ended_at": utcnow()}})
        raise AppError(410, "Your seat hold has expired. Please select your seats again.", "hold_expired")

    st = get_bookable_showtime(db, hold["showtime_id"])
    from .seat_service import price_seats  # local import avoids a circular import

    items = price_seats(st, hold["seats"])
    subtotal = round(sum(i["price"] for i in items), 2)
    offer, discount = None, 0.0
    if offer_code and offer_code.strip():
        offer = offer_service.get_by_code(db, offer_code)
        discount = offer_service.evaluate(db, offer, subtotal, user["_id"])
    total = round(subtotal - discount, 2)

    movie = db.movies.find_one({"_id": st["movie_id"]}) or {}
    screen = db.screens.find_one({"_id": st["screen_id"]}) or {}
    cinema = db.cinemas.find_one({"_id": st["cinema_id"]}) or {}
    now = utcnow()
    booking = {
        "_id": ObjectId(),
        "reference": _unique_reference(db),
        "user_id": user["_id"],
        "user_snapshot": {"name": user["name"], "email": user["email"]},
        "showtime_id": st["_id"],
        "hold_id": hold["_id"],
        # Snapshots keep historical tickets correct even if the catalogue changes later.
        "movie_snapshot": {"movie_id": st["movie_id"], "title": movie.get("title"),
                           "certificate": movie.get("certificate"), "duration_minutes": movie.get("duration_minutes"),
                           "languages": movie.get("languages", []), "genres": movie.get("genres", []),
                           "poster_url": movie.get("poster_url"), "poster_colors": movie.get("poster_colors")},
        "cinema_snapshot": {"cinema_id": st["cinema_id"], "name": cinema.get("name"), "city": cinema.get("city"),
                            "address": cinema.get("address")},
        "screen_snapshot": {"screen_id": st["screen_id"], "name": screen.get("name"),
                            "screen_type": screen.get("screen_type")},
        "show_start": st["start_time"],
        "show_end": st["end_time"],
        "language": st["language"],
        "format": st["format"],
        "seats": items,
        "seat_count": len(items),
        "subtotal": subtotal,
        "discount": discount,
        "total": total,
        "offer": ({"offer_id": offer["_id"], "code": offer["code"], "title": offer["title"],
                   "discount_type": offer["discount_type"], "discount_value": offer["discount_value"]}
                  if offer else None),
        "payment": {"status": "not_collected", "method": "pay_at_cinema", "note": PAYMENT_NOTE},
        "refund": None,
        "status": BookingStatus.PENDING,
        "status_history": [{"status": BookingStatus.PENDING, "at": now}],
        "created_at": now,
        "updated_at": now,
    }
    progress = {"coupon_reserved": False, "seats_converted": False}
    use_txn = transactions_enabled()
    try:
        if use_txn:
            with get_client().start_session() as session:
                session.with_transaction(lambda s: _commit(db, booking, hold, offer, s, progress))
        else:
            _commit(db, booking, hold, offer, None, progress)
    except Exception as exc:  # noqa: BLE001 - every failure path must clean up
        reason = exc.detail if isinstance(exc, AppError) else "Unexpected error while confirming the booking"
        keep_hold = isinstance(exc, AppError) and exc.code in OFFER_ERROR_CODES
        _rollback(db, booking, hold, offer, progress, transactional=use_txn, reason=reason, keep_hold=keep_hold)
        if isinstance(exc, AppError):
            raise
        log.exception("Booking %s failed", booking["reference"])
        raise AppError(500, "The booking could not be completed and no seats were reserved. Please try again.",
                       "booking_failed") from exc

    confirmed = db.bookings.find_one({"_id": booking["_id"]})
    show = to_local(confirmed["show_start"]).strftime("%a %d %b, %I:%M %p")
    notify(db, user["_id"], "Booking confirmed 🎬",
           f"{confirmed['movie_snapshot']['title']} · {show} · Seats "
           f"{', '.join(s['seat_id'] for s in confirmed['seats'])} · Ref {confirmed['reference']}", "success")
    log.info("Booking %s confirmed (%d seats)", confirmed["reference"], confirmed["seat_count"])
    return confirmed


def _unique_reference(db: Database) -> str:
    for _ in range(10):
        ref = new_booking_reference()
        if not db.bookings.find_one({"reference": ref}, {"_id": 1}):
            return ref
    raise AppError(500, "Could not allocate a booking reference", "reference_failed")


def _commit(db: Database, booking: dict[str, Any], hold: dict[str, Any], offer: dict[str, Any] | None,
            session, progress: dict[str, bool]) -> None:
    now = utcnow()
    db.bookings.insert_one(booking, session=session)
    if offer:
        offer_service.reserve_usage(db, offer, booking["user_id"], session=session)
        progress["coupon_reserved"] = True
    converted = db.seat_locks.update_many(
        {"hold_id": hold["_id"], "user_id": booking["user_id"], "state": LockState.HELD, "expires_at": {"$gt": now}},
        {"$set": {"state": LockState.BOOKED, "booking_id": booking["_id"], "booked_at": now},
         "$unset": {"expires_at": ""}},
        session=session,
    ).modified_count
    progress["seats_converted"] = converted > 0
    if converted != len(booking["seats"]):
        raise AppError(409, "Your seat hold expired or some seats are no longer available. "
                            "Please select your seats again.", "seats_unavailable")
    res = db.bookings.update_one(
        {"_id": booking["_id"], "status": BookingStatus.PENDING},
        {"$set": {"status": BookingStatus.CONFIRMED, "confirmed_at": now, "updated_at": now},
         "$push": {"status_history": {"status": BookingStatus.CONFIRMED, "at": now}}},
        session=session,
    )
    if res.modified_count != 1:
        raise AppError(409, "Booking state changed unexpectedly", "state_conflict")
    db.seat_holds.update_one({"_id": hold["_id"], "status": HoldStatus.ACTIVE},
                             {"$set": {"status": HoldStatus.CONVERTED, "booking_id": booking["_id"], "ended_at": now}},
                             session=session)
    if offer:
        db.coupon_redemptions.insert_one(
            {"offer_id": offer["_id"], "code": offer["code"], "user_id": booking["user_id"],
             "booking_id": booking["_id"], "discount": booking["discount"], "status": "applied", "created_at": now},
            session=session,
        )


def _rollback(db: Database, booking: dict[str, Any], hold: dict[str, Any], offer: dict[str, Any] | None,
              progress: dict[str, bool], *, transactional: bool, reason: str, keep_hold: bool) -> None:
    now = utcnow()
    try:
        if not transactional:
            # Compensate partial work done outside a transaction.
            if progress["seats_converted"]:
                db.seat_locks.delete_many({"booking_id": booking["_id"]})
            if progress["coupon_reserved"] and offer:
                offer_service.release_usage(db, offer["_id"], booking["user_id"])
            db.coupon_redemptions.delete_many({"booking_id": booking["_id"]})
        if not keep_hold:
            db.seat_locks.delete_many({"hold_id": hold["_id"], "state": LockState.HELD})
            db.seat_holds.update_one({"_id": hold["_id"], "status": {"$in": [HoldStatus.ACTIVE, HoldStatus.CONVERTED]}},
                                     {"$set": {"status": HoldStatus.RELEASED, "ended_at": now}})
        record = {k: v for k, v in booking.items() if k not in ("_id", "status", "status_history", "updated_at")}
        try:
            # The customer never received a success response, so even a booking that reached CONFIRMED
            # inside this request is rolled back to FAILED (the only allowed exception to the state machine).
            db.bookings.update_one(
                {"_id": booking["_id"], "status": {"$in": [BookingStatus.PENDING, BookingStatus.CONFIRMED]}},
                {"$set": {"status": BookingStatus.FAILED, "failure_reason": reason, "updated_at": now},
                 "$setOnInsert": record,
                 "$push": {"status_history": {"status": BookingStatus.FAILED, "at": now, "note": reason}}},
                upsert=True,
            )
        except DuplicateKeyError:
            pass
    except Exception:  # noqa: BLE001
        log.exception("Cleanup after failed booking %s did not finish; background cleanup will retry",
                      booking["reference"])


# ---------------------------------------------------------------- history
def list_for_user(db: Database, user: dict[str, Any], scope: str, page: int, page_size: int):
    now = utcnow()
    q: dict[str, Any] = {"user_id": user["_id"]}
    sort = [("show_start", DESCENDING)]
    if scope == "upcoming":
        q.update({"status": BookingStatus.CONFIRMED, "show_start": {"$gt": now}})
        sort = [("show_start", 1)]
    elif scope == "past":
        q.update({"status": BookingStatus.CONFIRMED, "show_start": {"$lte": now}})
    elif scope == "cancelled":
        q["status"] = BookingStatus.CANCELLED
    else:
        q["status"] = {"$in": [BookingStatus.CONFIRMED, BookingStatus.CANCELLED]}
    total = db.bookings.count_documents(q)
    docs = db.bookings.find(q).sort(sort).skip((page - 1) * page_size).limit(page_size)
    return [present(db, b) for b in docs], total


# ---------------------------------------------------------------- cancel
def cancel_booking(db: Database, actor: dict[str, Any], booking_id: str, reason: str | None) -> dict[str, Any]:
    b = _get_for_actor(db, actor, booking_id)
    by_admin = actor.get("role") == Role.ADMIN
    ok, why = cancellation_check(db, b, by_admin=by_admin)
    if not ok:
        raise conflict(f"This booking cannot be cancelled: {why}", "not_cancellable")
    policy = get_policy(db)
    percent = 100 if by_admin else policy["refund_percent"]
    now = utcnow()
    refund = {
        "status": "simulated_pending",
        "percent": percent,
        "amount": round(b["total"] * percent / 100, 2),
        "note": "Simulated refund – no payment was collected online, so no money is transferred by CineBook.",
    }
    updated = db.bookings.find_one_and_update(
        {"_id": b["_id"], "status": BookingStatus.CONFIRMED},  # atomic state transition
        {"$set": {"status": BookingStatus.CANCELLED, "cancelled_at": now, "updated_at": now,
                  "cancelled_by": "admin" if by_admin else "customer", "cancellation_reason": reason, "refund": refund},
         "$push": {"status_history": {"status": BookingStatus.CANCELLED, "at": now, "note": reason}}},
        return_document=ReturnDocument.AFTER,
    )
    if not updated:
        raise conflict("This booking was already cancelled", "not_cancellable")
    # Seats return to sale only after the cancellation itself has succeeded.
    db.seat_locks.delete_many({"booking_id": b["_id"], "state": LockState.BOOKED})
    if b.get("offer"):
        offer_service.release_usage(db, b["offer"]["offer_id"], b["user_id"])
        db.coupon_redemptions.update_one({"booking_id": b["_id"]}, {"$set": {"status": "reversed",
                                                                            "reversed_at": now}})
    notify(db, b["user_id"], "Booking cancelled",
           f"{b['movie_snapshot']['title']} · Ref {b['reference']} was cancelled. "
           f"Refund of {refund['amount']:.2f} recorded as simulated / pending.", "warning")
    if by_admin:
        audit(db, actor, "booking.cancel", "booking", b["_id"], {"reference": b["reference"], "reason": reason})
    log.info("Booking %s cancelled by %s", b["reference"], "admin" if by_admin else "customer")
    return updated


# ---------------------------------------------------------------- admin
def admin_search(db: Database, *, reference: str | None, status: str | None, movie_id: str | None,
                 cinema_id: str | None, date_from, date_to, page: int, page_size: int):
    q: dict[str, Any] = {}
    if reference:
        q["reference"] = {"$regex": "^" + re.escape(reference.strip().upper())}
    if status:
        q["status"] = status
    if movie_id:
        q["movie_snapshot.movie_id"] = to_oid(movie_id, "Movie")
    if cinema_id:
        q["cinema_snapshot.cinema_id"] = to_oid(cinema_id, "Cinema")
    rng: dict[str, Any] = {}
    if date_from:
        rng["$gte"] = local_day_bounds_utc(date_from)[0]
    if date_to:
        rng["$lte"] = local_day_bounds_utc(date_to)[1]
    if rng:
        q["created_at"] = rng
    total = db.bookings.count_documents(q)
    docs = db.bookings.find(q).sort("created_at", DESCENDING).skip((page - 1) * page_size).limit(page_size)
    return [present(db, b) for b in docs], total


def check_in(db: Database, actor: dict[str, Any], reference: str) -> dict[str, Any]:
    b = db.bookings.find_one({"reference": reference.strip().upper()})
    if not b:
        raise not_found("Booking")
    if b["status"] != BookingStatus.CONFIRMED:
        raise conflict(f"Ticket is not valid for entry (status: {b['status']})", "ticket_invalid")
    if as_utc(b["show_end"]) < utcnow():
        raise conflict("This show has already ended", "ticket_expired")
    now = utcnow()
    res = db.bookings.find_one_and_update(
        {"_id": b["_id"], "status": BookingStatus.CONFIRMED, "checked_in_at": None},
        {"$set": {"checked_in_at": now, "updated_at": now}}, return_document=ReturnDocument.AFTER)
    if not res:
        raise conflict("This ticket has already been checked in", "already_checked_in")
    audit(db, actor, "booking.check_in", "booking", b["_id"], {"reference": b["reference"]})
    return res


# ---------------------------------------------------------------- maintenance
def cleanup(db: Database, stale_minutes: int = 5) -> dict[str, int]:
    """Release expired holds and fail bookings stuck in PENDING (e.g. after a crash mid-confirmation)."""
    from .seat_service import purge_expired

    released = purge_expired(db)
    failed = 0
    cutoff = utcnow() - timedelta(minutes=stale_minutes)
    for b in db.bookings.find({"status": BookingStatus.PENDING, "created_at": {"$lt": cutoff}}):
        now = utcnow()
        res = db.bookings.update_one(
            {"_id": b["_id"], "status": BookingStatus.PENDING},
            {"$set": {"status": BookingStatus.FAILED, "failure_reason": "Timed out during confirmation",
                      "updated_at": now},
             "$push": {"status_history": {"status": BookingStatus.FAILED, "at": now, "note": "cleanup"}}})
        if res.modified_count:
            failed += 1
            db.seat_locks.delete_many({"booking_id": b["_id"]})
            db.seat_locks.delete_many({"hold_id": b.get("hold_id"), "state": LockState.HELD})
    # Orphan booked locks (their booking failed or vanished) are released.
    recent = utcnow() - timedelta(days=2)
    ids = [i for i in db.seat_locks.distinct("booking_id", {"state": LockState.BOOKED, "booked_at": {"$gte": recent}}) if i]
    if ids:
        alive = {x["_id"] for x in db.bookings.find(
            {"_id": {"$in": ids}, "status": {"$in": [BookingStatus.CONFIRMED, BookingStatus.PENDING]}}, {"_id": 1})}
        orphans = [i for i in ids if i not in alive]
        if orphans:
            db.seat_locks.delete_many({"booking_id": {"$in": orphans}, "state": LockState.BOOKED,
                                       "booked_at": {"$lt": cutoff}})
    return {"released_locks": released, "failed_bookings": failed}
