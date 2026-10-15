"""Application error type with a consistent JSON shape: {"detail": str, "code": str, ...extra}."""
from __future__ import annotations

from typing import Any


class AppError(Exception):
    def __init__(self, status_code: int, detail: str, code: str = "error", **extra: Any) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.code = code
        self.extra = extra


def not_found(what: str) -> AppError:
    return AppError(404, f"{what} not found", "not_found")


def bad_request(detail: str, code: str = "bad_request", **extra: Any) -> AppError:
    return AppError(400, detail, code, **extra)


def conflict(detail: str, code: str = "conflict", **extra: Any) -> AppError:
    return AppError(409, detail, code, **extra)


def forbidden(detail: str = "You do not have permission to perform this action") -> AppError:
    return AppError(403, detail, "forbidden")
