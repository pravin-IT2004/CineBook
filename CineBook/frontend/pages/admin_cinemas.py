import pandas as pd
import streamlit as st

from components import seat_map
from components.ui import badge, call, esc, page_header
from services import api_client as api
from services import state

state.require_admin()
page_header("Cinemas & Screens", "Manage venues, auditoriums and seat layouts.", "Administration")

cinemas = call(api.get, "/api/admin/cinemas")
if cinemas is None:
    st.stop()

for c in cinemas:
    with st.expander(f"🏢 {c['name']} · {c['city']} · {len(c['screens'])} screen(s)"
                     + ("" if c.get("is_active", True) else " · INACTIVE")):
        st.markdown(f"<span class='cb-muted'>{esc(c.get('address') or '')}</span><br/>"
                    + " ".join(badge(a, "grey") for a in c.get("amenities", [])), unsafe_allow_html=True)
        if c["screens"]:
            st.dataframe(pd.DataFrame([{"Screen": s["name"], "Type": s["screen_type"], "Capacity": s["capacity"],
                                        **{k.title(): v for k, v in s["category_counts"].items()},
                                        "Prices": ", ".join(f"{k}: {v:g}" for k, v in s["default_prices"].items()),
                                        "Active": s.get("is_active", True)} for s in c["screens"]]),
                         hide_index=True, width="stretch")
        with st.form(f"cin_{c['id']}"):
            e1, e2, e3 = st.columns([2, 1.2, 1])
            name = e1.text_input("Name", value=c["name"])
            city = e2.text_input("City", value=c["city"])
            active = e3.toggle("Active", value=c.get("is_active", True))
            address = st.text_input("Address", value=c.get("address") or "")
            amenities = st.text_input("Amenities (comma separated)", value=", ".join(c.get("amenities", [])))
            if st.form_submit_button("Save cinema"):
                if call(api.put, f"/api/admin/cinemas/{c['id']}", {"name": name, "city": city, "address": address,
                        "is_active": active, "amenities": [a.strip() for a in amenities.split(",") if a.strip()]}):
                    state.flash("Cinema updated.")
                    st.rerun()
        with st.popover("🗑️ Delete cinema"):
            st.caption("Only cinemas without showtimes can be deleted. Otherwise deactivate them.")
            if st.button("Confirm delete", key=f"delc_{c['id']}", type="primary"):
                if call(api.delete, f"/api/admin/cinemas/{c['id']}"):
                    state.flash("Cinema deleted.", "info")
                    st.rerun()

st.markdown("### Add a cinema")
with st.form("new_cinema", clear_on_submit=True):
    n1, n2, n3 = st.columns([2, 1, 1])
    name = n1.text_input("Cinema name *")
    code = n2.text_input("Code * (A-Z, 0-9, -)", max_chars=12).strip().upper()
    city = n3.text_input("City *")
    address = st.text_input("Address")
    amenities = st.text_input("Amenities (comma separated)", placeholder="Dolby Atmos, Parking, Food court")
    if st.form_submit_button("Create cinema", type="primary"):
        if call(api.post, "/api/admin/cinemas", {"name": name, "code": code, "city": city, "address": address,
                "amenities": [a.strip() for a in amenities.split(",") if a.strip()]}):
            state.flash(f"Cinema {name} created.")
            st.rerun()

st.markdown("### Screens & seat layouts")
if not cinemas:
    st.info("Create a cinema first.")
    st.stop()

mode = st.radio("Action", ["Add a screen", "Edit a screen"], horizontal=True, key="sc_mode")
all_screens = [(c, s) for c in cinemas for s in c["screens"]]
existing = None
if mode == "Edit a screen":
    if not all_screens:
        st.caption("No screens yet.")
        st.stop()
    existing_pair = st.selectbox("Screen", all_screens, format_func=lambda p: f"{p[0]['name']} – {p[1]['name']}")
    cinema, existing = existing_pair
else:
    cinema = st.selectbox("Cinema", cinemas, format_func=lambda c: c["name"], key="sc_cinema")

