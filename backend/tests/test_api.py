def test_register_login_and_protected_profile(client):
    registered = client.post("/api/auth/register", json={"name": "Alex", "email": "alex@example.com", "password": "long-password"})
    assert registered.status_code == 201
    assert registered.json["user"]["email"] == "alex@example.com"
    login = client.post("/api/auth/login", json={"email": "alex@example.com", "password": "long-password"})
    assert login.status_code == 200
    assert client.get("/api/auth/me").status_code == 401
    profile = client.get("/api/auth/me", headers={"Authorization": "Bearer " + login.json["access_token"]})
    assert profile.json["name"] == "Alex"


def test_registration_validation_and_duplicate_email(client):
    assert client.post("/api/auth/register", json={"name": "", "email": "bad", "password": "short"}).status_code == 400
    body = {"name": "Test", "email": "same@example.com", "password": "long-password"}
    assert client.post("/api/auth/register", json=body).status_code == 201
    assert client.post("/api/auth/register", json=body).status_code == 409


def test_conversation_is_private(client, auth):
    created = client.post("/api/chat/conversations", headers=auth, json={"title": "My notes"})
    assert created.status_code == 201
    assert client.get(f"/api/chat/conversations/{created.json['id']}").status_code == 401
    assert client.get(f"/api/chat/conversations/{created.json['id']}", headers=auth).json["title"] == "My notes"


def test_reject_unsupported_document(client, auth):
    response = client.post("/api/documents", headers=auth, data={"files": ( __import__('io').BytesIO(b"no"), "evil.exe")}, content_type="multipart/form-data")
    assert response.status_code == 201
    assert response.json[0]["error"]


def test_health_endpoint(client):
    assert client.get("/api/health").json == {"status": "ok", "database": "ok"}
