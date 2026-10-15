import streamlit as st

from components.ui import call, empty_state, movie_card_html, page_header
from services import api_client as api
from services import state

page_header("Movies", "Search the catalogue and filter by genre, language and availability.", "Catalogue")

opts = call(api.cached_get, "/api/movies/filters") or {"genres": [], "languages": []}
c1, c2, c3, c4 = st.columns([2.2, 1, 1, 1.2])
q = c1.text_input("Search by title", placeholder="e.g. Monsoon", key="mv_q")
genre = c2.selectbox("Genre", ["All"] + opts["genres"], key="mv_genre")
language = c3.selectbox("Language", ["All"] + opts["languages"], key="mv_lang")
status_label = c4.selectbox("Status", ["All", "Now Showing", "Coming Soon"], key="mv_status")
only_shows = st.toggle("Only movies with upcoming shows", key="mv_avail")

filters = (q.strip(), genre, language, status_label, only_shows)
if st.session_state.get("mv_filters") != filters:
    st.session_state.mv_filters = filters
    st.session_state.mv_page = 1
page = st.session_state.get("mv_page", 1)
PAGE_SIZE = 12

params = {
    "q": q.strip() or None,
    "genre": None if genre == "All" else genre,
    "language": None if language == "All" else language,
    "status": {"Now Showing": "now_showing", "Coming Soon": "coming_soon"}.get(status_label),
    "availability": "with_shows" if only_shows else None,
    "page": page,
    "page_size": PAGE_SIZE,
}
with st.spinner("Loading movies..."):
    data = call(api.cached_get, "/api/movies", tuple(sorted((k, v) for k, v in params.items() if v)))
if data is None:
    st.stop()

st.caption(f"{data['total']} movie(s) found")
if not data["items"]:
    empty_state("🔍", "No movies match your filters", "Try a different title, genre or language.")
    st.stop()

COLS = 4
items = data["items"]
for start in range(0, len(items), COLS):
    for col, m in zip(st.columns(COLS), items[start:start + COLS]):
        with col:
            st.markdown(movie_card_html(m), unsafe_allow_html=True)
            label = "Book tickets" if m.get("has_shows") else "View details"
            if st.button(label, key=f"mv_{m['id']}", width="stretch", type="primary" if m.get("has_shows") else "secondary"):
                state.goto("movie", movie_id=m["id"])

if data["pages"] > 1:
    p1, p2, p3 = st.columns([1, 2, 1])
    if p1.button("← Previous", disabled=page <= 1, width="stretch"):
        st.session_state.mv_page = page - 1
        st.rerun()
    p2.markdown(f"<div style='text-align:center;padding-top:8px'>Page {page} of {data['pages']}</div>",
                unsafe_allow_html=True)
    if p3.button("Next →", disabled=page >= data["pages"], width="stretch"):
        st.session_state.mv_page = page + 1
        st.rerun()
