from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class Flexible(BaseModel):
    """Response model that documents key fields but tolerates extra ones."""

    model_config = ConfigDict(extra="allow")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int


class Message(BaseModel):
    message: str


class ErrorResponse(BaseModel):
    detail: str
    code: str


def page_response(items: list[Any], total: int, page: int, page_size: int) -> dict[str, Any]:
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, -(-total // page_size)) if page_size else 1,
    }
