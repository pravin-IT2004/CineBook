"""Initialise the CineBook database with indexes, the admin account and a SAMPLE catalogue.

Safe to run many times: movies, cinemas, screens and offers are matched by natural keys
(slug / code / name) and inserted only if missing; showtimes are unique per screen + start
time, so re-running only adds shows for new upcoming days. No customer accounts or bookings
are created.

Usage (from the CineBook folder, with the virtual environment active):
    python scripts/seed_data.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pymongo.errors import DuplicateKeyError, PyMongoError  # noqa: E402

from backend.config import get_settings  # noqa: E402
from backend.database import ensure_indexes, get_db, ping  # noqa: E402
from backend.services.auth_service import ensure_admin  # noqa: E402
from backend.services.cinema_service import layout_capacity  # noqa: E402
from backend.services.movie_service import slugify  # noqa: E402
from backend.utils.timeutils import app_tz, local_to_utc, utcnow  # noqa: E402

TODAY = datetime.now(app_tz()).date()

MOVIES = [
    dict(title="The Last Monsoon", genres=["Drama", "Family"], languages=["Tamil", "English"], duration_minutes=142,
         certificate="U", rating=8.4, status="now_showing", release_days_ago=12, colors=["#F4A261", "#264653"],
         director="Meera Raghavan", cast=["Arjun Dev", "Kavya Iyer", "Nassar Ali"],
         description="A retired fisherman and his estranged daughter must rebuild their coastal village "
                     "after the worst monsoon in a century."),
    dict(title="Neon Requiem", genres=["Sci-Fi", "Thriller"], languages=["English", "Hindi"], duration_minutes=128,
         certificate="UA 13+", rating=7.9, status="now_showing", release_days_ago=5, colors=["#FF2E88", "#120B2E"],
         director="Daniel Okafor", cast=["Lena Park", "Victor Hale"],
         description="In a city that never sleeps, a memory detective discovers that her own past "
                     "has been rewritten."),
    dict(title="Paper Kites", genres=["Animation", "Family", "Adventure"], languages=["English", "Tamil", "Hindi"],
         duration_minutes=98, certificate="U", rating=8.1, status="now_showing", release_days_ago=20,
         colors=["#8ECAE6", "#023047"], director="Asha Menon", cast=["Voice cast"],
         description="Two siblings follow a runaway paper kite across rooftops, rivers and rain clouds."),
    dict(title="Iron Harbour", genres=["Action", "Crime"], languages=["Telugu", "Tamil", "Hindi"],
         duration_minutes=156, certificate="A", rating=7.2, status="now_showing", release_days_ago=3,
         colors=["#E63946", "#1D1D1D"], director="Ravi Teja Varma", cast=["Surya Prakash", "Anjali Rao"],
         description="A dock worker takes on a smuggling empire to protect the port town he grew up in."),
    dict(title="Midnight at Marina", genres=["Romance", "Comedy"], languages=["Tamil"], duration_minutes=124,
         certificate="UA", rating=7.6, status="now_showing", release_days_ago=9, colors=["#FFB4A2", "#3D405B"],
         director="Karthik Subbu", cast=["Vishnu Raj", "Priya Nair"],
         description="Two strangers keep missing each other on the same beach at midnight - until they don't."),
    dict(title="Echoes of Kaveri", genres=["Historical", "Drama"], languages=["Tamil", "Malayalam", "English"],
         duration_minutes=168, certificate="UA 7+", rating=8.7, status="now_showing", release_days_ago=30,
         colors=["#E9C46A", "#3A2E1F"], director="S. Lakshmanan", cast=["Vikram Shankar", "Divya Menon"],
         description="An epic about the engineers and dreamers who built an ancient dam on the Kaveri."),
    dict(title="Quantum Heist", genres=["Action", "Sci-Fi", "Thriller"], languages=["English", "Hindi"],
         duration_minutes=134, certificate="UA 13+", rating=7.4, status="now_showing", release_days_ago=1,
         colors=["#00F5D4", "#0B132B"], director="Mira Castellanos", cast=["Theo Grant", "Ishaan Kapoor"],
         description="A crew of physicists plans a robbery that takes place in two timelines at once."),
    dict(title="Whispering Pines", genres=["Horror", "Mystery"], languages=["Malayalam", "English"],
         duration_minutes=112, certificate="A", rating=6.9, status="now_showing", release_days_ago=7,
         colors=["#52B788", "#081C15"], director="Anand Joseph", cast=["Fahad Ali", "Nimisha Thomas"],
         description="A forest ranger investigates voices heard only between 3 and 4 in the morning."),
    dict(title="Laugh Track", genres=["Comedy"], languages=["Hindi", "English"], duration_minutes=118,
         certificate="UA", rating=None, status="coming_soon", release_days_ago=-14, colors=["#FFD166", "#26547C"],
         director="Rohan Mehta", cast=["Kunal Shah", "Sana Mirza"],
         description="A failing sitcom writer accidentally becomes the star of his own show."),
    dict(title="Skybound", genres=["Adventure", "Family"], languages=["English", "Tamil", "Telugu"],
         duration_minutes=126, certificate="U", rating=None, status="coming_soon", release_days_ago=-28,
         colors=["#4CC9F0", "#3A0CA3"], director="Hannah Lee", cast=["Maya Torres", "Arav Krishnan"],
         description="A young pilot enters an air race across five continents in a plane she built herself."),
]


def layout(rows: list[tuple[str, int, str]], aisles: list[int], blocked: list[str] | None = None) -> dict:
    return {"rows": [{"row": r, "seats": n, "category": c} for r, n, c in rows], "aisles_after": aisles,
            "blocked_seats": blocked or []}


STANDARD = layout([("A", 14, "regular"), ("B", 14, "regular"), ("C", 14, "regular"), ("D", 14, "regular"),
                   ("E", 14, "premium"), ("F", 14, "premium"), ("G", 14, "premium"), ("H", 8, "recliner"),
                   ("J", 8, "recliner")], aisles=[3, 11], blocked=["A1", "A14"])
LARGE = layout([("A", 18, "regular"), ("B", 18, "regular"), ("C", 18, "regular"), ("D", 18, "regular"),
                ("E", 18, "regular"), ("F", 18, "premium"), ("G", 18, "premium"), ("H", 18, "premium"),
                ("J", 10, "recliner"), ("K", 10, "recliner")], aisles=[4, 14])
COMPACT = layout([("A", 10, "regular"), ("B", 10, "regular"), ("C", 10, "regular"), ("D", 10, "premium"),
                  ("E", 10, "premium"), ("F", 6, "recliner")], aisles=[5])

CINEMAS = [
    dict(code="STAR-CBE", name="Starlight Multiplex (Sample)", city="Coimbatore",
         address="Avinashi Road, Peelamedu, Coimbatore (sample address)",
         amenities=["Dolby Atmos", "Recliners", "Food Court", "Parking", "Wheelchair access"],
         screens=[("Screen 1", "2D", STANDARD, {"regular": 180, "premium": 250, "recliner": 420}),
                  ("Screen 2 - IMAX", "IMAX", LARGE, {"regular": 280, "premium": 360, "recliner": 550})]),
    dict(code="AURORA-CBE", name="Aurora Cinemas (Sample)", city="Coimbatore",
         address="Race Course Road, Coimbatore (sample address)",
         amenities=["4K Projection", "Cafe", "Parking"],
         screens=[("Audi 1", "Dolby Atmos", STANDARD, {"regular": 160, "premium": 230, "recliner": 380}),
                  ("Audi 2", "3D", COMPACT, {"regular": 200, "premium": 260, "recliner": 400})]),
]

SHOW_TIMES = ["10:00", "13:45", "17:30", "21:15"]
DAYS_AHEAD = 7


def seed_movies(db) -> dict[str, object]:
    ids = {}
    created = 0
    for m in MOVIES:
        release = TODAY - timedelta(days=m["release_days_ago"])
        slug = slugify(f"{m['title']}-{release.year}")
        existing = db.movies.find_one({"title": m["title"], "is_sample": True})
        if existing:
            ids[m["title"]] = existing["_id"]
            continue
        now = utcnow()
        doc = {
            "slug": slug, "title": m["title"], "description": m["description"] + " (Sample catalogue entry.)",
            "genres": m["genres"], "languages": m["languages"], "duration_minutes": m["duration_minutes"],
            "certificate": m["certificate"], "rating": m["rating"], "status": m["status"],
            "release_date": datetime(release.year, release.month, release.day, tzinfo=timezone.utc),
            "poster_url": None, "poster_colors": m["colors"], "cast": m["cast"], "director": m["director"],
            "is_published": True, "is_sample": True, "avg_user_rating": None, "review_count": 0,
            "created_at": now, "updated_at": now,
        }
        try:
            ids[m["title"]] = db.movies.insert_one(doc).inserted_id
            created += 1
        except DuplicateKeyError:
            ids[m["title"]] = db.movies.find_one({"slug": slug})["_id"]
    print(f"Movies: {created} created, {len(MOVIES) - created} already present")
    return ids


def seed_cinemas(db) -> list[dict]:
    screens = []
    for c in CINEMAS:
        now = utcnow()
        cinema = db.cinemas.find_one({"code": c["code"]})
        if not cinema:
            cinema = {"code": c["code"], "name": c["name"], "city": c["city"], "address": c["address"],
                      "amenities": c["amenities"], "is_active": True, "is_sample": True,
                      "created_at": now, "updated_at": now}
            db.cinemas.insert_one(cinema)
            print(f"Cinema created: {c['name']}")
        for name, stype, lay, prices in c["screens"]:
            screen = db.screens.find_one({"cinema_id": cinema["_id"], "name": name})
            if not screen:
                screen = {"cinema_id": cinema["_id"], "name": name, "screen_type": stype, "layout": lay,
                          "default_prices": prices, "capacity": layout_capacity(lay), "is_active": True,
                          "created_at": now, "updated_at": now}
                db.screens.insert_one(screen)
            screens.append(screen)
    print(f"Cinemas: {len(CINEMAS)} present, screens: {len(screens)}")
    return screens


def seed_showtimes(db, movie_ids: dict[str, object], screens: list[dict]) -> None:
    now_showing = [m for m in MOVIES if m["status"] == "now_showing"]
    created = 0
    now = utcnow()
    for day_offset in range(DAYS_AHEAD):
        d = TODAY + timedelta(days=day_offset)
        for s_idx, screen in enumerate(screens):
            for t_idx, t in enumerate(SHOW_TIMES):
                movie = now_showing[(day_offset + s_idx * 2 + t_idx) % len(now_showing)]
                hh, mm = map(int, t.split(":"))
                start = local_to_utc(datetime(d.year, d.month, d.day, hh, mm))
                if start <= now + timedelta(minutes=30):
                    continue
                lang = movie["languages"][(s_idx + t_idx) % len(movie["languages"])]
                doc = {
                    "movie_id": movie_ids[movie["title"]], "cinema_id": screen["cinema_id"],
                    "screen_id": screen["_id"], "start_time": start,
                    "end_time": start + timedelta(minutes=movie["duration_minutes"]), "language": lang,
                    "format": screen["screen_type"], "prices": screen["default_prices"], "layout": screen["layout"],
                    "capacity": layout_capacity(screen["layout"]), "is_published": True,
                    "created_at": now, "updated_at": now,
                }
                try:
                    db.showtimes.insert_one(doc)
                    created += 1
                except DuplicateKeyError:
                    pass
    print(f"Showtimes: {created} new upcoming shows created for the next {DAYS_AHEAD} days")


def seed_offers(db) -> None:
    now = utcnow()
    offers = [
        dict(code="WELCOME10", title="Welcome offer - 10% off", description="10% off your booking, up to 150.",
             discount_type="percent", discount_value=10, min_booking_value=200, max_discount=150,
             start_date=now - timedelta(days=1), end_date=now + timedelta(days=90), usage_limit=None,
             per_user_limit=1),
        dict(code="FLAT100", title="Flat 100 off", description="Flat 100 off on bookings of 500 or more.",
             discount_type="fixed", discount_value=100, min_booking_value=500, max_discount=None,
             start_date=now - timedelta(days=1), end_date=now + timedelta(days=60), usage_limit=500,
             per_user_limit=2),
        dict(code="WEEKEND20", title="Weekend special - 20% off", description="20% off, up to 250, min. 400.",
             discount_type="percent", discount_value=20, min_booking_value=400, max_discount=250,
             start_date=now - timedelta(days=1), end_date=now + timedelta(days=30), usage_limit=200,
             per_user_limit=1),
        dict(code="FESTIVE25", title="Festive preview - 25% off", description="Starts soon: 25% off, up to 300.",
             discount_type="percent", discount_value=25, min_booking_value=300, max_discount=300,
             start_date=now + timedelta(days=10), end_date=now + timedelta(days=40), usage_limit=None,
             per_user_limit=1),
    ]
    created = 0
    for o in offers:
        res = db.offers.update_one(
            {"code": o["code"]},
            {"$setOnInsert": {**o, "is_active": True, "used_count": 0, "is_sample": True,
                              "created_at": now, "updated_at": now}},
            upsert=True,
        )
        created += 1 if res.upserted_id else 0
    print(f"Offers: {created} created, {len(offers) - created} already present")


def main() -> int:
    s = get_settings()
    print(f"Connecting to MongoDB at {s.mongo_url.split('@')[-1]} (database '{s.mongo_db_name}') ...")
    if not ping():
        print("ERROR: Cannot connect to MongoDB. Start the MongoDB service and check MONGO_URL in .env.")
        return 1
    try:
        db = get_db()
        ensure_indexes(db)
        print(f"Administrator: {ensure_admin(db)} ({s.admin_email or 'ADMIN_EMAIL not set'})")
        movie_ids = seed_movies(db)
        screens = seed_cinemas(db)
        seed_showtimes(db, movie_ids, screens)
        seed_offers(db)
    except PyMongoError as exc:
        print(f"ERROR while seeding: {exc}")
        return 1
    print("Done. Sample data is ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
