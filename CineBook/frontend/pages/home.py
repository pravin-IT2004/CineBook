import streamlit as st

from components.posters import poster_css
from components.ui import call, empty_state, esc, fmt_dt, movie_card_html
from services import api_client as api
from services import state

feed = call(api.cached_get, "/api/movies", (("status", "now_showing"), ("availability", "with_shows"),
                                             ("page_size", 8)))
soon = call(api.cached_get, "/api/movies", (("status", "coming_soon"), ("page_size", 4)))
offers = call(api.cached_get, "/api/offers") or []

hero_movies = (feed or {}).get("items", [])[:3]
strip = "".join(f'<div class="p" style="background-image:{poster_css(m)}"></div>' for m in hero_movies)
user = state.user()
greeting = f"Welcome back, {esc(user['name'].split()[0])}." if user else "Your seat is waiting."
st.markdown(f"""
<div class="cb-hero">
  <div class="strip">{strip}</div>
  <div style="position:relative;z-index:2">
    <div class="cb-badge solid">NOW BOOKING</div>
    <h1>{greeting}<br/><em>Pick a film.</em> Pick your seat.</h1>
    <p>Browse what's playing, choose a cinema and showtime, select exact seats on a live seat map and get a
    QR ticket in seconds.</p>
  </div>
</div>""", unsafe_allow_html=True)

c1, c2, _ = st.columns([1, 1, 3])
if c1.button("🎞️  Browse movies", type="primary", width="stretch"):
    state.goto("movies")
if c2.button("🏷️  See offers", width="stretch"):
    state.goto("offers")

if user and user["role"] == "customer":
    notes = call(api.get, "/api/me/notifications", params={"unread_only": True, "page_size": 3})
    if notes and notes["items"]:
        with st.container(border=True):
            st.markdown(f"**🔔 {notes['unread']} new notification(s)**")
            for n in notes["items"]:
                st.markdown(f"- **{esc(n['title'])}** — {esc(n['message'])} "
                            f"<span class='cb-muted'>({fmt_dt(n['created_at'], '%d %b %I:%M %p')})</span>",
                            unsafe_allow_html=True)
            if st.button("Mark as read", key="mark_read"):
                call(api.post, "/api/me/notifications/read-all")
                st.rerun()


def grid(movies: list[dict], key: str, cols: int = 4) -> None:
    for start in range(0, len(movies), cols):
        columns = st.columns(cols)
        for col, m in zip(columns, movies[start:start + cols]):
            with col:
                st.markdown(movie_card_html(m), unsafe_allow_html=True)
                label = "Book tickets" if m.get("has_shows") else "View details"
                if st.button(label, key=f"{key}_{m['id']}", width="stretch",
                             type="primary" if m.get("has_shows") else "secondary"):
                    state.goto("movie", movie_id=m["id"])


st.markdown("## Now showing")
if feed is None:
    st.stop()
if feed["items"]:
    grid(feed["items"], "now")
else:
    empty_state("🎬", "No shows scheduled yet", "Check back soon - the cinema hasn't published any upcoming showtimes.")

if soon and soon["items"]:
    st.markdown("## Coming soon")
    grid(soon["items"], "soon")

if offers:
    st.markdown("## Offers for you")
    cols = st.columns(min(3, len(offers)))
    for col, o in zip(cols, offers[:3]):
        col.markdown(f'<div class="cb-offer"><div class="label">{esc(o["label"])}</div><div class="code">{esc(o["code"])}'
                     f'</div><div>{esc(o["title"])}</div><div class="desc">{esc(o.get("description", ""))}</div></div>',
                     unsafe_allow_html=True)

if user and user["role"] == "customer":
    recent = call(api.get, "/api/me/recently-viewed")
    if recent:
        st.markdown("## Recently viewed")
        grid(recent[:4], "recent")
