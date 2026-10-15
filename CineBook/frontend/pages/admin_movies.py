from datetime import date

import pandas as pd
import streamlit as st

from components.posters import poster_css
from components.ui import call, page_header
from services import api_client as api
from services import state

state.require_admin()
page_header("Movies", "Add, edit, publish and remove movies.", "Administration")

GENRES = ["Action", "Adventure", "Animation", "Biography", "Comedy", "Crime", "Documentary", "Drama", "Family",
          "Fantasy", "Historical", "Horror", "Musical", "Mystery", "Romance", "Sci-Fi", "Sports", "Thriller"]
LANGS = ["Tamil", "English", "Hindi", "Telugu", "Malayalam", "Kannada", "Bengali", "Marathi"]
CERTS = ["U", "UA", "UA 7+", "UA 13+", "UA 16+", "A", "S"]
STATUSES = {"now_showing": "Now Showing", "coming_soon": "Coming Soon", "archived": "Archived"}

q = st.text_input("Search movies", key="am_q", placeholder="Title contains...")
data = call(api.get, "/api/admin/movies", params={"q": q or None, "page_size": 100})
if data is None:
    st.stop()
movies = data["items"]
if movies:
    df = pd.DataFrame([{"Title": m["title"], "Status": m["status_label"], "Published": m["is_published"],
                        "Languages": ", ".join(m["languages"]), "Genres": ", ".join(m["genres"]),
                        "Duration": m["duration_minutes"], "Upcoming shows": m.get("has_shows", False)} for m in movies])
    st.dataframe(df, hide_index=True, width="stretch")
else:
    st.info("No movies yet. Create the first one below.")


def movie_form(existing: dict | None, key: str) -> None:
    e = existing or {}
    with st.form(key, clear_on_submit=existing is None):
        c1, c2 = st.columns(2)
        title = c1.text_input("Title *", value=e.get("title", ""), max_chars=120)
        director = c2.text_input("Director", value=e.get("director") or "", max_chars=80)
        description = st.text_area("Description", value=e.get("description", ""), max_chars=2000)
        c3, c4 = st.columns(2)
        genres = c3.multiselect("Genres *", sorted(set(GENRES) | set(e.get("genres", []))), default=e.get("genres", []),
                                accept_new_options=True)
        languages = c4.multiselect("Languages *", sorted(set(LANGS) | set(e.get("languages", []))),
                                   default=e.get("languages", []), accept_new_options=True)
        c5, c6, c7, c8 = st.columns(4)
        duration = c5.number_input("Duration (min) *", 30, 400, int(e.get("duration_minutes", 120)))
        cert = c6.selectbox("Certificate", CERTS, index=CERTS.index(e.get("certificate", "UA")))
        rel_default = date.fromisoformat(e["release_date"][:10]) if e.get("release_date") else date.today()
        release = c7.date_input("Release date *", value=rel_default)
        rating = c8.number_input("Critic rating /10", 0.0, 10.0, float(e.get("rating") or 0.0), step=0.1,
                                 help="0 = no rating")
        c9, c10 = st.columns(2)
        status = c9.selectbox("Status", list(STATUSES), format_func=STATUSES.get,
                              index=list(STATUSES).index(e.get("status", "now_showing")))
        published = c10.toggle("Published (visible to customers)", value=e.get("is_published", False))
        poster_url = st.text_input("Poster image URL (optional)", value=e.get("poster_url") or "",
                                   help="Leave empty to use generated artwork in the colours below.")
        cols = (e.get("poster_colors") or ["#E50914", "#1F1F2E"]) + ["#1F1F2E"]
        p1, p2, p3 = st.columns([1, 1, 3])
        col1 = p1.color_picker("Poster accent", cols[0])
        col2 = p2.color_picker("Poster background", cols[1])
        cast = p3.text_input("Cast (comma separated)", value=", ".join(e.get("cast") or []))
        submitted = st.form_submit_button("Save movie" if existing else "Create movie", type="primary")
    if submitted:
        missing = [n for n, v in (("title", title.strip()), ("at least one genre", genres),
                                  ("at least one language", languages)) if not v]
        if missing:
            st.error("Please provide " + ", ".join(missing) + ".")
            return
        payload = {
            "title": title.strip(), "description": description.strip(), "genres": genres, "languages": languages,
            "duration_minutes": int(duration), "certificate": cert, "release_date": release.isoformat(),
            "status": status, "rating": rating or None, "poster_url": poster_url.strip() or None,
            "poster_colors": [col1.upper(), col2.upper()], "director": director.strip() or None,
            "cast": [c.strip() for c in cast.split(",") if c.strip()], "is_published": published,
        }
        if existing:
            res = call(api.put, f"/api/admin/movies/{existing['id']}", payload)
        else:
            res = call(api.post, "/api/admin/movies", payload)
        if res:
            state.flash(f"Movie '{res['title']}' saved.")
            st.rerun()


tab_new, tab_edit = st.tabs(["➕ Add movie", "✏️ Edit / publish / remove"])
with tab_new:
    movie_form(None, "new_movie")
with tab_edit:
    if not movies:
        st.caption("Nothing to edit yet.")
    else:
        pick = st.selectbox("Choose a movie", movies, format_func=lambda m: f"{m['title']} ({m['status_label']})",
                            key="am_pick")
        left, right = st.columns([1, 4])
        left.markdown(f'<div class="cb-card"><div class="cb-poster" style="background-image:{poster_css(pick)}"></div></div>',
                      unsafe_allow_html=True)
        with right:
            b1, b2, b3 = st.columns(3)
            if b1.button("Unpublish" if pick["is_published"] else "Publish", key="am_pub", width="stretch"):
                if call(api.post, f"/api/admin/movies/{pick['id']}/publish",
                        params={"publish": str(not pick["is_published"]).lower()}):
                    state.flash("Publication status updated.")
                    st.rerun()
            with b3.popover("🗑️ Remove", width="stretch"):
                st.write("Movies with showtimes or bookings are archived (hidden) instead of deleted, so ticket "
                         "history stays intact.")
                if st.button("Confirm remove", type="primary", key="am_del"):
                    res = call(api.delete, f"/api/admin/movies/{pick['id']}")
                    if res:
                        state.flash(res["message"], "info")
                        st.rerun()
            movie_form(pick, f"edit_{pick['id']}")
