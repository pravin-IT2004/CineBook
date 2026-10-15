"""CineBook Streamlit frontend entry point.

Run from the CineBook folder:   streamlit run frontend/app.py
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

LOGO = Path(__file__).parent / "assets" / "logo.png"
st.set_page_config(page_title="CineBook", page_icon=str(LOGO) if LOGO.exists() else "🎬", layout="wide",
                   initial_sidebar_state="auto")

from components.theme import apply_theme  # noqa: E402
from components.ui import esc  # noqa: E402
from services import state  # noqa: E402
from services.state import PAGES  # noqa: E402

state.init()
state.sync_cookie()
apply_theme()

pages = {key: st.Page(path, default=(key == "home"), url_path=key) for key, path in PAGES.items()}
current = st.navigation(list(pages.values()), position="hidden")
st.session_state["_current_page"] = next((k for k, p in pages.items() if p == current), "home")

with st.sidebar:
    st.markdown('<div class="cb-brand"><div class="logo">🎬</div><div><div class="name">CINE<span>BOOK</span></div>'
                '<div class="tag">Smart movie ticket booking</div></div></div>', unsafe_allow_html=True)
    user = state.user()
    if user:
        role = "Administrator" if user["role"] == "admin" else "Customer"
        st.markdown(f'<div class="cb-userbox"><b>{esc(user["name"])}</b><span class="cb-muted">{role} · '
                    f'{esc(user["email"])}</span></div>', unsafe_allow_html=True)

    st.markdown('<div class="cb-navlabel">Browse</div>', unsafe_allow_html=True)
    st.page_link(pages["home"], label="Home", icon="🏠")
    st.page_link(pages["movies"], label="Movies", icon="🎞️")
    st.page_link(pages["offers"], label="Offers", icon="🏷️")
    if user and user["role"] == "customer":
        st.markdown('<div class="cb-navlabel">My account</div>', unsafe_allow_html=True)
        st.page_link(pages["bookings"], label="My Bookings", icon="🎟️")
        st.page_link(pages["profile"], label="Profile", icon="👤")
    if user and user["role"] == "admin":
        st.markdown('<div class="cb-navlabel">Administration</div>', unsafe_allow_html=True)
        st.page_link(pages["admin"], label="Dashboard", icon="📊")
        st.page_link(pages["admin_movies"], label="Movies", icon="🎬")
        st.page_link(pages["admin_cinemas"], label="Cinemas & Screens", icon="🏢")
        st.page_link(pages["admin_showtimes"], label="Showtimes", icon="🕒")
        st.page_link(pages["admin_bookings"], label="Bookings", icon="📋")
        st.page_link(pages["verify"], label="Verify Tickets", icon="✅")
        st.page_link(pages["admin_offers"], label="Offers", icon="🏷️")
        st.page_link(pages["admin_users"], label="Users", icon="👥")
        st.page_link(pages["admin_settings"], label="Settings & Audit", icon="⚙️")
        st.page_link(pages["profile"], label="Profile", icon="👤")
    st.divider()
    if user:
        if st.button("Log out", width="stretch"):
            state.logout()
            state.flash("You have been logged out.", "info")
            st.switch_page(PAGES["home"])
    else:
        if st.button("Log in / Register", type="primary", width="stretch"):
            st.switch_page(PAGES["login"])
    st.caption("Demo project · payments are not processed online.")

state.show_flash()
current.run()
