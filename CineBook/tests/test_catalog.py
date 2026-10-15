"""Movie search, publishing rules and showtime scheduling/availability."""
from datetime import timedelta

from conftest import local_iso


def test_movie_search_and_filters(client, admin, catalog):
    catalog(title="Monsoon Diaries")
    catalog(title="Neon Nights", genres=["Sci-Fi"], languages=["English", "Hindi"])
    r = client.get("/api/movies", params={"q": "monsoon"}).json()
    assert [m["title"] for m in r["items"]] == ["Monsoon Diaries"]
    r = client.get("/api/movies", params={"genre": "Sci-Fi"}).json()
    assert [m["title"] for m in r["items"]] == ["Neon Nights"]
    r = client.get("/api/movies", params={"language": "Tamil"}).json()  # only the first film is in Tamil
    assert [m["title"] for m in r["items"]] == ["Monsoon Diaries"]
    r = client.get("/api/movies", params={"availability": "with_shows"}).json()
    assert r["total"] == 2 and all(m["has_shows"] for m in r["items"])
    # Regex special characters are treated literally, never as a pattern.
    assert client.get("/api/movies", params={"q": ".*"}).json()["total"] == 0
    opts = client.get("/api/movies/filters").json()
    assert "Sci-Fi" in opts["genres"] and "Hindi" in opts["languages"]


def test_pagination(client, admin):
    for i in range(5):
        client.post("/api/admin/movies", headers=admin, json={
            "title": f"Film {i}", "genres": ["Drama"], "languages": ["English"], "duration_minutes": 100,
            "release_date": "2026-01-01", "is_published": True})
    r = client.get("/api/movies", params={"page": 2, "page_size": 2}).json()
    assert r["total"] == 5 and r["pages"] == 3 and len(r["items"]) == 2


def test_unpublished_and_archived_movies_are_hidden(client, admin):
    r = client.post("/api/admin/movies", headers=admin, json={
        "title": "Secret Cut", "genres": ["Drama"], "languages": ["English"], "duration_minutes": 100,
        "release_date": "2026-01-01", "is_published": False})
    movie_id = r.json()["id"]
    assert client.get("/api/movies").json()["total"] == 0
    assert client.get(f"/api/movies/{movie_id}").status_code == 404
    client.post(f"/api/admin/movies/{movie_id}/publish", headers=admin, params={"publish": "true"})
    assert client.get(f"/api/movies/{movie_id}").status_code == 200
    client.put(f"/api/admin/movies/{movie_id}", headers=admin, json={"status": "archived"})
    assert client.get(f"/api/movies/{movie_id}").status_code == 404


def test_delete_movie_with_shows_archives_it(client, admin, catalog):
    c = catalog()
    r = client.delete(f"/api/admin/movies/{c['movie']['id']}", headers=admin).json()
    assert r["archived"] is True and r["deleted"] is False


def test_showtime_listing_and_seat_map(client, catalog):
    c = catalog()
    data = client.get(f"/api/movies/{c['movie']['id']}/showtimes").json()
    assert len(data["dates"]) == 1 and data["cinemas"][0]["shows"][0]["id"] == c["showtime"]["id"]
    show = data["cinemas"][0]["shows"][0]
    assert show["seats_available"] == 15  # 16 seats minus blocked A1
    seats = client.get(f"/api/showtimes/{c['showtime']['id']}/seats").json()
    assert seats["counts"] == {"available": 15, "booked": 0, "held": 0, "mine": 0, "blocked": 1}
    assert seats["prices"] == {"regular": 150, "premium": 250, "recliner": 400}


def test_overlapping_and_past_showtimes_rejected(client, admin, catalog):
    c = catalog()
    body = {"movie_id": c["movie"]["id"], "screen_id": c["screen"]["id"], "language": "English"}
    # Same screen, starts 1 hour into a 2-hour film -> overlap.
    r = client.post("/api/admin/showtimes", headers=admin, json={**body, "start_time": local_iso(timedelta(days=1, hours=1))})
    assert r.status_code == 409 and r.json()["code"] == "showtime_overlap"
    r = client.post("/api/admin/showtimes", headers=admin, json={**body, "start_time": local_iso(timedelta(hours=-2))})
    assert r.status_code == 400
    r = client.post("/api/admin/showtimes", headers=admin, json={**body, "language": "French",
                                                                "start_time": local_iso(timedelta(days=3))})
    assert r.status_code == 400 and r.json()["code"] == "invalid_language"


def test_showtime_closed_for_booking_is_not_listed(client, catalog):
    c = catalog(start_in=timedelta(minutes=5))  # inside the 10-minute booking cut-off
    data = client.get(f"/api/movies/{c['movie']['id']}/showtimes").json()
    assert data["dates"] == []
    r = client.get(f"/api/showtimes/{c['showtime']['id']}/seats")
    assert r.status_code == 409 and r.json()["code"] == "booking_closed"


def test_bulk_schedule_skips_conflicts(client, admin, catalog):
    c = catalog()
    from datetime import date

    tomorrow = (date.today() + timedelta(days=2)).isoformat()
    r = client.post("/api/admin/showtimes/bulk", headers=admin, json={
        "movie_id": c["movie"]["id"], "screen_id": c["screen"]["id"], "dates": [tomorrow],
        "times": ["10:00", "11:00", "15:00"], "language": "English"})
    assert r.status_code == 201
    assert r.json()["created"] == 2 and len(r.json()["skipped"]) == 1  # 11:00 overlaps the 10:00 show


def test_watchlist_and_recently_viewed(client, catalog, make_customer):
    c = catalog()
    headers, _ = make_customer()
    mid = c["movie"]["id"]
    assert client.post(f"/api/me/watchlist/{mid}", headers=headers).status_code == 200
    assert [m["id"] for m in client.get("/api/me/watchlist", headers=headers).json()] == [mid]
    client.get(f"/api/movies/{mid}", headers=headers)
    assert client.get("/api/me/recently-viewed", headers=headers).json()[0]["id"] == mid
    client.delete(f"/api/me/watchlist/{mid}", headers=headers)
    assert client.get("/api/me/watchlist", headers=headers).json() == []
