"""Promotional offers / coupon codes: validation, atomic usage counting and admin management."""
from __future__ import annotations

from typing import Any

from pymongo import DESCENDING
from pymongo.client_session import ClientSession
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from ..utils.errors import AppError, conflict, not_found
from ..utils.ids import serialize, to_oid
from ..utils.timeutils import as_utc, local_to_utc, utcnow
from .support_service import audit


def present(offer: dict[str, Any], *, admin: bool = False) -> dict[str, Any]:
    out = serialize(offer)
    if offer.get("discount_type") == "percent":
        label = f"{offer['discount_value']:g}% off"
        if offer.get("max_discount"):
            label += f" (up to {offer['max_discount']:g})"
    else:
        label = f"{offer['discount_value']:g} off"
    out["label"] = label
    if offer.get("usage_limit"):
        out["remaining_uses"] = max(0, offer["usage_limit"] - offer.get("used_count", 0))
    if not admin:
        out.pop("used_count", None)
    return out


def get_by_code(db: Database, code: str) -> dict[str, Any] | None:
    return db.offers.find_one({"code": code.strip().upper()})


def list_public(db: Database) -> list[dict[str, Any]]:
    now = utcnow()
    offers = db.offers.find({"is_active": True, "end_date": {"$gte": now}}).sort("end_date", 1)
    out = []
    for o in offers:
        if o.get("usage_limit") and o.get("used_count", 0) >= o["usage_limit"]:
            continue
        item = present(o)
        item["is_live"] = as_utc(o["start_date"]) <= now
        out.append(item)
    return out


def compute_discount(offer: dict[str, Any], subtotal: float) -> float:
    if offer["discount_type"] == "percent":
        discount = subtotal * offer["discount_value"] / 100
        if offer.get("max_discount"):
            discount = min(discount, offer["max_discount"])
    else:
        discount = offer["discount_value"]
    return round(min(discount, subtotal), 2)


def evaluate(db: Database, offer: dict[str, Any] | None, subtotal: float, user_oid: Any) -> float:
    """Validate an offer for this customer and amount. Raises AppError with a specific reason."""
    now = utcnow()
    if not offer or not offer.get("is_active"):
        raise AppError(400, "This coupon code is not valid", "offer_invalid")
    if as_utc(offer["start_date"]) > now:
        raise AppError(400, "This offer has not started yet", "offer_not_started")
    if as_utc(offer["end_date"]) < now:
        raise AppError(400, "This offer has expired", "offer_expired")
    if subtotal < offer.get("min_booking_value", 0):
        raise AppError(400, f"This offer needs a minimum booking value of {offer['min_booking_value']:g}",
                       "offer_min_value")
    if offer.get("usage_limit") and offer.get("used_count", 0) >= offer["usage_limit"]:
        raise AppError(400, "This offer has been fully redeemed", "offer_exhausted")
    usage = db.coupon_usage.find_one({"offer_id": offer["_id"], "user_id": user_oid})
    if usage and usage.get("count", 0) >= offer.get("per_user_limit", 1):
        raise AppError(400, "You have already used this offer the maximum number of times", "offer_user_limit")
    discount = compute_discount(offer, subtotal)
    if discount <= 0:
        raise AppError(400, "This offer does not give a discount on this booking", "offer_invalid")
    return discount


def reserve_usage(db: Database, offer: dict[str, Any], user_oid: Any, session: ClientSession | None = None) -> None:
    """Atomically count one redemption, enforcing the global and per-customer limits."""
    limit = offer.get("usage_limit")
    filt: dict[str, Any] = {"_id": offer["_id"], "is_active": True}
    if limit:
        filt["used_count"] = {"$lt": limit}
    if db.offers.update_one(filt, {"$inc": {"used_count": 1}}, session=session).modified_count != 1:
        raise AppError(409, "This offer has just been fully redeemed", "offer_exhausted")
    try:
        db.coupon_usage.find_one_and_update(
            {"offer_id": offer["_id"], "user_id": user_oid, "count": {"$lt": offer.get("per_user_limit", 1)}},
            {"$inc": {"count": 1}, "$set": {"updated_at": utcnow()}},
            upsert=True,
            session=session,
        )
    except DuplicateKeyError:
        # The counter document exists and is already at the limit -> upsert collided with the unique index.
        if session is None:
            db.offers.update_one({"_id": offer["_id"]}, {"$inc": {"used_count": -1}})
        raise AppError(409, "You have already used this offer the maximum number of times", "offer_user_limit") from None


def release_usage(db: Database, offer_oid: Any, user_oid: Any) -> None:
    db.offers.update_one({"_id": offer_oid, "used_count": {"$gt": 0}}, {"$inc": {"used_count": -1}})
    db.coupon_usage.update_one({"offer_id": offer_oid, "user_id": user_oid, "count": {"$gt": 0}},
                               {"$inc": {"count": -1}})


# ---------------------------------------------------------------- admin
def _dates(data: dict[str, Any]) -> dict[str, Any]:
    for key in ("start_date", "end_date"):
        if data.get(key) is not None:
            data[key] = local_to_utc(data[key])
    return data


def admin_list(db: Database) -> list[dict[str, Any]]:
    out = []
    for o in db.offers.find().sort("created_at", DESCENDING):
        item = present(o, admin=True)
        applied = list(db.coupon_redemptions.find({"offer_id": o["_id"], "status": "applied"}, {"discount": 1}))
        item["redemptions"] = len(applied)
        item["discount_given"] = round(sum(r.get("discount", 0) for r in applied), 2)
        out.append(item)
    return out


def create_offer(db: Database, actor: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    now = utcnow()
    doc = {**_dates(dict(data)), "used_count": 0, "created_at": now, "updated_at": now}
    try:
        db.offers.insert_one(doc)
    except DuplicateKeyError:
        raise conflict(f"Offer code {data['code']} already exists", "duplicate_code") from None
    audit(db, actor, "offer.create", "offer", doc["_id"], {"code": doc["code"]})
    return present(doc, admin=True)


def update_offer(db: Database, actor: dict[str, Any], offer_id: str, data: dict[str, Any]) -> dict[str, Any]:
    oid = to_oid(offer_id, "Offer")
    offer = db.offers.find_one({"_id": oid})
    if not offer:
        raise not_found("Offer")
    changes = _dates({k: v for k, v in data.items() if v is not None})
    unset = {}
    if changes.get("max_discount") == 0:
        changes.pop("max_discount")
        unset["max_discount"] = ""
    if changes.get("usage_limit") == 0:
        changes.pop("usage_limit")
        unset["usage_limit"] = ""
    merged = {**offer, **changes}
    if as_utc(merged["end_date"]) <= as_utc(merged["start_date"]):
        raise AppError(400, "End date must be after the start date", "invalid_dates")
    if merged["discount_type"] == "percent" and merged["discount_value"] > 100:
        raise AppError(400, "Percentage discounts cannot exceed 100", "invalid_discount")
    update: dict[str, Any] = {"$set": {**changes, "updated_at": utcnow()}}
    if unset:
        update["$unset"] = unset
    db.offers.update_one({"_id": oid}, update)
    audit(db, actor, "offer.update", "offer", oid, {k: str(v) for k, v in {**changes, **unset}.items()})
    return present(db.offers.find_one({"_id": oid}), admin=True)


def deactivate_offer(db: Database, actor: dict[str, Any], offer_id: str) -> dict[str, Any]:
    return update_offer(db, actor, offer_id, {"is_active": False})
