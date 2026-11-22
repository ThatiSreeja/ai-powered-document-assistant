import os
from pathlib import Path
from urllib.parse import urlsplit

BASE_DIR = Path(__file__).resolve().parent


def database_url(value):
    for scheme in ("postgres://", "postgresql://"):
        if value.startswith(scheme):
            return "postgresql+psycopg2://" + value[len(scheme):]
    return value


def cors_origins(value):
    origins = [origin.strip().rstrip("/") for origin in value.split(",") if origin.strip()]
    for origin in origins:
        parsed = urlsplit(origin)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or any((parsed.path, parsed.query, parsed.fragment, parsed.username, parsed.password))
                or "*" in origin):
            raise ValueError("CORS_ORIGINS must contain explicit HTTP or HTTPS origins")
    return origins


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-this-secret")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-only-change-this-jwt-secret")
    SQLALCHEMY_DATABASE_URI = database_url(os.getenv(
        "DATABASE_URL",
        "mysql+pymysql://root:password@localhost:3306/document_assistant?charset=utf8mb4",
    ))
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "hide_parameters": True}
    FRONTEND_DIST = os.getenv("FRONTEND_DIST")
    JWT_ACCESS_TOKEN_EXPIRES = 3600
    JWT_TOKEN_LOCATION = ["headers", "cookies"]
    JWT_ACCESS_COOKIE_PATH = "/api"
    JWT_COOKIE_SECURE = os.getenv("AUTH_COOKIE_SECURE", os.getenv("RENDER", "false")).lower() == "true"
    JWT_COOKIE_SAMESITE = os.getenv("AUTH_COOKIE_SAMESITE", "Lax")
    JWT_CSRF_IN_COOKIES = False
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", 16 * 1024 * 1024))
    UPLOAD_FOLDER = str(BASE_DIR / os.getenv("UPLOAD_FOLDER", "uploads"))
    CHROMA_PATH = str(BASE_DIR / os.getenv("CHROMA_PATH", "vector_store"))
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
    OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    AI_PROVIDER = os.getenv("AI_PROVIDER", "groq").strip().lower()
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    GROQ_CHAT_MODEL = os.getenv("GROQ_CHAT_MODEL", "openai/gpt-oss-120b")
    GROQ_TIMEOUT_SECONDS = float(os.getenv("GROQ_TIMEOUT_SECONDS", "30"))
    EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "").strip().lower()
    EMBEDDING_CACHE_PATH = Path(os.getenv("EMBEDDING_CACHE_PATH", Path.home() / ".cache" / "chroma" / "onnx_models"))
    MAX_PDF_PAGES = int(os.getenv("MAX_PDF_PAGES", "1000"))
    MAX_EXTRACTED_CHARACTERS = int(os.getenv("MAX_EXTRACTED_CHARACTERS", "2000000"))
    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    OLLAMA_CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "qwen2.5:3b")
    OLLAMA_EMBEDDING_MODEL = os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")
    CORS_ORIGINS = cors_origins(os.getenv("CORS_ORIGINS", "http://localhost:5173"))
    RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI", "memory://")
