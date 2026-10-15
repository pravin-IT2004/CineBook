import streamlit as st

from components.ticket import pdf_download, render_ticket
from components.ui import call, empty_state, page_header
from services import api_client as api
from services import state

state.require_login()
booking_id = st.query_params.get("booking") or st.session_state.get("booking_id")
if not booking_id:
    empty_state("🎟️", "No ticket selected", "Open a booking from My Bookings to see its ticket.")
    st.stop()

b = call(api.get, f"/api/bookings/{booking_id}")
if not b:
    st.stop()

page_header("Your ticket", f"Booking reference {b['reference']}", "E-ticket")
if b["status"] == "confirmed" and b.get("is_upcoming"):
    st.success("🎉 Booking confirmed. Show the QR code at the cinema entrance. A copy is always available under "
               "My Bookings.")
elif b["status"] == "cancelled":
    st.warning("This booking was cancelled and the ticket is no longer valid for entry.")

render_ticket(b)
st.write("")
c1, c2, c3, _ = st.columns([1.3, 1.2, 1.2, 2])
with c1:
    pdf_download(b, "ticket")
if c2.button("🎟️ My bookings", width="stretch"):
    state.goto("bookings")
if c3.button("🎞️ Book another", width="stretch"):
    state.goto("movies")
