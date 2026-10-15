"""Coupon validation rules, admin analytics and the idempotent seed script."""
from datetime import timedelta

from conftest import hold_and_book, local_iso


def _hold(client, headers, showtime_id, seats):
    r = client.post("/api/holds", headers=headers, json={"showtime_id": showtime_id, "seats": seats})
    assert r.status_code == 201, r.text
    return r.json()


def test_percentage_coupon_with_cap(client, catalog, make_customer, offer):
    c = catalog()
    offer("BIG50", discount_value=50, max_discount=100)
    alice, _ = make_customer()
    hold = _hold(client, alice, c["showtime"]["id"], ["C1", "C2"])  # 800
    v = client.post("/api/offers/validate", headers=alice, json={"code": "big50", "hold_id": hold["id"]}).json()
    assert v["discount"] == 100 and v["total"] == 700
    b = client.post("/api/bookings", headers=alice, json={"hold_id": hold["id"], "offer_code": "BIG50"}).json()
    assert (b["subtotal"], b["discount"], b["total"]) == (800, 100, 700)


def test_fixed_coupon_and_minimum_value(client, catalog, make_customer, offer):
    c = catalog()
    offer("FLAT75", discount_type="fixed", discount_value=75, min_booking_value=300)
    alice, _ = make_customer()
    small = _hold(client, alice, c["showtime"]["id"], ["A2"])  # 150 < 300
    r = client.post("/api/offers/validate", headers=alice, json={"code": "FLAT75", "hold_id": small["id"]})
    assert r.status_code == 400 and r.json()["code"] == "offer_min_value"
    big = _hold(client, alice, c["showtime"]["id"], ["B1", "B2"])  # 500
    r = client.post("/api/offers/validate", headers=alice, json={"code": "FLAT75", "hold_id": big["id"]})
    assert r.json()["discount"] == 75


def test_invalid_expired_and_future_coupons(client, catalog, make_customer, offer, admin):
    c = catalog()
    offer("OLD", start_date=local_iso(timedelta(days=-10)), end_date=local_iso(timedelta(days=-1)))
    offer("SOON", start_date=local_iso(timedelta(days=2)), end_date=local_iso(timedelta(days=9)))
    off = offer("OFF")
    client.post(f"/api/admin/offers/{off['id']}/deactivate", headers=admin)
    alice, _ = make_customer()
    hold = _hold(client, alice, c["showtime"]["id"], ["B3"])
    expected = {"NOPE": "offer_invalid", "OLD": "offer_expired", "SOON": "offer_not_started", "OFF": "offer_invalid"}
    for code, err in expected.items():
        r = client.post("/api/offers/validate", headers=alice, json={"code": code, "hold_id": hold["id"]})
        assert r.status_code == 400 and r.json()["code"] == err, code
    # A booking with an invalid coupon is rejected but the hold is kept so the customer can retry without it.
    r = client.post("/api/bookings", headers=alice, json={"hold_id": hold["id"], "offer_code": "OLD"})
    assert r.status_code == 400
    assert client.post("/api/bookings", headers=alice, json={"hold_id": hold["id"]}).status_code == 201
    public = [o["code"] for o in client.get("/api/offers").json()]
    assert "OLD" not in public and "OFF" not in public and "SOON" in public


def test_per_customer_limit_and_reuse_after_cancellation(client, catalog, make_customer, offer):
    c = catalog()
    offer("ONCE", per_user_limit=1)
    alice, _ = make_customer()
    _, b1 = hold_and_book(client, alice, c["showtime"]["id"], ["A2"], offer_code="ONCE")
    assert b1.status_code == 201 and b1.json()["discount"] == 15
    hold = _hold(client, alice, c["showtime"]["id"], ["A3"])
    r = client.post("/api/bookings", headers=alice, json={"hold_id": hold["id"], "offer_code": "ONCE"})
    assert r.status_code == 400 and r.json()["code"] == "offer_user_limit"
    # Another customer may still use it.
    bob, _ = make_customer()
    _, b2 = hold_and_book(client, bob, c["showtime"]["id"], ["A4"], offer_code="ONCE")
    assert b2.status_code == 201
    # Cancelling restores Alice's redemption.
    client.post(f"/api/bookings/{b1.json()['id']}/cancel", headers=alice)
    r = client.post("/api/offers/validate", headers=alice, json={"code": "ONCE", "hold_id": hold["id"]})
    assert r.status_code == 200


