import os
from pathlib import Path
from flask import Flask, jsonify, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from config import Config
from app.extensions import db, jwt, migrate
from app.models import RevokedToken, User


@jwt.token_in_blocklist_loader
def token_is_revoked(_header, claims):
    user_id = claims.get("sub", "")
    if not isinstance(user_id, str) or not user_id.isascii() or not user_id.isdecimal() or len(user_id) > 10:
        return True
    user = db.session.get(User, int(user_id))
    if user is None or claims.get("account_created_at") != user.account_created_at():
        return True
    return db.session.get(RevokedToken, claims["jti"]) is not None


@jwt.invalid_token_loader
def invalid_token(_reason):
    return jsonify({"error": "Your session is invalid. Sign in again."}), 401


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        if test_config.get("TESTING"):
            app.config["DOCUMENT_JOBS"] = False
        app.config.update(test_config)
    if app.config["SQLALCHEMY_DATABASE_URI"].startswith(("postgresql://", "postgresql+")):
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
            "pool_size": 5, "max_overflow": 2, "pool_timeout": 10,
            **app.config["SQLALCHEMY_ENGINE_OPTIONS"],
        }
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["CHROMA_PATH"]).mkdir(parents=True, exist_ok=True)
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    if app.config["JWT_COOKIE_SAMESITE"] == "None" and not app.config["JWT_COOKIE_SECURE"]:
        raise ValueError("Cross-site authentication cookies require HTTPS")
    CORS(app, origins=app.config["CORS_ORIGINS"], supports_credentials=True)
    if os.getenv("RENDER") == "true":
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
    limiter = Limiter(get_remote_address, app=app, default_limits=["300 per hour"],
                      storage_uri=app.config["RATELIMIT_STORAGE_URI"])
    from app.routes.api import api
    app.register_blueprint(api)

    @app.get("/api/health")
    @limiter.exempt
    def health():
        try:
            db.session.execute(text("SELECT 1"))
            return jsonify({"status": "ok", "database": "ok"})
        except Exception:
            db.session.rollback()
            app.logger.error("Health check database query failed")
            return jsonify({"status": "degraded", "database": "unavailable"}), 503

    @app.errorhandler(413)
    def too_large(_):
        limit = app.config["MAX_CONTENT_LENGTH"] / (1024 * 1024)
        return jsonify({"error": f"The combined upload exceeds the {limit:g} MB limit."}), 413

    @app.errorhandler(429)
    def too_many_requests(_):
        return jsonify({"error": "Too many requests. Wait a moment and retry."}), 429

    @app.errorhandler(SQLAlchemyError)
    def database_error(exc):
        db.session.rollback()
        app.logger.error("Database request failed: %s", exc.__class__.__name__)
        return jsonify({"error": "Database unavailable. Check the database connection and try again."}), 503

    @app.errorhandler(500)
    def server_error(_):
        app.logger.exception("Unhandled application error")
        return jsonify({"error": "An unexpected server error occurred."}), 500

    dist = app.config["FRONTEND_DIST"]
    if dist:
        @app.get("/assets/<path:filename>")
        @limiter.exempt
        def frontend_asset(filename):
            return send_from_directory(Path(dist) / "assets", filename, max_age=31536000)

        @app.get("/")
        @app.get("/login")
        @app.get("/register")
        @app.get("/app")
        @app.get("/app/<path:route>")
        @limiter.exempt
        def frontend(route=None):
            return send_from_directory(dist, "index.html", max_age=0)

    return app
