"""MongoDB connection management and index definitions."""
from __future__ import annotations

import logging
import threading

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.database import Database
from pymongo.errors import PyMongoError

from .config import get_settings

log = logging.getLogger("cinebook.db")

_client: MongoClient | None = None
_lock = threading.Lock()
_tx_supported: bool | None = None


def get_client() -> MongoClient:
    """Return a process-wide MongoClient (thread-safe, connection-pooled)."""
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                s = get_settings()
                if s.mongo_url.startswith("mongomock://"):
                    # In-memory emulation used only by the automated tests when no MongoDB server is running.
                    import mongomock

                    _client = mongomock.MongoClient(tz_aware=True)
                else:
                    _client = MongoClient(
                        s.mongo_url,
                        serverSelectionTimeoutMS=s.mongo_timeout_ms,
                        tz_aware=True,
                        appname="cinebook-api",
                    )
    return _client


def get_db() -> Database:
    return get_client()[get_settings().mongo_db_name]


def close_client() -> None:
    global _client, _tx_supported
    with _lock:
        if _client is not None:
            _client.close()
        _client = None
        _tx_supported = None


def ping() -> bool:
    try:
        get_client().admin.command("ping")
        return True
    except Exception:  # noqa: BLE001 - any failure means "not reachable"
        return False


def server_supports_transactions() -> bool:
    """Multi-document transactions need a replica set or sharded cluster (not a standalone mongod)."""
    global _tx_supported
    if _tx_supported is None:
        if get_settings().mongo_url.startswith("mongomock://"):
            _tx_supported = False
        else:
            try:
                hello = get_client().admin.command("hello")
                _tx_supported = bool(hello.get("setName")) or hello.get("msg") == "isdbgrid"
            except PyMongoError:
                _tx_supported = False
    return _tx_supported


def transactions_enabled() -> bool:
    mode = get_settings().use_transactions
    if mode == "false":
        return False
    supported = server_supports_transactions()
    if mode == "true" and not supported:
        log.warning("USE_TRANSACTIONS=true but the MongoDB server is standalone; falling back to atomic operations.")
    return supported


INDEXES: dict[str, list[tuple[list[tuple[str, int]], dict]]] = {
    "users": [([("email", ASCENDING)], {"unique": True, "name": "uniq_email"}), ([("role", ASCENDING)], {})],
    "movies": [
        ([("slug", ASCENDING)], {"unique": True, "name": "uniq_slug"}),
        ([("is_published", ASCENDING), ("status", ASCENDING)], {}),
        ([("title", ASCENDING)], {}),
        ([("genres", ASCENDING)], {}),
        ([("languages", ASCENDING)], {}),
    ],
    "cinemas": [([("code", ASCENDING)], {"unique": True, "name": "uniq_cinema_code"})],
    "screens": [([("cinema_id", ASCENDING), ("name", ASCENDING)], {"unique": True, "name": "uniq_screen_per_cinema"})],
    "showtimes": [
        ([("screen_id", ASCENDING), ("start_time", ASCENDING)], {"unique": True, "name": "uniq_screen_start"}),
        ([("movie_id", ASCENDING), ("start_time", ASCENDING)], {}),
        ([("cinema_id", ASCENDING), ("start_time", ASCENDING)], {}),
    ],
    # One document per (showtime, seat) => the database itself rejects a second claim on a seat.
    "seat_locks": [
        ([("showtime_id", ASCENDING), ("seat_id", ASCENDING)], {"unique": True, "name": "uniq_showtime_seat"}),
        ([("hold_id", ASCENDING)], {}),
        ([("booking_id", ASCENDING)], {}),
        ([("expires_at", ASCENDING)], {"expireAfterSeconds": 0, "name": "ttl_expired_holds"}),
    ],
    "seat_holds": [([("user_id", ASCENDING), ("status", ASCENDING)], {}), ([("expires_at", ASCENDING)], {})],
    "bookings": [
        ([("reference", ASCENDING)], {"unique": True, "name": "uniq_reference"}),
        ([("user_id", ASCENDING), ("created_at", DESCENDING)], {}),
        ([("showtime_id", ASCENDING), ("status", ASCENDING)], {}),
        ([("status", ASCENDING), ("created_at", DESCENDING)], {}),
        ([("movie_snapshot.movie_id", ASCENDING)], {}),
    ],
    "offers": [([("code", ASCENDING)], {"unique": True, "name": "uniq_offer_code"}), ([("is_active", ASCENDING)], {})],
    "coupon_usage": [([("offer_id", ASCENDING), ("user_id", ASCENDING)], {"unique": True, "name": "uniq_offer_user"})],
    "coupon_redemptions": [
        ([("booking_id", ASCENDING)], {"unique": True, "name": "uniq_redemption_booking"}),
        ([("offer_id", ASCENDING), ("user_id", ASCENDING)], {}),
    ],
    "reviews": [([("movie_id", ASCENDING), ("user_id", ASCENDING)], {"unique": True, "name": "uniq_review"})],
    "notifications": [([("user_id", ASCENDING), ("created_at", DESCENDING)], {})],
    "audit_logs": [([("created_at", DESCENDING)], {}), ([("action", ASCENDING)], {})],
}


def ensure_indexes(db: Database | None = None) -> None:
    db = db if db is not None else get_db()
    for coll, specs in INDEXES.items():
        for keys, opts in specs:
            try:
                db[coll].create_index(keys, **opts)
            except PyMongoError as exc:
                if opts.get("unique"):
                    raise  # unique indexes are essential for correctness
                log.warning("Optional index on %s %s not created: %s", coll, keys, exc)
