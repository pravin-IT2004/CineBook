import streamlit as st

from components.ui import call, empty_state, esc, fmt_dt, movie_card_html, page_header
from services import api_client as api
from services import state

user = state.require_login()
me = call(api.get, "/api/me")
if not me:
    st.stop()
page_header(me["name"], f"{me['email']} · member since {fmt_dt(me.get('created_at'), '%B %Y')}", "Profile")

is_customer = me["role"] == "customer"
tab_names = ["Profile", "Security"] + (["Watchlist", "Recently viewed", "Notifications"] if is_customer else [])
tabs = st.tabs(tab_names)

with tabs[0]:
    with st.form("profile_form"):
        name = st.text_input("Full name", value=me["name"], max_chars=60)
        phone = st.text_input("Phone (optional)", value=me.get("phone") or "", max_chars=20)
        st.text_input("E-mail", value=me["email"], disabled=True, help="E-mail cannot be changed.")
        if st.form_submit_button("Save changes", type="primary"):
            res = call(api.put, "/api/me", {"name": name, "phone": phone})
            if res:
                st.session_state.user = {**st.session_state.user, **res}
                state.flash("Profile updated.")
                st.rerun()

with tabs[1]:
    with st.form("pw_form", clear_on_submit=True):
        cur = st.text_input("Current password", type="password")
        new = st.text_input("New password", type="password", help="At least 8 characters with a letter and a number.")
        new2 = st.text_input("Confirm new password", type="password")
        if st.form_submit_button("Change password", type="primary"):
            if new != new2:
                st.error("The new passwords do not match.")
            elif call(api.post, "/api/me/password", {"current_password": cur, "new_password": new}):
                st.success("Password changed.")


def movie_grid(items: list[dict], key: str) -> None:
    for start in range(0, len(items), 4):
        for col, m in zip(st.columns(4), items[start:start + 4]):
            with col:
                st.markdown(movie_card_html(m), unsafe_allow_html=True)
                if st.button("Open", key=f"{key}_{m['id']}", width="stretch"):
                    state.goto("movie", movie_id=m["id"])


if is_customer:
    with tabs[2]:
        wl = call(api.get, "/api/me/watchlist")
        if wl:
            movie_grid(wl, "wl")
        elif wl is not None:
            empty_state("❤️", "Your watchlist is empty", "Tap 'Add to watchlist' on any movie page.")
    with tabs[3]:
        rv = call(api.get, "/api/me/recently-viewed")
        if rv:
            movie_grid(rv, "rv")
        elif rv is not None:
            empty_state("👀", "Nothing viewed yet", "Movies you open will show up here.")
    with tabs[4]:
        notes = call(api.get, "/api/me/notifications", params={"page_size": 30})
        if notes:
            if notes["unread"] and st.button(f"Mark all {notes['unread']} as read"):
                call(api.post, "/api/me/notifications/read-all")
                st.rerun()
            if not notes["items"]:
                empty_state("🔔", "No notifications", "Booking confirmations and cancellations appear here.")
            for n in notes["items"]:
                dot = "🔴 " if not n["read"] else ""
                st.markdown(f"<div class='cb-panel' style='margin-bottom:8px'>{dot}<b>{esc(n['title'])}</b> "
                            f"<span class='cb-muted'>· {fmt_dt(n['created_at'], '%d %b %Y %I:%M %p')}</span>"
                            f"<div>{esc(n['message'])}</div></div>", unsafe_allow_html=True)
