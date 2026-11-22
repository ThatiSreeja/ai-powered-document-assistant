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


def test_production_frontend_routes(tmp_path):
    from app import create_app

    (tmp_path / "index.html").write_text("Paperwise frontend", encoding="utf-8")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "test.js").write_text("export {};", encoding="utf-8")
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite://",
                      "FRONTEND_DIST": str(tmp_path), "UPLOAD_FOLDER": str(tmp_path / "uploads"),
                      "CHROMA_PATH": str(tmp_path / "vectors"), "RATELIMIT_DEFAULT": "1 per hour"})
    with app.test_client() as client:
        for url in ("/", "/app/chat", "/app/history", "/login"):
            assert client.get(url).data == b"Paperwise frontend"
        assert client.get("/assets/test.js").cache_control.max_age == 31536000
        assert client.get("/assets/absent.js").status_code == 404
        assert client.get("/api/absent").status_code == 404
        assert client.get("/api/health").is_json
