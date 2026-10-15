"""Time helpers. All datetimes are stored in MongoDB as UTC; display uses APP_TIMEZONE."""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from ..config import get_settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(dt: datetime | None) -> datetime | None:
    """Make a datetime timezone-aware UTC (naive values are assumed to already be UTC)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def app_tz() -> ZoneInfo:
    return ZoneInfo(get_settings().app_timezone)


def local_to_utc(dt: datetime) -> datetime:
    """Interpret a naive datetime as local cinema time (APP_TIMEZONE) and convert to UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=app_tz())
    return dt.astimezone(timezone.utc)


def to_local(dt: datetime) -> datetime:
    return as_utc(dt).astimezone(app_tz())


def local_day_bounds_utc(d: date) -> tuple[datetime, datetime]:
    tz = app_tz()
    start = datetime.combine(d, time.min, tzinfo=tz)
    end = datetime.combine(d, time.max, tzinfo=tz)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)
