from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from components.ui import call, page_header, parse_dt
from services import api_client as api
from services import state

state.require_admin()
page_header("Offers", "Create and manage coupon codes. All rules are enforced by the backend.", "Administration")

offers = call(api.get, "/api/admin/offers")
if offers is None:
    st.stop()
if offers:
    st.dataframe(pd.DataFrame([{
        "Code": o["code"], "Title": o["title"], "Discount": o["label"], "Min value": o.get("min_booking_value", 0),
        "Active": o["is_active"], "Starts": parse_dt(o["start_date"]).strftime("%d %b %Y"),
        "Ends": parse_dt(o["end_date"]).strftime("%d %b %Y"), "Used": o.get("used_count", 0),
        "Limit": o.get("usage_limit") or "∞", "Per customer": o.get("per_user_limit", 1),
        "Discount given": o.get("discount_given", 0)} for o in offers]), hide_index=True, width="stretch")
else:
    st.info("No offers yet.")


def offer_form(o: dict | None, key: str) -> None:
    e = o or {}
    now = datetime.now()
    with st.form(key, clear_on_submit=o is None):
        c1, c2 = st.columns([1, 2])
        code = c1.text_input("Code *", value=e.get("code", ""), disabled=o is not None, max_chars=20,
                             help="Letters and numbers only").strip().upper()
        title = c2.text_input("Title *", value=e.get("title", ""), max_chars=80)
        desc = st.text_input("Description", value=e.get("description", ""), max_chars=300)
        d1, d2, d3, d4 = st.columns(4)
        dtype = d1.selectbox("Type", ["percent", "fixed"], index=["percent", "fixed"].index(e.get("discount_type", "percent")))
        value = d2.number_input("Value (% or amount) *", 0.0, 100000.0, float(e.get("discount_value", 10)))
        minv = d3.number_input("Min. booking value", 0.0, 100000.0, float(e.get("min_booking_value", 0)))
        maxd = d4.number_input("Max. discount (0 = none)", 0.0, 100000.0, float(e.get("max_discount") or 0))
        s1, s2, s3, s4 = st.columns(4)
        start = parse_dt(e["start_date"]) if e.get("start_date") else now
        end = parse_dt(e["end_date"]) if e.get("end_date") else now + timedelta(days=30)
        sd = s1.date_input("Start date", value=start.date())
        ed = s2.date_input("End date", value=end.date())
        limit = s3.number_input("Total usage limit (0 = unlimited)", 0, 1_000_000, int(e.get("usage_limit") or 0))
        per = s4.number_input("Uses per customer", 1, 100, int(e.get("per_user_limit", 1)))
        active = st.toggle("Active", value=e.get("is_active", True))
        if st.form_submit_button("Save offer" if o else "Create offer", type="primary"):
            body = {"title": title, "description": desc, "discount_type": dtype, "discount_value": value,
                    "min_booking_value": minv, "start_date": f"{sd.isoformat()}T00:00:00",
                    "end_date": f"{ed.isoformat()}T23:59:59", "per_user_limit": int(per), "is_active": active}
            if o:
                body.update({"max_discount": maxd, "usage_limit": int(limit)})
                res = call(api.put, f"/api/admin/offers/{o['id']}", body)
            else:
                body.update({"code": code, "max_discount": maxd or None, "usage_limit": int(limit) or None})
                res = call(api.post, "/api/admin/offers", body)
            if res:
                state.flash(f"Offer {res['code']} saved.")
                st.rerun()


t1, t2 = st.tabs(["➕ New offer", "✏️ Edit / deactivate"])
with t1:
    offer_form(None, "new_offer")
with t2:
    if offers:
        pick = st.selectbox("Offer", offers, format_func=lambda o: f"{o['code']} · {o['title']}")
        if pick["is_active"] and st.button("Deactivate now"):
            if call(api.post, f"/api/admin/offers/{pick['id']}/deactivate"):
                state.flash(f"{pick['code']} deactivated.", "info")
                st.rerun()
        offer_form(pick, f"edit_{pick['id']}")