layout = (existing or {}).get("layout") or {
    "rows": [{"row": r, "seats": 12, "category": "regular"} for r in "ABCDE"]
    + [{"row": r, "seats": 12, "category": "premium"} for r in "FG"] + [{"row": "H", "seats": 8, "category": "recliner"}],
    "aisles_after": [3, 9], "blocked_seats": []}
key = existing["id"] if existing else f"new_{cinema['id']}"
s1, s2 = st.columns([2, 1])
sc_name = s1.text_input("Screen name", value=(existing or {}).get("name", ""), key=f"scn_{key}")
sc_type = s2.selectbox("Screen type", ["2D", "3D", "IMAX", "4DX", "Dolby Atmos"],
                       index=["2D", "3D", "IMAX", "4DX", "Dolby Atmos"].index((existing or {}).get("screen_type", "2D")),
                       key=f"sct_{key}")
st.caption("Seat layout — one line per row (front row first). Categories: regular, premium, recliner.")
rows_df = st.data_editor(pd.DataFrame(layout["rows"]), num_rows="dynamic", key=f"rows_{key}", width="stretch",
                         column_config={
                             "row": st.column_config.TextColumn("Row", max_chars=2, required=True),
                             "seats": st.column_config.NumberColumn("Seats", min_value=1, max_value=40, required=True),
                             "category": st.column_config.SelectboxColumn("Category", options=["regular", "premium", "recliner"],
                                                                          required=True)})
a1, a2 = st.columns(2)
aisles = a1.text_input("Aisle gaps after seat numbers", value=", ".join(str(a) for a in layout.get("aisles_after", [])),
                       key=f"ais_{key}")
blocked = a2.text_input("Blocked seats (never sold)", value=", ".join(layout.get("blocked_seats", [])),
                        key=f"blk_{key}")
prices = (existing or {}).get("default_prices") or {"regular": 180, "premium": 260, "recliner": 420}
p1, p2, p3 = st.columns(3)
pr = {"regular": p1.number_input("Regular price", 0.0, 10000.0, float(prices["regular"]), key=f"pr_{key}"),
      "premium": p2.number_input("Premium price", 0.0, 10000.0, float(prices["premium"]), key=f"pp_{key}"),
      "recliner": p3.number_input("Recliner price", 0.0, 10000.0, float(prices["recliner"]), key=f"pc_{key}")}

try:
    new_layout = {
        "rows": [{"row": str(r["row"]).strip().upper(), "seats": int(r["seats"]), "category": r["category"]}
                 for r in rows_df.to_dict("records") if r.get("row") and r.get("seats")],
        "aisles_after": [int(x) for x in aisles.replace(" ", "").split(",") if x],
        "blocked_seats": [x.strip().upper() for x in blocked.split(",") if x.strip()],
    }
    st.markdown("**Preview**")
    seat_map.static_preview(new_layout, pr)
except (ValueError, TypeError):
    new_layout = None
    st.error("Aisles must be comma-separated numbers and every row needs a label and seat count.")

if existing:
    st.caption("Layout changes apply to showtimes created afterwards. Existing showtimes keep their original layout, "
               "so sold seats are never affected.")
b1, b2 = st.columns([1, 1])
if b1.button("Save screen" if existing else "Create screen", type="primary", disabled=new_layout is None):
    body = {"name": sc_name, "screen_type": sc_type, "layout": new_layout, "default_prices": pr}
    res = (call(api.put, f"/api/admin/screens/{existing['id']}", body) if existing
           else call(api.post, "/api/admin/screens", {**body, "cinema_id": cinema["id"]}))
    if res:
        state.flash(f"Screen saved ({res['capacity']} sellable seats).")
        st.rerun()
if existing:
    with b2.popover("🗑️ Delete screen"):
        st.caption("Only screens without showtimes can be deleted.")
        if st.button("Confirm delete", key="del_screen", type="primary"):
            if call(api.delete, f"/api/admin/screens/{existing['id']}"):
                state.flash("Screen deleted.", "info")
                st.rerun()