def test_global_usage_limit(client, catalog, make_customer, offer):
    c = catalog()
    offer("ONLY2", usage_limit=2, per_user_limit=5)
    seats = iter(["A2", "A3", "A4"])
    results = []
    for _ in range(3):
        h, _u = make_customer()
        _, b = hold_and_book(client, h, c["showtime"]["id"], [next(seats)], offer_code="ONLY2")
        results.append(b.status_code)
    assert results == [201, 201, 400]


def test_admin_analytics(client, admin, catalog, make_customer, offer):
    c = catalog()
    offer("SAVE10")
    alice, _ = make_customer()
    bob, _ = make_customer()
    hold_and_book(client, alice, c["showtime"]["id"], ["B1", "B2"], offer_code="SAVE10")  # 500 - 50
    _, b = hold_and_book(client, bob, c["showtime"]["id"], ["C1"])  # 400
    client.post(f"/api/bookings/{b.json()['id']}/cancel", headers=bob)
    a = client.get("/api/admin/analytics", headers=admin).json()
    assert a["counts"]["customers"] == 2 and a["counts"]["movies"] == 1 and a["counts"]["screens"] == 1
    assert a["status_counts"]["confirmed"] == 1 and a["status_counts"]["cancelled"] == 1
    assert a["sales"]["tickets"] == 2
    assert a["sales"]["gross"] == 500 and a["sales"]["discount"] == 50 and a["sales"]["net"] == 450
    assert a["top_movies"][0]["movie"] == "Test Movie"
    assert {x["category"]: x["tickets"] for x in a["seat_categories"]} == {"premium": 2}
    assert a["coupons"][0]["code"] == "SAVE10" and a["coupons"][0]["uses"] == 1
    assert a["occupancy"][0]["booked"] == 2 and a["occupancy"][0]["capacity"] == 15
    assert a["daily_trend"] and a["monthly_trend"]
    filtered = client.get("/api/admin/analytics", headers=admin, params={"status": "cancelled"}).json()
    assert filtered["status_counts"]["cancelled"] == 1 and filtered["sales"]["tickets"] == 0
    assert client.get("/api/admin/analytics", headers=admin, params={"status": "nonsense"}).status_code == 400
    # Admin booking search by reference
    ref = b.json()["reference"]
    found = client.get("/api/admin/bookings", headers=admin, params={"reference": ref}).json()
    assert found["total"] == 1 and found["items"][0]["reference"] == ref


def test_audit_log_records_admin_actions(client, admin, catalog):
    catalog()
    logs = client.get("/api/admin/audit-logs", headers=admin).json()
    actions = {x["action"] for x in logs["items"]}
    assert {"movie.create", "cinema.create", "screen.create", "showtime.create"} <= actions


def test_seed_script_is_idempotent(client, db):
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "scripts" / "seed_data.py"
    spec = importlib.util.spec_from_file_location("seed_data", path)
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    assert seed.main() == 0
    counts = {n: db[n].count_documents({}) for n in ("movies", "cinemas", "screens", "showtimes", "offers", "users")}
    assert seed.main() == 0
    assert counts == {n: db[n].count_documents({}) for n in counts}
    assert counts["movies"] >= 8 and counts["cinemas"] >= 2 and counts["offers"] >= 3
    assert db.bookings.count_documents({}) == 0  # no fake booking history
    assert db.users.count_documents({"role": "customer"}) == 0


def test_health_endpoint(client):
    r = client.get("/api/health").json()
    assert r["database"] == "connected"
