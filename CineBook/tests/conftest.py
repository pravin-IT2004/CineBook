"""Test configuration.

Tests use a SEPARATE database (default name ``cinebook_test``) which is wiped before every test.
They never touch your development database ``cinebook``.

* If a MongoDB server is reachable at TEST_MONGO_URL (default mongodb://127.0.0.1:27017) it is used.
* Otherwise the tests fall back to ``mongomock`` (an in-memory emulation of PyMongo), so the suite
  can run even without MongoDB installed.
Force a mode with:  set TEST_MONGO_URL=mongomock://   (Windows)   or   export TEST_MONGO_URL=mongomock://
"""
from __future__ import annotations

import os
import secrets
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEST_DB = os.environ.get("TEST_MONGO_DB_NAME", "cinebook_test")
if not TEST_DB.endswith("_test"):
    raise RuntimeError("Refusing to run: the test database name must end with '_test'")


def _pick_mongo_url() -> str:
    url = os.environ.get("TEST_MONGO_URL", "mongodb://127.0.0.1:27017")
    if url.startswith("mongomock://"):
        return url
    try:
        from pymongo import MongoClient

        MongoClient(url, serverSelectionTimeoutMS=1500).admin.command("ping")
        return url
    except Exception:  # noqa: BLE001
        return "mongomock://"


# Environment must be configured before the backend is imported (settings are cached).
os.environ.update({
    "MONGO_URL": _pick_mongo_url(),
    "MONGO_DB_NAME": TEST_DB,
    "JWT_SECRET": secrets.token_urlsafe(48),
    "ADMIN_EMAIL": "admin@cinebook.test",
    "ADMIN_PASSWORD": "AdminPass123",
    "CLEANUP_INTERVAL_SECONDS": "0",
    "SMTP_HOST": "",
    "LOG_LEVEL": "WARNING",
    "APP_TIMEZONE": "Asia/Kolkata",
})

from fastapi.testclient import TestClient  # noqa: E402

from backend.config import get_settings  # noqa: E402

get_settings.cache_clear()

from backend.database import ensure_indexes, get_db  # noqa: E402
from backend.main import app  # noqa: E402
from backend.services.auth_service import ensure_admin  # noqa: E402

MODE = "mongomock" if os.environ["MONGO_URL"].startswith("mongomock") else "mongodb"


def pytest_report_header(config):  # noqa: D401
    return f"CineBook tests using {MODE} ({os.environ['MONGO_URL']}) database '{TEST_DB}'"


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def clean_db(client):
    db = get_db()
    assert db.name.endswith("_test"), "safety check: never wipe a non-test database"
    for name in db.list_collection_names():
        db.drop_collection(name)
    ensure_indexes(db)
    ensure_admin(db)
    yield db


@pytest.fixture
def db(clean_db):
    return clean_db


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin(client):
    r = client.post("/api/auth/login", json={"email": "admin@cinebook.test", "password": "AdminPass123"})
    assert r.status_code == 200, r.text
    return auth(r.json()["access_token"])


@pytest.fixture
def make_customer(client):
    counter = {"n": 0}

    def _make(name: str = "Test Customer") -> tuple[dict, dict]:
        counter["n"] += 1
        email = f"customer{counter['n']}_{secrets.token_hex(3)}@example.com"
        r = client.post("/api/auth/register", json={"name": name, "email": email, "password": "Password123"})
        assert r.status_code == 201, r.text
        body = r.json()
        return auth(body["access_token"]), body["user"]

    return _make


def local_iso(delta: timedelta) -> str:
    """Naive local (APP_TIMEZONE) ISO string, as the admin UI sends it."""
    from zoneinfo import ZoneInfo

    return (datetime.now(ZoneInfo("Asia/Kolkata")) + delta).replace(tzinfo=None, microsecond=0).isoformat()


@pytest.fixture
def catalog(client, admin):
    """A published movie, a cinema with one small screen and an upcoming showtime, created via the admin API."""
    def _create(start_in: timedelta = timedelta(days=1), title: str = "Test Movie", **movie_extra):
        mv = client.post("/api/admin/movies", headers=admin, json={
            "title": title, "description": "A test film", "genres": ["Drama", "Comedy"], "languages": ["English", "Tamil"],
            "duration_minutes": 120, "certificate": "UA", "release_date": "2026-01-01", "status": "now_showing",
            "is_published": True, **movie_extra})
        assert mv.status_code == 201, mv.text
        cinema = client.post("/api/admin/cinemas", headers=admin, json={
            "name": f"Cinema {secrets.token_hex(2)}", "code": f"C{secrets.token_hex(3).upper()}", "city": "Coimbatore"})
        assert cinema.status_code == 201, cinema.text
        screen = client.post("/api/admin/screens", headers=admin, json={
            "cinema_id": cinema.json()["id"], "name": "Screen 1", "screen_type": "2D",
            "layout": {"rows": [{"row": "A", "seats": 6, "category": "regular"},
                                {"row": "B", "seats": 6, "category": "premium"},
                                {"row": "C", "seats": 4, "category": "recliner"}],
                       "aisles_after": [3], "blocked_seats": ["A1"]},
            "default_prices": {"regular": 150, "premium": 250, "recliner": 400}})
        assert screen.status_code == 201, screen.text
        show = client.post("/api/admin/showtimes", headers=admin, json={
            "movie_id": mv.json()["id"], "screen_id": screen.json()["id"], "start_time": local_iso(start_in),
            "language": "English", "format": "2D"})
        assert show.status_code == 201, show.text
        return {"movie": mv.json(), "cinema": cinema.json(), "screen": screen.json(), "showtime": show.json()}

    return _create


@pytest.fixture
def offer(client, admin):
    def _create(code: str = "SAVE10", **extra):
        body = {"code": code, "title": f"{code} offer", "discount_type": "percent", "discount_value": 10,
                "min_booking_value": 0, "start_date": local_iso(timedelta(days=-1)),
                "end_date": local_iso(timedelta(days=10)), "per_user_limit": 1, **extra}
        r = client.post("/api/admin/offers", headers=admin, json=body)
        assert r.status_code == 201, r.text
        return r.json()

    return _create


def hold_and_book(client, headers, showtime_id, seats, offer_code=None):
    h = client.post("/api/holds", headers=headers, json={"showtime_id": showtime_id, "seats": seats})
    assert h.status_code == 201, h.text
    b = client.post("/api/bookings", headers=headers, json={"hold_id": h.json()["id"], "offer_code": offer_code})
    return h.json(), b
