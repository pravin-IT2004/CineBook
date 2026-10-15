"""Seat holds, double-booking prevention, booking, rollback, cancellation, tickets and access control."""
import threading
from datetime import timedelta

import pytest
from bson import ObjectId

from backend.database import get_db
from backend.services import booking_service, seat_service
from backend.utils.errors import AppError
from backend.utils.timeutils import utcnow
from conftest import MODE, hold_and_book


def test_successful_booking_uses_server_prices(client, catalog, make_customer):
    c = catalog()
    headers, _ = make_customer()
    # Extra fields such as a fake price are ignored: the server prices seats itself.
    h = client.post("/api/holds", headers=headers, json={"showtime_id": c["showtime"]["id"], "seats": ["A2", "B3", "C1"],
                                                         "price": 1})
    assert h.status_code == 201
    assert h.json()["subtotal"] == 150 + 250 + 400
    b = client.post("/api/bookings", headers=headers, json={"hold_id": h.json()["id"], "total": 1, "status": "cancelled"})
    assert b.status_code == 201, b.text
    booking = b.json()
    assert booking["status"] == "confirmed"
    assert booking["total"] == 800 and booking["discount"] == 0
    assert booking["reference"].startswith("CB-")
    assert booking["payment"]["status"] == "not_collected"
    assert {s["seat_id"]: s["price"] for s in booking["seats"]} == {"A2": 150, "B3": 250, "C1": 400}
    seats = client.get(f"/api/showtimes/{c['showtime']['id']}/seats").json()
    assert seats["counts"]["booked"] == 3
    mine = client.get("/api/bookings", headers=headers, params={"scope": "upcoming"}).json()
    assert mine["total"] == 1 and mine["items"][0]["id"] == booking["id"]


def test_booking_snapshot_survives_catalogue_changes(client, admin, catalog, make_customer):
    c = catalog()
    headers, _ = make_customer()
    _, b = hold_and_book(client, headers, c["showtime"]["id"], ["B1"])
    client.put(f"/api/admin/movies/{c['movie']['id']}", headers=admin, json={"title": "Renamed"})
    client.put(f"/api/admin/showtimes/{c['showtime']['id']}", headers=admin,
               json={"prices": {"regular": 1, "premium": 1, "recliner": 1}})
    again = client.get(f"/api/bookings/{b.json()['id']}", headers=headers).json()
    assert again["movie_snapshot"]["title"] == "Test Movie"
    assert again["total"] == 250


def test_seat_validation(client, catalog, make_customer):
    c = catalog()
    headers, _ = make_customer()
    sid = c["showtime"]["id"]
    r = client.post("/api/holds", headers=headers, json={"showtime_id": sid, "seats": ["Z9"]})
    assert r.status_code == 400 and r.json()["code"] == "invalid_seats"
    r = client.post("/api/holds", headers=headers, json={"showtime_id": sid, "seats": ["A1"]})
    assert r.status_code == 400 and r.json()["code"] == "blocked_seats"
    r = client.post("/api/holds", headers=headers, json={"showtime_id": sid, "seats": ["bad seat"]})
    assert r.status_code == 422
    r = client.post("/api/holds", headers=headers, json={"showtime_id": sid, "seats": []})
    assert r.status_code == 422
    client.put("/api/admin/settings", headers=_admin_headers(client), json={**_policy(client), "max_seats_per_booking": 2})
    r = client.post("/api/holds", headers=headers, json={"showtime_id": sid, "seats": ["A2", "A3", "A4"]})
    assert r.status_code == 400 and r.json()["code"] == "too_many_seats"


def _admin_headers(client):
    t = client.post("/api/auth/login", json={"email": "admin@cinebook.test", "password": "AdminPass123"}).json()
    return {"Authorization": f"Bearer {t['access_token']}"}


def _policy(client):
    return client.get("/api/admin/settings", headers=_admin_headers(client)).json()


def test_double_booking_prevented(client, catalog, make_customer):
    c = catalog()
    alice, _ = make_customer("Alice")
    bob, _ = make_customer("Bob")
    sid = c["showtime"]["id"]
    assert client.post("/api/holds", headers=alice, json={"showtime_id": sid, "seats": ["B2", "B3"]}).status_code == 201
    r = client.post("/api/holds", headers=bob, json={"showtime_id": sid, "seats": ["B3", "B4"]})
    assert r.status_code == 409
    assert r.json()["code"] == "seats_unavailable" and r.json()["unavailable_seats"] == ["B3"]
    # Bob's partial hold was rolled back: B4 is still free.
    seats = client.get(f"/api/showtimes/{sid}/seats", headers=bob).json()
    status = {s["seat_id"]: s["status"] for r_ in seats["rows"] for s in r_["seats"]}
    assert status["B4"] == "available" and status["B3"] == "held" and status["B2"] == "held"


