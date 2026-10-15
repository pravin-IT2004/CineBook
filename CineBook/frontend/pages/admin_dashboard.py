from datetime import date, timedelta

import pandas as pd
import streamlit as st

from components import charts
from components.ui import call, money, page_header, stat_card
from services import api_client as api
from services import state

state.require_admin()
page_header("Dashboard", "Live analytics computed from the MongoDB booking data.", "Administration")

movies = (call(api.get, "/api/admin/movies", params={"page_size": 100}) or {"items": []})["items"]
cinemas = call(api.get, "/api/admin/cinemas") or []
with st.container(border=True):
    f1, f2, f3, f4 = st.columns([1.6, 1.4, 1.4, 1])
    rng = f1.date_input("Booking date range", value=(date.today() - timedelta(days=30), date.today()),
                        key="dash_range")
    movie = f2.selectbox("Movie", ["All movies"] + [m["title"] for m in movies], key="dash_movie")
    cinema = f3.selectbox("Cinema", ["All cinemas"] + [c["name"] for c in cinemas], key="dash_cinema")
    status = f4.selectbox("Status", ["All", "confirmed", "cancelled", "pending", "failed"], key="dash_status")
    use_range = st.checkbox("Filter by booking date", value=False, key="dash_use_range",
                            help="Unticked = all-time figures")

params = {
    "movie_id": next((m["id"] for m in movies if m["title"] == movie), None),
    "cinema_id": next((c["id"] for c in cinemas if c["name"] == cinema), None),
    "status": None if status == "All" else status,
}
if use_range and isinstance(rng, (list, tuple)) and len(rng) == 2:
    params["date_from"], params["date_to"] = rng[0].isoformat(), rng[1].isoformat()

with st.spinner("Crunching numbers..."):
    a = call(api.get, "/api/admin/analytics", params=params)
if not a:
    st.stop()
c, s = a["counts"], a["sales"]

row1 = st.columns(4)
with row1[0]:
    stat_card("Customers", c["customers"], "registered accounts")
with row1[1]:
    stat_card("Movies", c["movies"], f"{c['published_movies']} published")
with row1[2]:
    stat_card("Cinemas · Screens", f"{c['cinemas']} · {c['screens']}", "venues and auditoriums")
with row1[3]:
    stat_card("Showtimes", c["showtimes"], f"{c['upcoming_showtimes']} upcoming")
st.write("")
row2 = st.columns(4)
with row2[0]:
    stat_card("Bookings", c["bookings"] if not params["status"] else sum(a["status_counts"].values()),
              f"{a['status_counts']['confirmed']} confirmed · {a['status_counts']['cancelled']} cancelled")
with row2[1]:
    stat_card("Tickets sold", s["tickets"], f"avg occupancy {s['average_occupancy_percent']}%")
with row2[2]:
    stat_card("Gross booking value", money(s["gross"]), f"net {money(s['net'])} after discounts")
with row2[3]:
    stat_card("Discounts given", money(s["discount"]), f"avg booking {money(s['average_booking_value'])}")
st.caption("Booking value = ticket prices of confirmed bookings. No payments are processed online, so this is "
           "not collected revenue.")

st.write("")
g1, g2 = st.columns([2, 1])
with g1:
    charts.trend(a["daily_trend"], "date", "Daily bookings")
with g2:
    sc = a["status_counts"]
    charts.donut(list(sc), list(sc.values()), "Bookings by status", charts.STATUS_COLORS)

g3, g4 = st.columns(2)
with g3:
    charts.bar(a["top_movies"], "movie", "tickets", "Most-booked movies (tickets)", horizontal=True)
with g4:
    charts.bar(a["seat_categories"], "category", "tickets", "Seat-category sales", color="category",
               color_map=charts.CAT_COLORS)

g5, g6 = st.columns(2)
with g5:
    charts.bar(a["popular_showtimes"], "time", "tickets", "Most popular showtimes (tickets by start time)")
with g6:
    charts.trend(a["monthly_trend"], "month", "Monthly bookings")

st.markdown("### Occupancy per show")
if a["occupancy"]:
    df = pd.DataFrame(a["occupancy"])[["movie", "cinema", "start", "booked", "capacity", "occupancy_percent"]]
    df["start"] = pd.to_datetime(df["start"]).dt.strftime("%d %b %Y %I:%M %p")
    st.dataframe(df, hide_index=True, width="stretch", column_config={
        "occupancy_percent": st.column_config.ProgressColumn("Occupancy", format="%.1f%%", min_value=0, max_value=100),
        "start": "Show", "booked": "Booked", "capacity": "Capacity", "movie": "Movie", "cinema": "Cinema"})
else:
    st.caption("No shows with bookings yet.")

st.markdown("### Coupon usage")
if a["coupons"]:
    st.dataframe(pd.DataFrame(a["coupons"]), hide_index=True, width="stretch", column_config={
        "code": "Code", "uses": "Uses", "discount": st.column_config.NumberColumn("Discount given", format="%.2f"),
        "revenue": st.column_config.NumberColumn("Booking value after discount", format="%.2f")})
else:
    st.caption("No coupons have been redeemed yet.")
