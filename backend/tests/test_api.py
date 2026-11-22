import io
import os
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pymupdf
import pytest
from flask_migrate import upgrade
from flask_jwt_extended import create_access_token
from sqlalchemy import create_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from app import create_app
from app.extensions import db
from app.models import Document, DocumentChunk, DocumentFile, Message, User
from app.services import document_jobs, groq_chat, vectors
from config import database_url


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


def test_cookie_login_requires_csrf_and_logout_revokes_session(app):
    app.config.update(JWT_COOKIE_SECURE=True, JWT_COOKIE_SAMESITE="None")
    credentials = {"email": "cookie@example.com", "password": "long-password"}
    headers = {"X-Paperwise-Session": "cookie", "Origin": "http://localhost:5173"}
    client = app.test_client()
    registered = client.post("/api/auth/register", json={"name": "Alex", **credentials}, headers=headers)
    assert registered.status_code == 201
    assert "access_token" not in registered.json
    assert registered.headers["Access-Control-Allow-Credentials"] == "true"
    cookie_header = registered.headers["Set-Cookie"]
    assert all(attribute in cookie_header for attribute in ("HttpOnly", "Secure", "SameSite=None"))
    assert client.post("/api/auth/logout", base_url="https://localhost").status_code == 401
    profile = client.get("/api/auth/me", headers=headers, base_url="https://localhost")
    assert profile.json["email"] == credentials["email"]
    csrf = {"X-CSRF-TOKEN": profile.json["csrf_token"]}
    logged_out = client.post("/api/auth/logout", headers=csrf, base_url="https://localhost")
    assert logged_out.status_code == 200
    assert client.get_cookie("access_token_cookie", path="/api") is None
    replay = app.test_client(use_cookies=False)
    assert replay.get("/api/auth/me", headers={"Cookie": cookie_header.split(";", 1)[0]}).status_code == 401
    new_browser = app.test_client()
    assert new_browser.post("/api/auth/login", json={**credentials, "password": "wrong"}).status_code == 401
    assert new_browser.post("/api/auth/login", json=credentials, headers=headers).status_code == 200


def test_expired_session_requires_sign_in(app, client):
    headers = {"X-Paperwise-Session": "cookie"}
    credentials = {"email": "expired@example.com", "password": "long-password"}
    registered = client.post("/api/auth/register", json={"name": "Alex", **credentials}, headers=headers)
    assert registered.status_code == 201
    with app.app_context():
        identity = str(registered.json["user"]["id"])
        expired = create_access_token(identity=identity, expires_delta=timedelta(seconds=-1))
    client.set_cookie("access_token_cookie", expired, path="/api")
    assert client.get("/api/auth/me", headers=headers).status_code == 401
    assert client.post("/api/auth/login", json=credentials, headers=headers).status_code == 200
    assert client.get("/api/auth/me", headers=headers).status_code == 200


@pytest.fixture(params=["sqlite", "postgresql"])
def persistent_database(request, tmp_path):
    if request.param == "sqlite":
        yield {"SQLALCHEMY_DATABASE_URI": f"sqlite:///{(tmp_path / 'persistent.db').as_posix()}"}
        return
    url = os.getenv("PAPERWISE_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set PAPERWISE_TEST_POSTGRES_URL to run against PostgreSQL")
    url = database_url(url)
    schema = f"paperwise_test_{uuid4().hex}"
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    try:
        yield {
            "SQLALCHEMY_DATABASE_URI": url,
            "SQLALCHEMY_ENGINE_OPTIONS": {
                "pool_pre_ping": True,
                "connect_args": {"options": f"-csearch_path={schema}"},
            },
        }
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()


