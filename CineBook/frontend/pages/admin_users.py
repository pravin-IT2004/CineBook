import pandas as pd
import streamlit as st

from components.ui import call, page_header
from services import api_client as api
from services import state

me = state.require_admin()
page_header("Users", "Customer and administrator accounts.", "Administration")

c1, c2 = st.columns([2, 1])
q = c1.text_input("Search name or e-mail")
role = c2.selectbox("Role", ["All", "customer", "admin"])
page = st.session_state.get("au_page", 1)
data = call(api.get, "/api/admin/users", params={"q": q or None, "role": None if role == "All" else role,
                                                 "page": page, "page_size": 25})
if data is None:
    st.stop()
if not data["items"]:
    st.info("No users found. Customers appear here after they register.")
    st.stop()
st.dataframe(pd.DataFrame([{"Name": u["name"], "E-mail": u["email"], "Role": u["role"], "Active": u["is_active"],
                            "Confirmed bookings": u["confirmed_bookings"], "Booking value": u["booking_value"],
                            "Joined": (u.get("created_at") or "")[:10]} for u in data["items"]]),
             hide_index=True, width="stretch")
st.caption(f"{data['total']} user(s) · page {page} of {data['pages']}")
n1, n2, _ = st.columns([1, 1, 4])
if n1.button("← Prev", disabled=page <= 1):
    st.session_state.au_page = page - 1
    st.rerun()
if n2.button("Next →", disabled=page >= data["pages"]):
    st.session_state.au_page = page + 1
    st.rerun()

st.markdown("### Manage account")
u = st.selectbox("User", data["items"], format_func=lambda u: f"{u['name']} <{u['email']}> · {u['role']}")
if u["id"] == me["id"]:
    st.caption("You cannot deactivate or demote your own account.")
else:
    a1, a2 = st.columns(2)
    if a1.button("Deactivate account" if u["is_active"] else "Reactivate account", width="stretch"):
        if call(api.put, f"/api/admin/users/{u['id']}", {"is_active": not u["is_active"]}):
            state.flash("Account status updated.")
            st.rerun()
    new_role = "admin" if u["role"] == "customer" else "customer"
    with a2.popover(f"Change role to {new_role}", width="stretch"):
        st.warning("Administrators can manage the whole cinema. Only promote trusted staff.")
        if st.button("Confirm role change", type="primary"):
            if call(api.put, f"/api/admin/users/{u['id']}", {"role": new_role}):
                state.flash("Role updated.")
                st.rerun()
