from datetime import date

import streamlit as st

from components.posters import poster_css
from components.ui import badge, call, empty_state, esc, fmt_dt
from services import api_client as api
from services import state

movie_id = st.query_params.get("movie") or st.session_state.get("movie_id")
if not movie_id:
    empty_state("🎬", "No movie selected", "Pick a movie from the catalogue first.")
    if st.button("Browse movies", type="primary"):
        state.goto("movies")
    st.stop()
st.session_state.movie_id = movie_id

with st.spinner("Loading movie..."):
    m = call(api.get, f"/api/movies/{movie_id}")
if not m:
    st.stop()

if st.button("← Back to movies"):
    state.goto("movies")

left, right = st.columns([1, 2.4], gap="large")
with left:
    st.markdown(f'<div class="cb-card"><div class="cb-poster" style="background-image:{poster_css(m)}"></div></div>',
                unsafe_allow_html=True)
with right:
    st.markdown(badge(m["status_label"], "solid" if m["status"] == "now_showing" else "blue")
                + badge(m.get("certificate", ""), "grey") + badge(f"{m['duration_minutes']} min", "grey"),
                unsafe_allow_html=True)
    st.markdown(f"<h1 style='margin:4px 0 6px'>{esc(m['title'])}</h1>", unsafe_allow_html=True)
    ratings = []
    if m.get("rating"):
        ratings.append(f"⭐ **{m['rating']:.1f}/10** critics")
    if m.get("avg_user_rating"):
        ratings.append(f"🎟️ **{m['avg_user_rating']:.1f}/5** from {m['review_count']} audience review(s)")
    if ratings:
        st.markdown(" · ".join(ratings))
    st.markdown(" ".join(badge(g, "red") for g in m["genres"]) + " " + " ".join(badge(lang, "blue") for lang in m["languages"]),
                unsafe_allow_html=True)
    st.write(m.get("description") or "")
    rel = fmt_dt(m.get("release_date"), "%d %B %Y") if m.get("release_date") else "—"
    st.markdown(f"""<div class="cb-kv">
<div class="k">Release</div><div>{esc(rel)}</div>
<div class="k">Director</div><div>{esc(m.get('director') or '—')}</div>
<div class="k">Cast</div><div>{esc(', '.join(m.get('cast') or []) or '—')}</div></div>""", unsafe_allow_html=True)
    st.write("")
    if state.logged_in() and state.user()["role"] == "customer":
        in_list = m.get("in_watchlist")
        if st.button("💔 Remove from watchlist" if in_list else "❤️ Add to watchlist"):
            if in_list:
                call(api.delete, f"/api/me/watchlist/{movie_id}")
            else:
                call(api.post, f"/api/me/watchlist/{movie_id}")
            st.rerun()

st.markdown("## Showtimes")
if m["status"] == "coming_soon" and not m.get("has_shows"):
    empty_state("🗓️", "Bookings open soon", "This movie is coming soon. Add it to your watchlist and check back.")
else:
    cinemas = call(api.get, "/api/cinemas") or []
    c1, c2 = st.columns([3, 1.3])
    cinema_names = {"All cinemas": None} | {c["name"]: c["id"] for c in cinemas}
    cinema_pick = c2.selectbox("Cinema", list(cinema_names), key="md_cinema")
    base = call(api.get, f"/api/movies/{movie_id}/showtimes", params={"cinema_id": cinema_names[cinema_pick]})
    if base is not None:
        if not base["dates"]:
            empty_state("🕒", "No upcoming shows", "There are no bookable showtimes for this movie right now.")
        else:
            labels = {d: date.fromisoformat(d).strftime("%a %d %b") for d in base["dates"]}
            with c1:
                chosen = st.pills("Date", base["dates"], format_func=lambda d: labels[d], default=base["dates"][0],
                                  key=f"md_date_{cinema_pick}")
            chosen = chosen or base["dates"][0]
            data = base if chosen == base["selected_date"] else call(
                api.get, f"/api/movies/{movie_id}/showtimes", params={"date": chosen, "cinema_id": cinema_names[cinema_pick]})
            for group in (data or {}).get("cinemas", []):
                c = group["cinema"]
                st.markdown(f'<div class="cb-cinema"><div class="name">🏢 {esc(c["name"])}</div><div class="addr">'
                            f'{esc(c.get("address") or c.get("city") or "")} · {esc(", ".join(c.get("amenities") or []))}'
                            f'</div></div>', unsafe_allow_html=True)
                with st.container(horizontal=True, key=f"shows_{c['id']}"):
                    for s in group["shows"]:
                        left_ = s["seats_available"]
                        tag = "Sold out" if left_ == 0 else (f"{left_} left" if left_ < 20 else "Available")
                        label = f"{s['local_time']} · {s['screen_name']} · {s['format']} · {s['language']} · {tag}"
                        if st.button(label, key=f"show_{s['id']}", disabled=left_ == 0,
                                     help="Prices: " + ", ".join(f"{k} {api.CURRENCY}{v:g}" for k, v in s["prices"].items())):
                            st.session_state.selected_seats = []
                            state.goto("seats", showtime_id=s["id"], seat_showtime=s["id"], hold=None,
                                       applied_offer=None)

st.markdown("## Audience reviews")
reviews = call(api.get, f"/api/movies/{movie_id}/reviews", params={"page_size": 10})
if reviews is not None:
    if not reviews["items"]:
        st.caption("No reviews yet. Customers can review a movie after attending a show.")
    for r in reviews["items"]:
        stars = "★" * r["rating"] + "☆" * (5 - r["rating"])
        st.markdown(f'<div class="cb-panel" style="margin-bottom:8px"><b style="color:#F5C542">{stars}</b> '
                    f'<span class="cb-muted">· {esc(r["user_name"])} · {fmt_dt(r["created_at"], "%d %b %Y")}</span>'
                    f'<div>{esc(r.get("comment") or "")}</div></div>', unsafe_allow_html=True)
if state.logged_in() and state.user()["role"] == "customer":
    with st.expander("✍️ Write a review"):
        with st.form("review_form", clear_on_submit=True):
            rating = st.slider("Your rating", 1, 5, 4)
            comment = st.text_area("Comment (optional)", max_chars=600)
            if st.form_submit_button("Submit review", type="primary"):
                res = call(api.post, f"/api/movies/{movie_id}/reviews", {"rating": rating, "comment": comment})
                if res:
                    state.flash("Thanks! Your review was saved.")
                    st.rerun()
