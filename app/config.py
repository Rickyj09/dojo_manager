import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, ".."))

UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads", "alumnos")
ACTAS_UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads", "actas")
MAX_CONTENT_LENGTH = 10 * 1024 * 1024


class Config:
    SECRET_KEY = os.environ.get(
        "SECRET_KEY",
        "dev-secret-key-cambiar-en-produccion"
    )

    WTF_CSRF_ENABLED = True

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "sqlite:///" + os.path.join(PROJECT_ROOT, "dojo_manager.db")
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = os.environ.get(
        "SESSION_COOKIE_SECURE", "0"
    ) == "1"
    SESSION_COOKIE_SAMESITE = "Lax"

    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = os.environ.get(
        "SESSION_COOKIE_SECURE", "0"
    ) == "1"
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_DURATION = 86400
