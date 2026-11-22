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


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["CHROMA_PATH"]).mkdir(parents=True, exist_ok=True)
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    CORS(app, origins=app.config["CORS_ORIGINS"])
    if os.getenv("RENDER") == "true":
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
    limiter = Limiter(get_remote_address, app=app, default_limits=["300 per hour"],
                      storage_uri=app.config["RATELIMIT_STORAGE_URI"])
    from app.models import User, Document, Conversation, Message, ProcessingLog
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
            app.logger.exception("Health check database query failed")
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
