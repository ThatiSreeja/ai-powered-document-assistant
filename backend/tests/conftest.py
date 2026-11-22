import pytest
from app import create_app
from app.extensions import db


@pytest.fixture
def app(tmp_path):
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite://", "JWT_SECRET_KEY": "test-key-for-unit-tests-minimum-32-bytes",
                      "UPLOAD_FOLDER": str(tmp_path / "uploads"), "CHROMA_PATH": str(tmp_path / "chroma"),
                      "RATELIMIT_ENABLED": False})
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth(client):
    response = client.post("/api/auth/register", json={"name": "Test User", "email": "test@example.com", "password": "safe-password-1"})
    return {"Authorization": "Bearer " + response.json["access_token"]}
