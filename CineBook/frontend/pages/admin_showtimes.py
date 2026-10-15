from datetime import date, time, timedelta

import pandas as pd
import streamlit as st

from components.ui import call, page_header
from services import api_client as api
from services import state

state.require_admin()
page_header("Showtimes", "Schedule shows, set prices and publish them.", "Administration")

movies = (call(api.get, "/api/admin/movies", params={"page_size": 100}) or {"items": []})["items"]
cinemas = call(api.get, "/api/admin/cinemas") or []
schedulable = [m for m in movies if m["status"] != "archived"]

tab_list, tab_new, tab_bulk = st.tabs(["📅 Schedule", "➕ Single show", "🗂️ Bulk schedule"])

with tab_list:
    f1, f2, f3, f4 = st.columns([1.5, 1.5, 1.4, 1])
    fm = f1.selectbox("Movie", [None] + movies, format_func=lambda m: "All movies" if m is None else m["title"])
    fc = f2.selectbox("Cinema", [None] + cinemas, format_func=lambda c: "All cinemas" if c is None else c["name"])
    fd = f3.date_input("From date", value=None)
    upcoming = f4.toggle("Upcoming only", value=True)
    page = st.session_state.get("st_page", 1)
    data = call(api.get, "/api/admin/showtimes", params={
        "movie_id": fm["id"] if fm else None, "cinema_id": fc["id"] if fc else None,
        "date_from": fd.isoformat() if fd else None, "upcoming_only": str(upcoming).lower(), "page": page,
        "page_size": 25})
    if data and data["items"]:
        df = pd.DataFrame([{"Date": s["local_date"], "Time": s["local_time"], "Movie": s.get("movie_title"),
                            "Cinema": s.get("cinema_name"), "Screen": s.get("screen_name"), "Lang": s["language"],
                            "Format": s["format"], "Booked": s["seats_booked"], "Capacity": s["capacity"],
                            "Occupancy": s["occupancy_percent"], "Published": s["is_published"]} for s in data["items"]])
        st.dataframe(df, hide_index=True, width="stretch", column_config={
            "Occupancy": st.column_config.ProgressColumn("Occupancy", format="%.0f%%", min_value=0, max_value=100)})
        st.caption(f"{data['total']} show(s) · page {page} of {data['pages']}")
        n1, n2, _ = st.columns([1, 1, 4])
        if n1.button("← Prev", disabled=page <= 1):
            st.session_state.st_page = page - 1
            st.rerun()
        if n2.button("Next →", disabled=page >= data["pages"]):
            st.session_state.st_page = page + 1
            st.rerun()

        st.markdown("#### Edit a show")
        pick = st.selectbox("Show", data["items"], format_func=lambda s: f"{s['local_date']} {s['local_time']} · "
                            f"{s.get('movie_title')} · {s.get('cinema_name')} {s.get('screen_name')}", key="st_pick")
        with st.form(f"edit_{pick['id']}"):
            p1, p2, p3, p4 = st.columns(4)
            regular = p1.number_input("Regular", 0.0, 10000.0, float(pick["prices"]["regular"]))
            premium = p2.number_input("Premium", 0.0, 10000.0, float(pick["prices"]["premium"]))
            recliner = p3.number_input("Recliner", 0.0, 10000.0, float(pick["prices"]["recliner"]))
            published = p4.toggle("Published", value=pick["is_published"])
            st.caption("Price changes apply to new bookings only; confirmed bookings keep the price they were sold at.")
            if st.form_submit_button("Save show", type="primary"):
                if call(api.put, f"/api/admin/showtimes/{pick['id']}", {"is_published": published, "prices": {
                        "regular": regular, "premium": premium, "recliner": recliner}}):
                    state.flash("Show updated.")
                    st.rerun()
        with st.popover("🗑️ Delete show"):
            st.caption("Shows with active bookings cannot be deleted — unpublish them instead.")
            if st.button("Confirm delete", type="primary", key="st_del"):
                if call(api.delete, f"/api/admin/showtimes/{pick['id']}"):
                    state.flash("Show deleted.", "info")
                    st.rerun()
    elif data is not None:
        st.info("No showtimes match these filters.")


