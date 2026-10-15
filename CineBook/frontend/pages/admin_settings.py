import pandas as pd
import streamlit as st

from components.ui import call, fmt_dt, page_header
from services import api_client as api
from services import state

state.require_admin()
page_header("Settings & Audit", "Booking and cancellation policies, system health and the audit trail.",
            "Administration")

health = call(api.get, "/api/health", auth=False)
if health:
    h1, h2, h3 = st.columns(3)
    h1.metric("API", health["status"].upper())
    h2.metric("MongoDB", health["database"])
    h3.metric("Transactions", "enabled" if health.get("transactions_enabled") else "atomic ops mode",
              help="Standalone MongoDB has no multi-document transactions; CineBook then relies on unique indexes, "
                   "atomic updates and compensation.")

p = call(api.get, "/api/admin/settings")
if p:
    st.markdown("### Booking policy")
    with st.form("policy"):
        c1, c2, c3 = st.columns(3)
        hold = c1.number_input("Seat hold duration (minutes)", 1, 30, int(p["hold_minutes"]))
        max_seats = c2.number_input("Max seats per booking", 1, 20, int(p["max_seats_per_booking"]))
        cutoff = c3.number_input("Online booking closes (minutes before show)", 0, 240, int(p["booking_cutoff_minutes"]))
        c4, c5, c6 = st.columns(3)
        canc = c4.toggle("Allow customer cancellations", value=p["cancellations_enabled"])
        ccut = c5.number_input("Cancellation cut-off (hours before show)", 0.0, 168.0, float(p["cancellation_cutoff_hours"]))
        refund = c6.slider("Simulated refund %", 0, 100, int(p["refund_percent"]))
        st.markdown("Default seat prices (used for new screens without their own prices)")
        d1, d2, d3, d4 = st.columns(4)
        dp = p["default_prices"]
        prices = {"regular": d1.number_input("Regular", 0.0, 10000.0, float(dp["regular"])),
                  "premium": d2.number_input("Premium", 0.0, 10000.0, float(dp["premium"])),
                  "recliner": d3.number_input("Recliner", 0.0, 10000.0, float(dp["recliner"]))}
        buffer = d4.number_input("Cleaning buffer between shows (min)", 0, 120, int(p["cleaning_buffer_minutes"]))
        if st.form_submit_button("Save policy", type="primary"):
            if call(api.put, "/api/admin/settings", {
                    "hold_minutes": hold, "max_seats_per_booking": max_seats, "booking_cutoff_minutes": cutoff,
                    "cancellations_enabled": canc, "cancellation_cutoff_hours": ccut, "refund_percent": refund,
                    "default_prices": prices, "cleaning_buffer_minutes": buffer}):
                state.flash("Policy saved.")
                st.rerun()

st.markdown("### Maintenance")
if st.button("Release expired seat holds now"):
    res = call(api.post, "/api/admin/maintenance/cleanup")
    if res:
        st.success(f"Released {res['released_locks']} expired seat lock(s); {res['failed_bookings']} stuck booking(s) "
                   "marked failed.")

st.markdown("### Audit log")
action = st.text_input("Filter by action prefix", placeholder="e.g. movie., offer., booking.")
page = st.session_state.get("audit_page", 1)
logs = call(api.get, "/api/admin/audit-logs", params={"action": action or None, "page": page, "page_size": 30})
if logs and logs["items"]:
    st.dataframe(pd.DataFrame([{"When": fmt_dt(x["created_at"], "%d %b %Y %I:%M %p"), "Who": x["actor_email"],
                                "Action": x["action"], "Entity": x["entity"], "Details": str(x.get("details") or "")}
                               for x in logs["items"]]), hide_index=True, width="stretch")
    n1, n2, _ = st.columns([1, 1, 4])
    if n1.button("← Prev", disabled=page <= 1):
        st.session_state.audit_page = page - 1
        st.rerun()
    if n2.button("Next →", disabled=page >= logs["pages"]):
        st.session_state.audit_page = page + 1
        st.rerun()
elif logs is not None:
    st.caption("No audit entries yet.")