def test_booked_seat_cannot_be_held_again(client, catalog, make_customer):
    c = catalog()
    alice, _ = make_customer()
    bob, _ = make_customer()
    _, b = hold_and_book(client, alice, c["showtime"]["id"], ["C2"])
    assert b.status_code == 201
    r = client.post("/api/holds", headers=bob, json={"showtime_id": c["showtime"]["id"], "seats": ["C2"]})
    assert r.status_code == 409


def test_concurrent_holds_only_one_wins(client, catalog, make_customer):
    """Many customers race for the same seat at the same moment; the unique index lets exactly one win."""
    c = catalog()
    db = get_db()
    users = []
    for i in range(12):
        _, u = make_customer(f"Racer {i}")
        users.append(db.users.find_one({"email": u["email"]}))
    results: list[str] = []
    barrier = threading.Barrier(len(users))

    def attempt(user):
        barrier.wait()
        try:
            seat_service.create_hold(db, user, c["showtime"]["id"], ["B5"])
            results.append("ok")
        except AppError as exc:
            results.append(exc.code)

    threads = [threading.Thread(target=attempt, args=(u,)) for u in users]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count("ok") == 1, results
    assert results.count("seats_unavailable") == len(users) - 1
    assert db.seat_locks.count_documents({"showtime_id": ObjectId(c["showtime"]["id"]), "seat_id": "B5"}) == 1


def test_expired_hold_is_released_and_cannot_be_booked(client, catalog, make_customer):
    c = catalog()
    alice, _ = make_customer()
    bob, _ = make_customer()
    sid = c["showtime"]["id"]
    hold = client.post("/api/holds", headers=alice, json={"showtime_id": sid, "seats": ["A5"]}).json()
    db = get_db()
    past = utcnow() - timedelta(seconds=1)
    db.seat_locks.update_many({"hold_id": ObjectId(hold["id"])}, {"$set": {"expires_at": past}})
    db.seat_holds.update_one({"_id": ObjectId(hold["id"])}, {"$set": {"expires_at": past}})
    # Another customer can now claim the seat (expired lock is reclaimed atomically).
    r = client.post("/api/holds", headers=bob, json={"showtime_id": sid, "seats": ["A5"]})
    assert r.status_code == 201
    # The original holder can no longer book with the expired hold.
    b = client.post("/api/bookings", headers=alice, json={"hold_id": hold["id"]})
    assert b.status_code == 410 and b.json()["code"] == "hold_expired"


def test_cleanup_purges_expired_holds(client, catalog, make_customer):
    c = catalog()
    alice, _ = make_customer()
    hold = client.post("/api/holds", headers=alice, json={"showtime_id": c["showtime"]["id"], "seats": ["A6"]}).json()
    db = get_db()
    db.seat_locks.update_many({"hold_id": ObjectId(hold["id"])}, {"$set": {"expires_at": utcnow() - timedelta(minutes=1)}})
    db.seat_holds.update_one({"_id": ObjectId(hold["id"])}, {"$set": {"expires_at": utcnow() - timedelta(minutes=1)}})
    booking_service.cleanup(db)
    # (A MongoDB TTL index may also remove the expired lock on its own; either way it must be gone.)
    assert db.seat_locks.count_documents({"hold_id": ObjectId(hold["id"])}) == 0
    assert db.seat_holds.find_one({"_id": ObjectId(hold["id"])})["status"] == "expired"


def test_release_hold(client, catalog, make_customer):
    c = catalog()
    alice, _ = make_customer()
    hold = client.post("/api/holds", headers=alice, json={"showtime_id": c["showtime"]["id"], "seats": ["A4"]}).json()
    r = client.delete(f"/api/holds/{hold['id']}", headers=alice)
    assert r.status_code == 200 and r.json()["status"] == "released"
    seats = client.get(f"/api/showtimes/{c['showtime']['id']}/seats").json()
    assert seats["counts"]["held"] == 0


def test_hold_cannot_be_used_twice(client, catalog, make_customer):
    c = catalog()
    alice, _ = make_customer()
    hold, b = hold_and_book(client, alice, c["showtime"]["id"], ["A2"])
    assert b.status_code == 201
    again = client.post("/api/bookings", headers=alice, json={"hold_id": hold["id"]})
    assert again.status_code == 409 and again.json()["code"] == "hold_used"


