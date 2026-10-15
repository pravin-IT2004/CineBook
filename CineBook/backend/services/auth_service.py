"""User registration, login, profiles and first-run administrator creation."""
from __future__ import annotations

import logging
from typing import Any

from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from ..auth import create_access_token, hash_password, verify_password
from ..config import get_settings
from ..models.constants import Role
from ..utils.errors import AppError, conflict
from ..utils.ids import serialize, to_oid
from ..utils.timeutils import utcnow

log = logging.getLogger("cinebook.auth")


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    keep = ("_id", "name", "email", "role", "phone", "is_active", "created_at")
    return serialize({k: user.get(k) for k in keep})


def token_response(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "access_token": create_access_token(user),
        "token_type": "bearer",
        "expires_in_minutes": get_settings().jwt_expire_minutes,
        "user": public_user(user),
    }


def register(db: Database, data: dict[str, Any]) -> dict[str, Any]:
    now = utcnow()
    user = {
        "name": data["name"],
        "email": data["email"].lower().strip(),
        "phone": data.get("phone"),
        "password_hash": hash_password(data["password"]),
        "role": Role.CUSTOMER,
        "is_active": True,
        "favourites": [],
        "recently_viewed": [],
        "created_at": now,
        "updated_at": now,
    }
    try:
        user["_id"] = db.users.insert_one(user).inserted_id
    except DuplicateKeyError:
        raise conflict("An account with this e-mail already exists", "email_taken") from None
    log.info("New customer registered: user_id=%s", user["_id"])
    return token_response(user)


def login(db: Database, email: str, password: str) -> dict[str, Any]:
    user = db.users.find_one({"email": email.lower().strip()})
    if not user or not verify_password(password, user.get("password_hash", "")):
        raise AppError(401, "Invalid e-mail or password", "invalid_credentials")
    if not user.get("is_active", True):
        raise AppError(403, "This account has been deactivated. Contact the cinema administrator.", "account_disabled")
    return token_response(user)


def update_profile(db: Database, user: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    changes = {k: v for k, v in data.items() if v is not None}
    if "phone" in data and data["phone"] == "":
        changes["phone"] = None
    if changes:
        changes["updated_at"] = utcnow()
        db.users.update_one({"_id": user["_id"]}, {"$set": changes})
    return public_user(db.users.find_one({"_id": user["_id"]}))


def change_password(db: Database, user: dict[str, Any], current: str, new: str) -> None:
    if not verify_password(current, user.get("password_hash", "")):
        raise AppError(400, "Current password is incorrect", "invalid_password")
    if current == new:
        raise AppError(400, "New password must be different from the current password", "same_password")
    db.users.update_one({"_id": user["_id"]}, {"$set": {"password_hash": hash_password(new), "updated_at": utcnow()}})


def ensure_admin(db: Database) -> str:
    """Create the configured administrator on first run. Never overwrites an existing account."""
    s = get_settings()
    if not s.admin_email or not s.admin_password:
        log.warning("ADMIN_EMAIL / ADMIN_PASSWORD not set - no administrator account was created.")
        return "skipped"
    email = s.admin_email.lower().strip()
    if db.users.find_one({"email": email}):
        return "exists"
    if len(s.admin_password) < 8:
        raise RuntimeError("ADMIN_PASSWORD must be at least 8 characters long")
    now = utcnow()
    try:
        db.users.insert_one(
            {
                "name": s.admin_name,
                "email": email,
                "phone": None,
                "password_hash": hash_password(s.admin_password),
                "role": Role.ADMIN,
                "is_active": True,
                "favourites": [],
                "recently_viewed": [],
                "created_at": now,
                "updated_at": now,
            }
        )
    except DuplicateKeyError:
        return "exists"
    log.info("Administrator account created for %s", email)
    return "created"


def admin_update_user(db: Database, actor: dict[str, Any], user_id: str, data: dict[str, Any]) -> dict[str, Any]:
    oid = to_oid(user_id, "User")
    target = db.users.find_one({"_id": oid})
    if not target:
        raise AppError(404, "User not found", "not_found")
    if oid == actor["_id"] and (data.get("is_active") is False or (data.get("role") and data["role"] != Role.ADMIN)):
        raise AppError(400, "You cannot deactivate or demote your own administrator account", "self_change")
    changes = {k: v for k, v in data.items() if v is not None}
    if changes:
        changes["updated_at"] = utcnow()
        db.users.update_one({"_id": oid}, {"$set": changes})
        from .support_service import audit

        audit(db, actor, "user.update", "user", oid, {k: v for k, v in changes.items() if k != "updated_at"})
    return public_user(db.users.find_one({"_id": oid}))