def test_accounts_and_workspace_survive_app_restart(persistent_database, tmp_path, monkeypatch):
    config = {
        **persistent_database,
        "TESTING": True,
        "JWT_SECRET_KEY": "persistent-integration-test-secret",
        "UPLOAD_FOLDER": str(tmp_path / "uploads"),
        "CHROMA_PATH": str(tmp_path / "vectors"),
        "RATELIMIT_ENABLED": False,
    }
    migration_dir = str(Path(__file__).resolve().parents[1] / "migrations")
    monkeypatch.setattr(vectors, "embed", lambda texts: [[1.0, 0.0] for _ in texts])
    credentials = {"email": "existing@example.com", "password": "long-password"}
    app = create_app(config)
    with app.app_context():
        upgrade(directory=migration_dir, revision="0002_chat_attachments")
        user = User(name="Existing", email=credentials["email"])
        user.set_password(credentials["password"])
        db.session.add(user)
        db.session.commit()
        assert user.password_hash != credentials["password"]
        upgrade(directory=migration_dir)
    client = app.test_client()
    login = client.post("/api/auth/login", json=credentials)
    assert login.status_code == 200
    auth = {"Authorization": "Bearer " + login.json["access_token"]}
    conversation = client.post("/api/chat/conversations", headers=auth, json={"title": "Notes"})
    conversation_id = conversation.json["id"]
    path = f"/api/chat/conversations/{conversation_id}"
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((72, 72), "The launch is in June.")
        uploaded = client.post(path + "/attachments", headers=auth, data={
            "files": (io.BytesIO(pdf.tobytes()), "launch.pdf"),
        })
    assert uploaded.status_code == 201
    document_id = uploaded.json[0]["id"]
    assert uploaded.json[0]["status"] == "ready"
    with app.app_context():
        db.session.add(Message(conversation_id=conversation_id, role="user", content="When is launch?"))
        db.session.commit()
    assert client.post("/api/auth/logout", headers=auth).status_code == 200
    with app.app_context():
        db.engine.dispose()

    restarted = create_app({**config, "DOCUMENT_JOBS": True})
    with restarted.app_context():
        upgrade(directory=migration_dir)
    reopened = restarted.test_client()
    assert reopened.get("/api/auth/me", headers=auth).status_code == 401
    login = reopened.post("/api/auth/login", json=credentials)
    assert login.status_code == 200
    new_auth = {"Authorization": "Bearer " + login.json["access_token"]}
    restored = reopened.get(path, headers=new_auth).json
    assert restored["messages"][0]["content"] == "When is launch?"
    assert restored["attachments"][0]["id"] == document_id
    assert reopened.get("/api/documents", headers=new_auth).json[0]["id"] == document_id
    pdf_url = f"/api/documents/{document_id}/pdf"
    assert reopened.get(pdf_url, headers=new_auth).data.startswith(b"%PDF-")
    reused = reopened.post(path + "/attachments", headers=new_auth, data={
        "files": (io.BytesIO(reopened.get(pdf_url, headers=new_auth).data), "launch.pdf"),
    })
    assert reused.json[0]["id"] == document_id
    assert reused.json[0]["status"] == "ready"
    assert (tmp_path / "vectors" / "chroma.sqlite3").is_file()
    with restarted.app_context():
        assert vectors._collection().get(where={"document_id": document_id})["ids"]
        assert User.query.count() == 1
        db.engine.dispose()
    other = reopened.post("/api/auth/register", json={
        "name": "Other", "email": "other@example.com", "password": "another-password",
    })
    other_auth = {"Authorization": "Bearer " + other.json["access_token"]}
    assert reopened.get(path, headers=other_auth).status_code == 404
    assert reopened.get(pdf_url, headers=other_auth).status_code == 404


