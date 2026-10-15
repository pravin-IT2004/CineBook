"""Cinemas, screens and seat layouts."""
from __future__ import annotations

from typing import Any

from pymongo import ASCENDING
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from ..utils.errors import AppError, conflict, not_found
from ..utils.ids import serialize, to_oid
from ..utils.timeutils import utcnow
from .support_service import audit, get_policy


# ---------------------------------------------------------------- layout helpers
def layout_seats(layout: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return {seat_id: {row, number, category, blocked}} for a layout."""
    blocked = set(layout.get("blocked_seats") or [])
    seats: dict[str, dict[str, Any]] = {}
    for row in layout["rows"]:
        for n in range(1, int(row["seats"]) + 1):
            sid = f"{row['row']}{n}"
            seats[sid] = {"row": row["row"], "number": n, "category": row["category"], "blocked": sid in blocked}
    return seats


def layout_capacity(layout: dict[str, Any]) -> int:
    return sum(1 for s in layout_seats(layout).values() if not s["blocked"])


def category_counts(layout: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for s in layout_seats(layout).values():
        if not s["blocked"]:
            counts[s["category"]] = counts.get(s["category"], 0) + 1
    return counts


# ---------------------------------------------------------------- cinemas
def list_cinemas(db: Database, include_inactive: bool = False) -> list[dict[str, Any]]:
    q = {} if include_inactive else {"is_active": True}
    out = []
    for c in db.cinemas.find(q).sort("name", ASCENDING):
        item = serialize(c)
        screens = list(db.screens.find({"cinema_id": c["_id"]}).sort("name", ASCENDING))
        item["screens"] = [present_screen(s) for s in screens if include_inactive or s.get("is_active", True)]
        out.append(item)
    return out


def get_cinema(db: Database, cinema_id: str) -> dict[str, Any]:
    c = db.cinemas.find_one({"_id": to_oid(cinema_id, "Cinema")})
    if not c:
        raise not_found("Cinema")
    item = serialize(c)
    item["screens"] = [present_screen(s) for s in db.screens.find({"cinema_id": c["_id"]}).sort("name", ASCENDING)]
    return item


def create_cinema(db: Database, actor: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    now = utcnow()
    doc = {**data, "created_at": now, "updated_at": now}
    try:
        db.cinemas.insert_one(doc)
    except DuplicateKeyError:
        raise conflict(f"A cinema with code {data['code']} already exists", "duplicate_code") from None
    audit(db, actor, "cinema.create", "cinema", doc["_id"], {"name": doc["name"]})
    return serialize(doc)


def update_cinema(db: Database, actor: dict[str, Any], cinema_id: str, data: dict[str, Any]) -> dict[str, Any]:
    oid = to_oid(cinema_id, "Cinema")
    changes = {k: v for k, v in data.items() if v is not None}
    if not db.cinemas.find_one({"_id": oid}):
        raise not_found("Cinema")
    if changes:
        changes["updated_at"] = utcnow()
        db.cinemas.update_one({"_id": oid}, {"$set": changes})
        audit(db, actor, "cinema.update", "cinema", oid, {k: str(v) for k, v in changes.items()})
    return get_cinema(db, cinema_id)


def delete_cinema(db: Database, actor: dict[str, Any], cinema_id: str) -> None:
    oid = to_oid(cinema_id, "Cinema")
    if not db.cinemas.find_one({"_id": oid}):
        raise not_found("Cinema")
    if db.showtimes.count_documents({"cinema_id": oid}, limit=1):
        raise conflict("This cinema has showtimes. Deactivate it instead of deleting it.", "in_use")
    db.screens.delete_many({"cinema_id": oid})
    db.cinemas.delete_one({"_id": oid})
    audit(db, actor, "cinema.delete", "cinema", oid)


# ---------------------------------------------------------------- screens
def present_screen(s: dict[str, Any]) -> dict[str, Any]:
    out = serialize(s)
    out["capacity"] = layout_capacity(s["layout"])
    out["category_counts"] = category_counts(s["layout"])
    return out


def get_screen(db: Database, screen_id: str) -> dict[str, Any]:
    s = db.screens.find_one({"_id": to_oid(screen_id, "Screen")})
    if not s:
        raise not_found("Screen")
    return s


def create_screen(db: Database, actor: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    cinema_oid = to_oid(data["cinema_id"], "Cinema")
    if not db.cinemas.find_one({"_id": cinema_oid}):
        raise not_found("Cinema")
    now = utcnow()
    prices = data.get("default_prices") or get_policy(db)["default_prices"]
    doc = {
        "cinema_id": cinema_oid,
        "name": data["name"].strip(),
        "screen_type": data["screen_type"],
        "layout": data["layout"],
        "default_prices": prices,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    doc["capacity"] = layout_capacity(doc["layout"])
    if doc["capacity"] == 0:
        raise AppError(400, "A screen needs at least one sellable seat", "empty_layout")
    try:
        db.screens.insert_one(doc)
    except DuplicateKeyError:
        raise conflict(f"Screen '{doc['name']}' already exists in this cinema", "duplicate_screen") from None
    audit(db, actor, "screen.create", "screen", doc["_id"], {"name": doc["name"], "capacity": doc["capacity"]})
    return present_screen(doc)


def update_screen(db: Database, actor: dict[str, Any], screen_id: str, data: dict[str, Any]) -> dict[str, Any]:
    """Layout changes affect only showtimes created afterwards (showtimes keep a layout snapshot)."""
    s = get_screen(db, screen_id)
    changes = {k: v for k, v in data.items() if v is not None}
    if "layout" in changes:
        changes["capacity"] = layout_capacity(changes["layout"])
        if changes["capacity"] == 0:
            raise AppError(400, "A screen needs at least one sellable seat", "empty_layout")
    if changes:
        changes["updated_at"] = utcnow()
        try:
            db.screens.update_one({"_id": s["_id"]}, {"$set": changes})
        except DuplicateKeyError:
            raise conflict("Another screen in this cinema already has that name", "duplicate_screen") from None
        audit(db, actor, "screen.update", "screen", s["_id"], {k: str(v)[:200] for k, v in changes.items()})
    return present_screen(db.screens.find_one({"_id": s["_id"]}))


def delete_screen(db: Database, actor: dict[str, Any], screen_id: str) -> None:
    s = get_screen(db, screen_id)
    if db.showtimes.count_documents({"screen_id": s["_id"]}, limit=1):
        raise conflict("This screen has showtimes. Deactivate it instead of deleting it.", "in_use")
    db.screens.delete_one({"_id": s["_id"]})
    audit(db, actor, "screen.delete", "screen", s["_id"], {"name": s["name"]})
