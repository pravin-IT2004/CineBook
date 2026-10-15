"""Session-state helpers: authentication, navigation and flash messages."""
from __future__ import annotations

from typing import Any

import streamlit as st

DEFAULTS: dict[str, Any] = {
    "token": None,
    "user": None,
    "movie_id": None,
    "showtime_id": None,
    "selected_seats": [],
    "seat_showtime": None,
    "hold": None,
    "applied_offer": None,
    "booking_id": None,
    "flash": [],
}

PAGES = {
    "home": "pages/home.py",
    "movies": "pages/movies.py",
    "movie": "pages/movie_detail.py",
    "seats": "pages/seats.py",
    "checkout": "pages/checkout.py",
    "ticket": "pages/ticket.py",
    "bookings": "pages/my_bookings.py",
    "offers": "pages/offers.py",
    "profile": "pages/profile.py",
    "login": "pages/login.py",
    "admin": "pages/admin_dashboard.py",
    "admin_movies": "pages/admin_movies.py",
    "admin_cinemas": "pages/admin_cinemas.py",
    "admin_showtimes": "pages/admin_showtimes.py",
    "admin_bookings": "pages/admin_bookings.py",
    "admin_offers": "pages/admin_offers.py",
    "admin_users": "pages/admin_users.py",
    "admin_settings": "pages/admin_settings.py",
    "verify": "pages/verify_ticket.py",
}


def init() -> None:
    for k, v in DEFAULTS.items():
        if k not in st.session_state:
            st.session_state[k] = list(v) if isinstance(v, list) else v


def user() -> dict | None:
    return st.session_state.get("user")


def logged_in() -> bool:
    return bool(st.session_state.get("token") and st.session_state.get("user"))


def is_admin() -> bool:
    u = user()
    return bool(u and u.get("role") == "admin")


COOKIE = "cinebook_token"


def login(token_response: dict) -> None:
    st.session_state.token = token_response["access_token"]
    st.session_state.user = token_response["user"]
    st.session_state["_cookie_action"] = ("set", token_response["access_token"],
                                          int(token_response.get("expires_in_minutes", 720)) * 60)


def logout() -> None:
    for k, v in DEFAULTS.items():
        st.session_state[k] = list(v) if isinstance(v, list) else v
    st.session_state["_cookie_action"] = ("clear", "", 0)


def sync_cookie() -> None:
    """Keep the login across browser refreshes.

    Streamlit forgets session state when the page is reloaded, so the JWT is also kept in a
    SameSite=Strict cookie for this site. On a fresh session the token is re-validated with the API.
    """
    action = st.session_state.pop("_cookie_action", None)
    if action:
        import streamlit.components.v1 as components

        kind, token, max_age = action
        js = (f"document.cookie='{COOKIE}={token}; path=/; max-age={max_age}; SameSite=Strict';" if kind == "set"
              else f"document.cookie='{COOKIE}=; path=/; max-age=0; SameSite=Strict';")
        components.html(f"<script>{js}</script>", height=0)
        return
    if st.session_state.get("token") or st.session_state.get("_cookie_checked"):
        return
    st.session_state["_cookie_checked"] = True
    token = st.context.cookies.get(COOKIE)
    if not token:
        return
    from services import api_client as api

    st.session_state.token = token
    try:
        st.session_state.user = api.get("/api/auth/me")
    except api.ApiError:
        st.session_state.token = None
        st.session_state.user = None
        st.session_state["_cookie_action"] = ("clear", "", 0)


def flash(message: str, kind: str = "success") -> None:
    st.session_state.flash.append((kind, message))


def show_flash() -> None:
    for kind, msg in st.session_state.get("flash", []):
        icon = {"success": "✅", "error": "⚠️", "warning": "⚠️", "info": "ℹ️"}.get(kind, "ℹ️")
        st.toast(msg, icon=icon)
    st.session_state.flash = []


def goto(page: str, **state: Any) -> None:
    for k, v in state.items():
        st.session_state[k] = v
    st.switch_page(PAGES[page])


def require_login(message: str = "Please log in to continue.") -> dict:
    if not logged_in():
        from components.ui import empty_state

        empty_state("🔐", "Login required", message)
        if st.button("Log in or create an account", type="primary"):
            st.session_state["after_login"] = st.session_state.get("_current_page")
            goto("login")
        st.stop()
    return user()


def require_admin() -> dict:
    u = require_login("This area is for cinema administrators.")
    if u.get("role") != "admin":
        from components.ui import empty_state

        empty_state("⛔", "Administrators only", "Your account does not have access to this page.")
        st.stop()
    return u


def require_customer() -> dict:
    u = require_login()
    if u.get("role") != "customer":
        from components.ui import empty_state

        empty_state("🎟️", "Customer accounts only",
                    "Administrators manage the cinema. Log in with a customer account to book tickets.")
        st.stop()
    return u