def screen_picker(prefix: str):
    c = st.selectbox("Cinema", cinemas, format_func=lambda c: c["name"], key=f"{prefix}_cin")
    screens = [s for s in (c or {}).get("screens", []) if s.get("is_active", True)]
    s = st.selectbox("Screen", screens, format_func=lambda s: f"{s['name']} ({s['screen_type']}, {s['capacity']} seats)",
                     key=f"{prefix}_scr")
    return c, s


def price_inputs(screen: dict | None, prefix: str) -> dict:
    d = (screen or {}).get("default_prices") or {"regular": 180, "premium": 260, "recliner": 420}
    c1, c2, c3 = st.columns(3)
    return {"regular": c1.number_input("Regular price", 0.0, 10000.0, float(d["regular"]), key=f"{prefix}_r"),
            "premium": c2.number_input("Premium price", 0.0, 10000.0, float(d["premium"]), key=f"{prefix}_p"),
            "recliner": c3.number_input("Recliner price", 0.0, 10000.0, float(d["recliner"]), key=f"{prefix}_c")}


with tab_new:
    if not schedulable or not cinemas:
        st.info("You need at least one movie and one cinema with a screen.")
    else:
        m = st.selectbox("Movie", schedulable, format_func=lambda m: m["title"], key="one_movie")
        c, s = screen_picker("one")
        d1, d2, d3, d4 = st.columns(4)
        day = d1.date_input("Date", value=date.today() + timedelta(days=1), min_value=date.today(), key="one_date")
        at = d2.time_input("Start time", value=time(18, 30), step=900, key="one_time")
        lang = d3.selectbox("Language", m["languages"], key="one_lang")
        fmt = d4.text_input("Format", value=(s or {}).get("screen_type", "2D"), key="one_fmt")
        prices = price_inputs(s, "one")
        pub = st.toggle("Publish immediately", value=True, key="one_pub")
        if st.button("Create show", type="primary", disabled=s is None):
            res = call(api.post, "/api/admin/showtimes", {
                "movie_id": m["id"], "screen_id": s["id"], "start_time": f"{day.isoformat()}T{at.strftime('%H:%M')}:00",
                "language": lang, "format": fmt, "prices": prices, "is_published": pub})
            if res:
                state.flash(f"Show created for {res['local_date']} at {res['local_time']}.")
                st.rerun()

with tab_bulk:
    if not schedulable or not cinemas:
        st.info("You need at least one movie and one cinema with a screen.")
    else:
        m = st.selectbox("Movie", schedulable, format_func=lambda m: m["title"], key="bulk_movie")
        c, s = screen_picker("bulk")
        b1, b2 = st.columns(2)
        start = b1.date_input("First date", value=date.today() + timedelta(days=1), min_value=date.today(), key="bulk_d1")
        days = b2.number_input("Number of days", 1, 31, 7, key="bulk_days")
        times = st.text_input("Start times (24h, comma separated)", value="10:00, 14:00, 18:00, 21:30", key="bulk_times")
        l1, l2 = st.columns(2)
        lang = l1.selectbox("Language", m["languages"], key="bulk_lang")
        fmt = l2.text_input("Format", value=(s or {}).get("screen_type", "2D"), key="bulk_fmt")
        prices = price_inputs(s, "bulk")
        if st.button("Create shows", type="primary", disabled=s is None):
            res = call(api.post, "/api/admin/showtimes/bulk", {
                "movie_id": m["id"], "screen_id": s["id"],
                "dates": [(start + timedelta(days=i)).isoformat() for i in range(int(days))],
                "times": [t.strip() for t in times.split(",") if t.strip()], "language": lang, "format": fmt,
                "prices": prices, "is_published": True})
            if res:
                st.success(f"{res['created']} show(s) created.")
                if res["skipped"]:
                    st.warning(f"{len(res['skipped'])} skipped:")
                    st.dataframe(pd.DataFrame(res["skipped"]), hide_index=True, width="stretch")
