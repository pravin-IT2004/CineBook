"""Registration, login, invalid credentials and role-based access control."""


def test_register_and_login(client):
    r = client.post("/api/auth/register", json={"name": "Asha", "email": "Asha@Example.com", "password": "Secret123"})
    assert r.status_code == 201
    body = r.json()
    assert body["user"]["email"] == "asha@example.com"
    assert body["user"]["role"] == "customer"
    assert "password" not in str(body["user"]).lower()

    r = client.post("/api/auth/login", json={"email": "asha@example.com", "password": "Secret123"})
    assert r.status_code == 200
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"})
    assert me.status_code == 200 and me.json()["name"] == "Asha"


def test_password_is_hashed(client, db):
    client.post("/api/auth/register", json={"name": "Hash", "email": "hash@example.com", "password": "Secret123"})
    stored = db.users.find_one({"email": "hash@example.com"})
    assert stored["password_hash"] != "Secret123"
    assert stored["password_hash"].startswith("$2")


def test_duplicate_email_rejected(client):
    payload = {"name": "Dup", "email": "dup@example.com", "password": "Secret123"}
    assert client.post("/api/auth/register", json=payload).status_code == 201
    r = client.post("/api/auth/register", json=payload)
    assert r.status_code == 409 and r.json()["code"] == "email_taken"


def test_invalid_credentials(client):
    client.post("/api/auth/register", json={"name": "Bob", "email": "bob@example.com", "password": "Secret123"})
    r = client.post("/api/auth/login", json={"email": "bob@example.com", "password": "wrong-pass1"})
    assert r.status_code == 401 and r.json()["code"] == "invalid_credentials"
    r = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "Secret123"})
    assert r.status_code == 401


def test_weak_password_and_bad_email_rejected(client):
    r = client.post("/api/auth/register", json={"name": "Weak", "email": "weak@example.com", "password": "short"})
    assert r.status_code == 422
    r = client.post("/api/auth/register", json={"name": "Weak", "email": "weak@example.com", "password": "lettersonly"})
    assert r.status_code == 422 and "number" in r.json()["detail"]
    r = client.post("/api/auth/register", json={"name": "Bad", "email": "not-an-email", "password": "Secret123"})
    assert r.status_code == 422


def test_protected_routes_need_token(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/bookings").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_customer_cannot_use_admin_routes(client, make_customer):
    headers, _ = make_customer()
    for path in ("/api/admin/analytics", "/api/admin/movies", "/api/admin/bookings", "/api/admin/users"):
        r = client.get(path, headers=headers)
        assert r.status_code == 403, path
    r = client.post("/api/admin/movies", headers=headers, json={})
    assert r.status_code == 403


def test_admin_cannot_book_as_customer(client, admin, catalog):
    c = catalog()
    r = client.post("/api/holds", headers=admin, json={"showtime_id": c["showtime"]["id"], "seats": ["A2"]})
    assert r.status_code == 403


def test_admin_bootstrap_is_idempotent(client, db):
    from backend.services.auth_service import ensure_admin

    assert ensure_admin(db) == "exists"
    assert db.users.count_documents({"role": "admin"}) == 1


def test_deactivated_user_is_locked_out(client, admin, make_customer):
    headers, user = make_customer()
    r = client.put(f"/api/admin/users/{user['id']}", headers=admin, json={"is_active": False})
    assert r.status_code == 200
    assert client.get("/api/auth/me", headers=headers).status_code == 403
    me = client.get("/api/admin/users", headers=admin).json()["items"]
    assert any(u["email"] == user["email"] and not u["is_active"] for u in me)


def test_profile_update_and_password_change(client, make_customer):
    headers, user = make_customer()
    r = client.put("/api/me", headers=headers, json={"name": "New Name", "phone": "+91 98765 43210"})
    assert r.status_code == 200 and r.json()["name"] == "New Name"
    r = client.post("/api/me/password", headers=headers, json={"current_password": "wrong", "new_password": "Another123"})
    assert r.status_code == 400
    r = client.post("/api/me/password", headers=headers,
                    json={"current_password": "Password123", "new_password": "Another123"})
    assert r.status_code == 200
    assert client.post("/api/auth/login", json={"email": user["email"], "password": "Another123"}).status_code == 200
