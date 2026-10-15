import pandas as pd
import streamlit as st

from components.ticket import render_ticket
from components.ui import call, money, page_header
from services import api_client as api
from services import state

state.require_admin()
page_header("Bookings", "Search by reference, filter, inspect and cancel bookings.", "Administration")

movies = (call(api.get, "/api/admin/movies", params={"page_size": 100}) or {"items": []})["items"]
cinemas = call(api.get, "/api/admin/cinemas") or []
f1, f2, f3, f4, f5 = st.columns([1.3, 1, 1.3, 1.3, 1.4])
ref = f1.text_input("Booking reference", placeholder="CB-XXXXXXXX").strip().upper()
status = f2.selectbox("Status", ["All", "confirmed", "cancelled", "pending", "failed"])
movie = f3.selectbox("Movie", [None] + movies, format_func=lambda m: "All movies" if m is None else m["title"])
cinema = f4.selectbox("Cinema", [None] + cinemas, format_func=lambda c: "All cinemas" if c is None else c["name"])
rng = f5.date_input("Booked between", value=[])

params = {"reference": ref or None, "status": None if status == "All" else status,
          "movie_id": movie["id"] if movie else None, "cinema_id": cinema["id"] if cinema else None,
          "page": st.session_state.get("ab_page", 1), "page_size": 25}
if isinstance(rng, (list, tuple)) and len(rng) == 2:
    params["date_from"], params["date_to"] = rng[0].isoformat(), rng[1].isoformat()
data = call(api.get, "/api/admin/bookings", params=params)
if data is None:
    st.stop()
if not data["items"]:
    st.info("No bookings match these filters. (Customer bookings appear here once customers start booking.)")
    st.stop()

df = pd.DataFrame([{"Reference": b["reference"], "Status": b["status"], "Customer": b["user_snapshot"]["name"],
                    "Movie": b["movie_snapshot"]["title"], "Show": f"{b['local_show_date']} {b['local_show_time']}",
                    "Cinema": b["cinema_snapshot"]["name"], "Seats": ", ".join(s["seat_id"] for s in b["seats"]),
                    "Total": b["total"], "Coupon": (b.get("offer") or {}).get("code", "")} for b in data["items"]])
st.dataframe(df, hide_index=True, width="stretch",
             column_config={"Total": st.column_config.NumberColumn(format="%.2f")})
p = params["page"]
st.caption(f"{data['total']} booking(s) · page {p} of {data['pages']}")
n1, n2, _ = st.columns([1, 1, 4])
if n1.button("← Prev", disabled=p <= 1):
    st.session_state.ab_page = p - 1
    st.rerun()
if n2.button("Next →", disabled=p >= data["pages"]):
    st.session_state.ab_page = p + 1
    st.rerun()

st.markdown("### Booking details")
b = st.selectbox("Select booking", data["items"], format_func=lambda b: f"{b['reference']} · {b['movie_snapshot']['title']}"
                 f" · {b['status']}")
st.markdown(f"**Customer:** {b['user_snapshot']['name']} ({b['user_snapshot']['email']}) · "
            f"**Booked:** {b['created_at'][:16].replace('T', ' ')} UTC · **Total:** {money(b['total'])}")
if b.get("failure_reason"):
    st.warning(f"Failure reason: {b['failure_reason']}")
if b["status"] in ("confirmed", "cancelled"):
    render_ticket(b)
with st.expander("Status history"):
    st.dataframe(pd.DataFrame(b.get("status_history", [])), hide_index=True, width="stretch")
if b["status"] == "confirmed" and b.get("is_upcoming"):
    with st.popover("Cancel booking (admin)"):
        st.caption("Admin cancellations bypass the customer cut-off and record a simulated 100% refund as pending.")
        reason = st.text_input("Reason", value="Cancelled by cinema")
        if st.button("Confirm cancellation", type="primary"):
            if call(api.post, f"/api/admin/bookings/{b['id']}/cancel", {"reason": reason}):
                state.flash(f"{b['reference']} cancelled and seats released.", "info")
                st.rerun()
