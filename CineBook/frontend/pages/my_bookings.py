import streamlit as st

from components.posters import poster_css
from components.ticket import pdf_download, render_ticket
from components.ui import call, empty_state, esc, money, page_header, status_badge
from services import api_client as api
from services import state

state.require_customer()
page_header("My Bookings", "Upcoming shows, past visits and cancellations.", "Account")

policy = call(api.get, "/api/settings/policy") or {}
if policy.get("text"):
    with st.expander("📜 Cancellation policy"):
        st.write(policy["text"])

PAGE_SIZE = 8
tabs = st.tabs(["Upcoming", "Past", "Cancelled", "All"])
for tab, scope in zip(tabs, ["upcoming", "past", "cancelled", "all"]):
    with tab:
        page_key = f"bk_page_{scope}"
        page = st.session_state.get(page_key, 1)
        data = call(api.get, "/api/bookings", params={"scope": scope, "page": page, "page_size": PAGE_SIZE})
        if data is None:
            continue
        if not data["items"]:
            empty_state("🎟️", "Nothing here yet",
                        {"upcoming": "You have no upcoming shows. Time to book a movie!",
                         "past": "Movies you have attended will appear here.",
                         "cancelled": "Cancelled bookings will appear here."}.get(scope, "No bookings yet."))
            if scope == "upcoming" and st.button("Browse movies", type="primary", key="bk_browse"):
                state.goto("movies")
            continue
        for b in data["items"]:
            key = f"{scope}_{b['id']}"
            seats = ", ".join(s["seat_id"] for s in b["seats"])
            st.markdown(f"""<div class="cb-booking"><div class="thumb" style="background-image:{poster_css(b['movie_snapshot'])}"></div>
<div style="flex:1"><div class="t">{esc(b['movie_snapshot']['title'])} {status_badge(b['status'])}</div>
<div class="m">🗓️ {esc(b['local_show_date'])} · 🕒 {esc(b['local_show_time'])} · 🏢 {esc(b['cinema_snapshot']['name'])} – {esc(b['screen_snapshot']['name'])}</div>
<div class="m">💺 {esc(seats)} · Ref <b>{esc(b['reference'])}</b></div></div>
<div style="text-align:right"><div class="cb-display" style="font-size:26px">{money(b['total'])}</div>
<div class="m">{'Refund ' + money(b['refund']['amount']) + ' · simulated/pending' if b.get('refund') else ''}</div></div></div>""",
                        unsafe_allow_html=True)
            a1, a2, a3, a4 = st.columns([1, 1, 1, 2.2])
            if a1.button("View ticket", key=f"view_{key}", width="stretch"):
                state.goto("ticket", booking_id=b["id"])
            with a2.popover("Details", width="stretch"):
                render_ticket(b)
                pdf_download(b, key)
            if b["status"] == "confirmed" and b.get("is_upcoming"):
                if b["can_cancel"]:
                    with a3.popover("Cancel", width="stretch"):
                        st.markdown(f"**Cancel {b['reference']}?**")
                        st.caption(f"{b['cancel_reason']}. A simulated refund of {policy.get('refund_percent', 0)}% "
                                   f"({money(b['total'] * policy.get('refund_percent', 0) / 100)}) will be recorded as "
                                   "pending — no real money is moved.")
                        reason = st.text_input("Reason (optional)", key=f"reason_{key}", max_chars=200)
                        if st.button("Yes, cancel booking", key=f"cancel_{key}", type="primary"):
                            res = call(api.post, f"/api/bookings/{b['id']}/cancel", {"reason": reason or None})
                            if res:
                                state.flash(f"Booking {b['reference']} cancelled. Seats were released.", "info")
                                st.rerun()
                else:
                    a3.button("Cancel", key=f"nocancel_{key}", disabled=True, help=b["cancel_reason"], width="stretch")
            if b.get("can_review"):
                with a4.popover("⭐ Rate this movie"):
                    with st.form(f"rv_{key}"):
                        rating = st.slider("Rating", 1, 5, 4)
                        comment = st.text_area("Comment", max_chars=600)
                        if st.form_submit_button("Submit", type="primary"):
                            if call(api.post, f"/api/movies/{b['movie_snapshot']['movie_id']}/reviews",
                                    {"rating": rating, "comment": comment}):
                                state.flash("Thanks for your review!")
                                st.rerun()
        if data["pages"] > 1:
            p1, p2, p3 = st.columns([1, 2, 1])
            if p1.button("← Newer" if scope != "upcoming" else "← Previous", key=f"prev_{scope}", disabled=page <= 1):
                st.session_state[page_key] = page - 1
                st.rerun()
            p2.markdown(f"<div style='text-align:center'>Page {page} of {data['pages']}</div>", unsafe_allow_html=True)
            if p3.button("Next →", key=f"next_{scope}", disabled=page >= data["pages"]):
                st.session_state[page_key] = page + 1
                st.rerun()