def test_failed_booking_rolls_back(client, catalog, make_customer, offer, monkeypatch):
    """Simulate a crash after every write of the booking succeeded: everything must be undone."""
    c = catalog()
    offer("ROLLBACK", usage_limit=5)
    alice, _ = make_customer()
    hold = client.post("/api/holds", headers=alice, json={"showtime_id": c["showtime"]["id"], "seats": ["B1", "B2"]}).json()
    original = booking_service._commit

    def exploding_commit(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("simulated crash after commit steps")

    monkeypatch.setattr(booking_service, "_commit", exploding_commit)
    r = client.post("/api/bookings", headers=alice, json={"hold_id": hold["id"], "offer_code": "ROLLBACK"})
    assert r.status_code == 500 and r.json()["code"] == "booking_failed"
    db = get_db()
    assert db.seat_locks.count_documents({"showtime_id": ObjectId(c["showtime"]["id"])}) == 0
    failed = db.bookings.find_one({"hold_id": ObjectId(hold["id"])})
    assert failed["status"] == "failed"
    o = db.offers.find_one({"code": "ROLLBACK"})
    assert o["used_count"] == 0
    assert db.coupon_usage.find_one({"offer_id": o["_id"]})["count"] == 0
    assert db.coupon_redemptions.count_documents({}) == 0
    monkeypatch.setattr(booking_service, "_commit", original)
    # Seats are free again for anyone.
    bob, _ = make_customer()
    _, b2 = hold_and_book(client, bob, c["showtime"]["id"], ["B1", "B2"])
    assert b2.status_code == 201


def test_stuck_pending_booking_is_cleaned_up(client, catalog, make_customer):
    c = catalog()
    alice, _ = make_customer()
    _, b = hold_and_book(client, alice, c["showtime"]["id"], ["C3"])
    db = get_db()
    bid = ObjectId(b.json()["id"])
    # Pretend the process crashed right after inserting a pending booking 10 minutes ago.
    db.bookings.update_one({"_id": bid}, {"$set": {"status": "pending", "created_at": utcnow() - timedelta(minutes=10)}})
    db.seat_locks.update_many({"booking_id": bid}, {"$set": {"booked_at": utcnow() - timedelta(minutes=10)}})
    res = booking_service.cleanup(db)
    assert res["failed_bookings"] == 1
    assert db.bookings.find_one({"_id": bid})["status"] == "failed"
    assert db.seat_locks.count_documents({"booking_id": bid}) == 0


def test_cancellation_frees_seats_and_invalidates_ticket(client, catalog, make_customer):
    c = catalog()
    alice, _ = make_customer()
    _, b = hold_and_book(client, alice, c["showtime"]["id"], ["A3", "A4"])
    booking = client.get(f"/api/bookings/{b.json()['id']}", headers=alice).json()
    from urllib.parse import urlparse

    verify_url = urlparse(booking["verification_url"])
    verify_path = f"{verify_url.path}?{verify_url.query}"
    assert client.get(verify_path).json()["valid"] is True
    r = client.post(f"/api/bookings/{booking['id']}/cancel", headers=alice, json={"reason": "plans changed"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "cancelled"
    assert body["refund"]["status"] == "simulated_pending" and body["refund"]["amount"] == 240.0  # 80% of 300
    seats = client.get(f"/api/showtimes/{c['showtime']['id']}/seats").json()
    assert seats["counts"]["booked"] == 0
    again = client.post(f"/api/bookings/{booking['id']}/cancel", headers=alice)
    assert again.status_code == 409
    assert client.get(verify_path).json()["valid"] is False
    assert client.get("/api/bookings", headers=alice, params={"scope": "cancelled"}).json()["total"] == 1


def test_cancellation_cutoff_enforced_but_admin_can_cancel(client, admin, catalog, make_customer):
    c = catalog(start_in=timedelta(hours=1))  # policy: no customer cancellations within 2 hours
    alice, _ = make_customer()
    _, b = hold_and_book(client, alice, c["showtime"]["id"], ["B6"])
    bid = b.json()["id"]
    assert b.json()["can_cancel"] is False
    r = client.post(f"/api/bookings/{bid}/cancel", headers=alice)
    assert r.status_code == 409 and r.json()["code"] == "not_cancellable"
    r = client.post(f"/api/admin/bookings/{bid}/cancel", headers=admin, json={"reason": "projector fault"})
    assert r.status_code == 200 and r.json()["refund"]["percent"] == 100


def test_ticket_verification(client, catalog, make_customer):
    from backend.services.ticket_service import ticket_signature

    c = catalog()
    alice, _ = make_customer()
    _, b = hold_and_book(client, alice, c["showtime"]["id"], ["B4"])
    ref = b.json()["reference"]
    ok = client.get("/api/tickets/verify", params={"ref": ref, "sig": ticket_signature(ref)}).json()
    assert ok["valid"] is True and ok["seats"] == ["B4"]
    assert "email" not in str(ok) and "name" not in ok  # no customer personal data
    bad = client.get("/api/tickets/verify", params={"ref": ref, "sig": "0" * 32}).json()
    assert bad["valid"] is False and "tampered" in bad["reason"]
    unknown = client.get("/api/tickets/verify", params={"ref": "CB-NOTREAL1", "sig": ticket_signature("CB-NOTREAL1")})
    assert unknown.json()["valid"] is False


def test_check_in_marks_ticket_used(client, admin, catalog, make_customer):
    from backend.services.ticket_service import ticket_signature

    c = catalog()
    alice, _ = make_customer()
    _, b = hold_and_book(client, alice, c["showtime"]["id"], ["C4"])
    ref = b.json()["reference"]
    assert client.post(f"/api/admin/tickets/{ref}/check-in", headers=admin).status_code == 200
    assert client.post(f"/api/admin/tickets/{ref}/check-in", headers=admin).status_code == 409
    v = client.get("/api/tickets/verify", params={"ref": ref, "sig": ticket_signature(ref)}).json()
    assert v["valid"] is False and v["checked_in"] is True


def test_qr_and_pdf_ticket(client, catalog, make_customer):
    c = catalog()
    alice, _ = make_customer()
    _, b = hold_and_book(client, alice, c["showtime"]["id"], ["A2"])
    qr = client.get(f"/api/bookings/{b.json()['id']}/qr.png", headers=alice)
    assert qr.status_code == 200 and qr.content[:8] == b"\x89PNG\r\n\x1a\n"
    pdf = client.get(f"/api/bookings/{b.json()['id']}/ticket.pdf", headers=alice)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_customers_cannot_access_each_others_bookings(client, catalog, make_customer):
    c = catalog()
    alice, _ = make_customer("Alice")
    mallory, _ = make_customer("Mallory")
    hold, b = hold_and_book(client, alice, c["showtime"]["id"], ["B2"])
    bid = b.json()["id"]
    for path in (f"/api/bookings/{bid}", f"/api/bookings/{bid}/qr.png", f"/api/bookings/{bid}/ticket.pdf"):
        assert client.get(path, headers=mallory).status_code == 404, path
    assert client.post(f"/api/bookings/{bid}/cancel", headers=mallory).status_code == 404
    assert client.get("/api/bookings", headers=mallory).json()["total"] == 0
    other_hold = client.post("/api/holds", headers=alice, json={"showtime_id": c["showtime"]["id"], "seats": ["A6"]}).json()
    assert client.get(f"/api/holds/{other_hold['id']}", headers=mallory).status_code == 404
    assert client.delete(f"/api/holds/{other_hold['id']}", headers=mallory).status_code == 404
    assert client.post("/api/bookings", headers=mallory, json={"hold_id": other_hold["id"]}).status_code == 404
    # Alice's booking is still intact.
    assert client.get(f"/api/bookings/{bid}", headers=alice).json()["status"] == "confirmed"


def test_reviews_require_attended_show(client, catalog, make_customer):
    c = catalog()
    alice, _ = make_customer()
    _, b = hold_and_book(client, alice, c["showtime"]["id"], ["A2"])
    r = client.post(f"/api/movies/{c['movie']['id']}/reviews", headers=alice, json={"rating": 5, "comment": "Great"})
    assert r.status_code == 403  # show has not happened yet
    get_db().bookings.update_one({"_id": ObjectId(b.json()["id"])}, {"$set": {"show_start": utcnow() - timedelta(hours=3)}})
    r = client.post(f"/api/movies/{c['movie']['id']}/reviews", headers=alice, json={"rating": 4, "comment": "Great"})
    assert r.status_code == 200
    movie = client.get(f"/api/movies/{c['movie']['id']}").json()
    assert movie["avg_user_rating"] == 4 and movie["review_count"] == 1


@pytest.mark.skipif(MODE != "mongodb", reason="needs a real MongoDB server")
def test_indexes_exist_on_real_server(client):
    names = {i["name"] for i in get_db().seat_locks.list_indexes()}
    assert "uniq_showtime_seat" in names
