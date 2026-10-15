import streamlit as st

from components import seat_map
from components.ui import call, empty_state, esc, money, nice_date
from services import api_client as api
from services import state

showtime_id = st.query_params.get("showtime") or st.session_state.get("showtime_id")
if not showtime_id:
    empty_state("🎟️", "No showtime selected", "Choose a movie and showtime first.")
    if st.button("Browse movies", type="primary"):
        state.goto("movies")
    st.stop()
st.session_state.showtime_id = showtime_id
if st.session_state.get("seat_showtime") != showtime_id:
    st.session_state.seat_showtime = showtime_id
    st.session_state.selected_seats = []

state.require_customer()

show = call(api.get, f"/api/showtimes/{showtime_id}")
if not show:
    if st.button("← Back to movie"):
        state.goto("movie")
    st.stop()

top = st.columns([1, 5])
if top[0].button("← Back"):
    state.goto("movie", movie_id=show["movie"]["id"])
st.markdown(f"<h1 style='margin:0'>{esc(show['movie']['title'])}</h1>", unsafe_allow_html=True)
st.markdown(f"<div class='cb-muted'>🏢 {esc(show['cinema_name'])} · {esc(show['screen_name'])} · "
            f"🗓️ {esc(nice_date(show['local_date']))} · 🕒 {esc(show['local_time'])} · {esc(show['language'])} · {esc(show['format'])}"
            f"</div>", unsafe_allow_html=True)
st.write("")

with st.spinner("Checking live seat availability..."):
    data = call(api.get, f"/api/showtimes/{showtime_id}/seats")
if not data:
    st.stop()

available = {s["seat_id"] for r in data["rows"] for s in r["seats"] if s["status"] == "available"}
gone = [s for s in st.session_state.selected_seats if s not in available]
if gone:
    st.session_state.selected_seats = [s for s in st.session_state.selected_seats if s in available]
    st.warning(f"These seats are no longer available and were removed from your selection: {', '.join(gone)}")

hold = data.get("my_hold")
if hold:
    with st.container(border=True):
        st.markdown(f"**🔵 You already have seats on hold:** {', '.join(hold['seats'])} "
                    f"(≈{hold['seconds_left'] // 60}m {hold['seconds_left'] % 60}s left).")
        h1, h2, _ = st.columns([1.2, 1.2, 2])
        if h1.button("Continue to checkout", type="primary", key="continue_hold"):
            state.goto("checkout", hold=hold)
        if h2.button("Release and choose again", key="release_hold"):
            call(api.delete, f"/api/holds/{hold['id']}")
            st.rerun()

grid_col, summary_col = st.columns([3.2, 1.2], gap="large")
with grid_col:
    seat_map.render(data)
    if msg := st.session_state.pop("seat_warning", None):
        st.warning(msg)
    if st.button("🔄 Refresh availability"):
        st.rerun()

with summary_col:
    selected = st.session_state.selected_seats
    rows_by_seat = {s["seat_id"]: r for r in data["rows"] for s in r["seats"]}
    st.markdown("### Your selection")
    if not selected:
        st.markdown("<div class='cb-muted'>Tap available seats on the map to select them. "
                    f"Up to {data['max_seats_per_booking']} seats per booking.</div>", unsafe_allow_html=True)
    else:
        lines, total = {}, 0.0
        for sid in selected:
            r = rows_by_seat[sid]
            lines.setdefault(r["category"], []).append(sid)
            total += float(r["price"])
        for cat, seats in lines.items():
            price = data["prices"][cat]
            st.markdown(f"**{cat.title()}** × {len(seats)} @ {money(price)}  \n"
                        f"<span class='cb-muted'>{', '.join(sorted(seats))}</span>", unsafe_allow_html=True)
        st.divider()
        st.markdown(f"<div style='display:flex;justify-content:space-between;font-size:20px;font-weight:800'>"
                    f"<span>Total</span><span>{money(total)}</span></div>", unsafe_allow_html=True)
        st.caption(f"Final price is confirmed by the server. Seats are held for {data['hold_minutes']} minutes "
                   "while you check out.")
    if st.button("Hold seats & continue →", type="primary", width="stretch", disabled=not selected):
        try:
            new_hold = api.post("/api/holds", {"showtime_id": showtime_id, "seats": selected})
            st.session_state.selected_seats = []
            state.goto("checkout", hold=new_hold, applied_offer=None)
        except api.ApiError as err:
            if err.code == "seats_unavailable":
                taken = err.data.get("unavailable_seats", [])
                st.session_state.selected_seats = [s for s in selected if s not in taken]
                st.session_state["seat_warning"] = err.message
                st.rerun()
            else:
                st.error(err.message)
    if selected and st.button("Clear selection", width="stretch"):
        st.session_state.selected_seats = []
        st.rerun()
