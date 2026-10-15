"""API routers."""
from fastapi import Query

from ..database import get_db


def db_dep():
    return get_db()


def page_params(page: int = Query(1, ge=1), page_size: int = Query(12, ge=1, le=100)) -> tuple[int, int]:
    return page, page_size
