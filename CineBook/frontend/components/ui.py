"""Reusable presentation helpers."""
from __future__ import annotations

import html
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from components.posters import poster_css
from services.api_client import APP_TIMEZONE, CURRENCY, ApiError

TZ = ZoneInfo(APP_TIMEZONE)
STATUS_BADGE = {"confirmed": "green", "cancelled": "red", "pending": "amber", "failed": "grey",
                "now_showing": "green", "coming_soon": "blue", "archived": "grey"}


def esc(x) -> str:
    return html.escape(str(x if x is not None else ""))


def money(x: float | None) -> str:
    return f"{CURRENCY}{(x or 0):,.2f}"


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(TZ)


def fmt_dt(value: str | None, fmt: str = "%a %d %b %Y, %I:%M %p") -> str:
    d = parse_dt(value)
    return d.strftime(fmt) if d else "—"


def nice_date(iso_day: str | None) -> str:
    """'2026-10-15' -> 'Thu, 15 Oct 2026'."""
    if not iso_day:
        return "—"
    from datetime import date

    return date.fromisoformat(iso_day[:10]).strftime("%a, %d %b %Y")


def badge(text: str, kind: str = "grey") -> str:
    return f'<span class="cb-badge {kind}">{esc(text)}</span>'


def status_badge(status: str) -> str:
    return badge(status.replace("_", " ").title(), STATUS_BADGE.get(status, "grey"))


def page_header(title: str, subtitle: str = "", eyebrow: str = "") -> None:
    st.markdown(
        f'<div class="cb-page-head">{f"<div class=eyebrow>{esc(eyebrow)}</div>" if eyebrow else ""}'
        f"<h1>{esc(title)}</h1>{f'<p>{esc(subtitle)}</p>' if subtitle else ''}</div>",
        unsafe_allow_html=True,
    )


def empty_state(icon: str, title: str, text: str = "") -> None:
    st.markdown(f'<div class="cb-empty"><div class="icon">{icon}</div><h3>{esc(title)}</h3><p>{esc(text)}</p></div>',
                unsafe_allow_html=True)


def stat_card(label: str, value, sub: str = "") -> None:
    st.markdown(f'<div class="cb-stat"><div class="label">{esc(label)}</div><div class="value">{esc(value)}</div>'
                f'<div class="sub">{esc(sub)}</div></div>', unsafe_allow_html=True)


def movie_card_html(m: dict) -> str:
    chip = badge(m.get("status_label", ""), "solid" if m.get("status") == "now_showing" else "blue")
    rating = ""
    if m.get("avg_user_rating"):
        rating = f'<div class="rating">★ {m["avg_user_rating"]:.1f}/5</div>'
    elif m.get("rating"):
        rating = f'<div class="rating">★ {m["rating"]:.1f}</div>'
    meta = f'{esc(m.get("certificate", ""))} · {m.get("duration_minutes", "?")} min · {esc(", ".join(m.get("languages", [])[:2]))}'
    genres = esc(" / ".join(m.get("genres", [])[:3]))
    return (f'<div class="cb-card"><div class="cb-poster" style="background-image:{poster_css(m)}">'
            f'<div class="chip">{chip}</div>{rating}</div><div class="body"><div class="title" title="{esc(m["title"])}">'
            f'{esc(m["title"])}</div><div class="meta">{meta}</div><div class="meta">{genres}</div></div></div>')


def show_api_error(err: ApiError, prefix: str = "") -> None:
    if err.code == "api_unreachable":
        st.error(f"🔌 {err.message}")
    elif err.status == 401:
        st.warning("Your session has expired. Please log in again.")
    else:
        st.error(f"{prefix}{err.message}")


def call(fn, *args, error_prefix: str = "", **kwargs):
    """Run an API call and show a friendly error instead of a stack trace. Returns None on failure."""
    try:
        return fn(*args, **kwargs)
    except ApiError as err:
        show_api_error(err, error_prefix)
        return None
