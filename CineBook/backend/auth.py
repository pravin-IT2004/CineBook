"""Password hashing (bcrypt), JWT handling and FastAPI auth dependencies."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

import bcrypt
import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import get_settings
from .database import get_db
from .models.constants import Role
from .utils.errors import AppError
from .utils.ids import to_oid
from .utils.timeutils import utcnow

bearer = HTTPBearer(auto_error=False, description="Paste the access_token returned by /api/auth/login")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(user: dict[str, Any]) -> str:
    s = get_settings()
    now = utcnow()
    payload = {
        "sub": str(user["_id"]),
        "role": user["role"],
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=s.jwt_expire_minutes)).timestamp()),
        "typ": "access",
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any]:
    s = get_settings()
    try:
        return jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm], options={"require": ["exp", "sub"]})
    except jwt.ExpiredSignatureError:
        raise AppError(401, "Your session has expired. Please log in again.", "token_expired") from None
    except jwt.PyJWTError:
        raise AppError(401, "Invalid authentication token", "invalid_token") from None


def get_current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict[str, Any]:
    if creds is None or not creds.credentials:
        raise AppError(401, "Please log in to continue", "not_authenticated")
    payload = decode_token(creds.credentials)
    # Always re-read the user so deactivation / role changes take effect immediately.
    user = get_db().users.find_one({"_id": to_oid(payload["sub"], "User")})
    if not user:
        raise AppError(401, "Account no longer exists", "invalid_token")
    if not user.get("is_active", True):
        raise AppError(403, "This account has been deactivated", "account_disabled")
    return user


def get_optional_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict[str, Any] | None:
    if creds is None or not creds.credentials:
        return None
    try:
        return get_current_user(creds)
    except AppError:
        return None


def require_admin(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if user.get("role") != Role.ADMIN:
        raise AppError(403, "Administrator access required", "forbidden")
    return user


def require_customer(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if user.get("role") != Role.CUSTOMER:
        raise AppError(403, "This action is only available to customer accounts", "forbidden")
    return user