def test_document_jobs_survive_restart_and_delete_safely(persistent_database, tmp_path, monkeypatch):
    config = {
        **persistent_database, "TESTING": True, "DOCUMENT_JOBS": True, "RATELIMIT_ENABLED": False,
        "JWT_SECRET_KEY": "persistent-document-jobs-testing-secret",
        "UPLOAD_FOLDER": str(tmp_path / "uploads"), "CHROMA_PATH": str(tmp_path / "vectors"),
    }
    monkeypatch.setattr(vectors, "embed", lambda texts: [[1.0, 0.0] for _ in texts])
    monkeypatch.setattr(groq_chat, "complete", lambda _, messages, structured=False, **options:
                        '{"mode":"document","document_ids":[99999]}' if structured and "files" in messages[-1]["content"]
                        else '{"document_answer":"Founded in 2017 [Source 1]."}' if structured else "Hello!")
    app = create_app(config)
    with app.app_context():
        upgrade(directory=str(Path(__file__).resolve().parents[1] / "migrations"))
    client = app.test_client()
    account = client.post("/api/auth/register", json={
        "name": "Owner", "email": "owner@example.com", "password": "test-password",
    }).json
    auth = {"Authorization": "Bearer " + account["access_token"]}
    chat_id = client.post("/api/chat/conversations", headers=auth, json={}).json["id"]
    chat = f"/api/chat/conversations/{chat_id}"
    with pymupdf.open() as document:
        document.new_page().insert_text((72, 72), "Novatek Systems was founded in 2017.")
        raw = document.tobytes()
        document.new_page().insert_text((72, 72), "Another unrelated file.")
        second = document.tobytes()
    response = client.post(chat + "/attachments", headers=auth, data={
        "files": [(io.BytesIO(raw), "novatek.pdf"), (io.BytesIO(second), "second.pdf")],
    })
    first_id, second_id = [doc["id"] for doc in response.json]
    assert [doc["status"] for doc in response.json] == ["uploaded", "uploaded"]
    pending = client.post(chat + "/messages", headers=auth, json={"question": "When was Novatek founded?"})
    assert "still processing" in pending.json["answer"]["content"]
    duplicate = client.post(chat + "/attachments", headers=auth,
                            data={"files": (io.BytesIO(raw), "novatek.pdf")})
    assert duplicate.json[0]["id"] == first_id
    assert not list((tmp_path / "uploads").iterdir())

    restarted = create_app({**config, "UPLOAD_FOLDER": str(tmp_path / "new-uploads")})
    reopened = restarted.test_client()
    assert reopened.get(chat + "/attachments", headers=auth).json[0]["status"] == "uploaded"
    with restarted.app_context():
        assert document_jobs.process_next()
    pdf_url = f"/api/documents/{first_id}/pdf"
    assert reopened.get(pdf_url, headers=auth).data == raw
    answer = reopened.post(chat + "/messages", headers=auth, json={"question": "When was Novatek founded?"})
    assert answer.json["answer"]["sources"][0]["page_number"] == 1
    other_account = reopened.post("/api/auth/register", json={
        "name": "Other", "email": "other@example.com", "password": "other-password",
    }).json
    other = {"Authorization": "Bearer " + other_account["access_token"]}
    assert reopened.delete(f"/api/documents/{first_id}", headers=other).status_code == 404
    assert reopened.delete(f"/api/documents/{first_id}", headers=auth).status_code == 202
    assert reopened.delete(f"/api/documents/{first_id}", headers=auth).status_code == 202
    assert reopened.get(pdf_url, headers=auth).status_code == 404
    assert [doc["id"] for doc in reopened.get(chat + "/attachments", headers=auth).json] == [second_id]
    with restarted.app_context():
        while document_jobs.process_next():
            pass
        assert db.session.get(Document, first_id) is None
        assert db.session.get(DocumentFile, first_id) is None
        assert not DocumentChunk.query.filter_by(document_id=first_id).count()
        assert db.session.get(Document, second_id).status == "ready"
        assert not vectors.retrieve(account["user"]["id"], "Novatek", document_ids=[first_id])
        db.engine.dispose()
    assert reopened.delete(f"/api/documents/{first_id}", headers=auth).status_code == 204


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
