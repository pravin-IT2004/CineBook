"""CineBook FastAPI application.

Run from the project root:   uvicorn backend.main:app --reload --port 8000
Swagger docs:                http://127.0.0.1:8000/docs
"""
from __future__ import annotations

import logging
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pymongo.errors import AutoReconnect, ConnectionFailure, PyMongoError, ServerSelectionTimeoutError

from . import __version__
from .config import get_settings
from .database import close_client, ensure_indexes, get_db, ping, server_supports_transactions, transactions_enabled
from .routes import admin, auth, bookings, movies, users
from .services import auth_service, booking_service
from .utils.errors import AppError

log = logging.getLogger("cinebook")


def _configure_logging() -> None:
    level = getattr(logging, get_settings().log_level.upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")


def initialise_database() -> bool:
    """Create indexes and the first-run admin. Returns False if MongoDB is unreachable."""
    if not ping():
        log.error("MongoDB is not reachable at %s. The API will start, but requests needing the database "
                  "will return 503 until MongoDB is running.", get_settings().mongo_url.split("@")[-1])
        return False
    db = get_db()
    ensure_indexes(db)
    auth_service.ensure_admin(db)
    log.info("MongoDB connected (db=%s, transactions supported=%s, enabled=%s)", db.name,
             server_supports_transactions(), transactions_enabled())
    return True


class CleanupWorker:
    """Background thread that releases expired seat holds and stuck bookings."""

    def __init__(self, interval: int, initialised: bool) -> None:
        self.interval = max(5, interval)
        self.initialised = initialised
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="cinebook-cleanup", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                if not self.initialised:  # MongoDB was down at startup: keep retrying setup
                    self.initialised = initialise_database()
                    continue
                result = booking_service.cleanup(get_db())
                if any(result.values()):
                    log.info("Cleanup: %s", result)
            except PyMongoError as exc:
                log.warning("Cleanup skipped (database unavailable): %s", exc)
            except Exception:  # noqa: BLE001
                log.exception("Cleanup failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_logging()
    settings = get_settings()
    settings.validate_security()
    ready = initialise_database()
    worker = CleanupWorker(settings.cleanup_interval_seconds, ready)
    if settings.cleanup_interval_seconds > 0:
        worker.start()
    yield
    worker.stop()
    close_client()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="CineBook API",
        version=__version__,
        description=(
            "Smart Movie Ticket Booking and Management System.\n\n"
            "Use **POST /api/auth/login**, copy `access_token`, then click **Authorize** and paste it."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def access_log(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        # Only method, path and status are logged - never headers, tokens or bodies.
        logging.getLogger("cinebook.http").info("%s %s -> %s (%.0f ms)", request.method, request.url.path,
                                                response.status_code, (time.perf_counter() - start) * 1000)
        return response

    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail, "code": exc.code, **exc.extra})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        errors = []
        for e in exc.errors():
            field = ".".join(str(p) for p in e.get("loc", []) if p not in ("body", "query", "path"))
            msg = str(e.get("msg", "Invalid value")).removeprefix("Value error, ")
            errors.append({"field": field, "message": msg})
        summary = "; ".join(f"{e['field']}: {e['message']}" if e["field"] else e["message"] for e in errors[:3])
        return JSONResponse(status_code=422, content={"detail": summary or "Invalid request", "code": "validation_error",
                                                      "errors": errors})

    @app.exception_handler(ServerSelectionTimeoutError)
    @app.exception_handler(ConnectionFailure)
    @app.exception_handler(AutoReconnect)
    async def db_down(_: Request, exc: Exception):
        log.error("Database unavailable: %s", exc.__class__.__name__)
        return JSONResponse(status_code=503, content={"detail": "The database is unavailable. Please make sure "
                                                                "MongoDB is running and try again.",
                                                      "code": "db_unavailable"})

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        log.exception("Unhandled error")
        return JSONResponse(status_code=500, content={"detail": "An unexpected server error occurred.",
                                                      "code": "server_error"})

    @app.get("/", tags=["System"])
    def root():
        return {"name": "CineBook API", "version": __version__, "docs": "/docs", "health": "/api/health"}

    @app.get("/api/health", tags=["System"])
    def health():
        ok = ping()
        return {"status": "ok" if ok else "degraded", "database": "connected" if ok else "unreachable",
                "transactions_supported": server_supports_transactions() if ok else None,
                "transactions_enabled": transactions_enabled() if ok else None, "version": __version__}

    for r in (auth.router, users.router, movies.router, bookings.router, admin.router):
        app.include_router(r)
    return app


app = create_app()
