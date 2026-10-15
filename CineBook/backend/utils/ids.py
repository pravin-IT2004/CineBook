"""ObjectId parsing and JSON-friendly serialisation of MongoDB documents."""
from __future__ import annotations

import secrets
from datetime import date, datetime, timezone
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId

from .errors import AppError

# Crockford-style alphabet without ambiguous characters (no 0/O, 1/I/L)
_REF_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


def to_oid(value: Any, what: str = "Resource") -> ObjectId:
    if isinstance(value, ObjectId):
        return value
    try:
        return ObjectId(str(value))
    except (InvalidId, TypeError):
        raise AppError(404, f"{what} not found", "not_found") from None


def new_booking_reference() -> str:
    return "CB-" + "".join(secrets.choice(_REF_ALPHABET) for _ in range(8))


def serialize(value: Any) -> Any:
    """Recursively convert ObjectIds/datetimes, renaming _id to id."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k == "password_hash":
                continue
            out["id" if k == "_id" else k] = serialize(v)
        return out
    if isinstance(value, list):
        return [serialize(v) for v in value]
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    return value
