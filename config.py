import os
from datetime import timedelta

from sqlalchemy.pool import StaticPool


def _bool_env(name, default=False):
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


class BaseConfig:
    ENV = os.getenv("FLASK_ENV", "development")
    DEBUG = False
    TESTING = False

    SECRET_KEY = os.getenv("SECRET_KEY")
    DATABASE_URL = os.getenv("DATABASE_URL")
    SQLALCHEMY_DATABASE_URI = DATABASE_URL
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": int(os.getenv("DB_POOL_RECYCLE_SECONDS", "3600")),
    }

    # Session/Auth
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = _bool_env("SESSION_COOKIE_SECURE", False)
    SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = _bool_env("REMEMBER_COOKIE_SECURE", False)
    REMEMBER_COOKIE_SAMESITE = os.getenv("REMEMBER_COOKIE_SAMESITE", "Lax")
    REMEMBER_COOKIE_DURATION = timedelta(days=int(os.getenv("REMEMBER_COOKIE_DURATION_DAYS", "7")))
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=int(os.getenv("PERMANENT_SESSION_LIFETIME_MINUTES", "120")))

    # Request limits
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", str(16 * 1024 * 1024)))
    MAX_FORM_MEMORY_SIZE = int(os.getenv("MAX_FORM_MEMORY_SIZE", str(2 * 1024 * 1024)))
    MAX_FORM_PARTS = int(os.getenv("MAX_FORM_PARTS", "200"))

    # Rate limiting
    REDIS_URL = os.getenv("REDIS_URL")
    RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI") or REDIS_URL or "memory://"
    RATELIMIT_DEFAULT = os.getenv("RATELIMIT_DEFAULT", "120 per hour")
    RATELIMIT_HEADERS_ENABLED = True

    # Auth lockout / route limits
    AUTH_LOCKOUT_ATTEMPTS = int(os.getenv("AUTH_LOCKOUT_ATTEMPTS", "5"))
    AUTH_LOCKOUT_MINUTES = int(os.getenv("AUTH_LOCKOUT_MINUTES", "15"))
    LOGIN_RATE_LIMIT = os.getenv("LOGIN_RATE_LIMIT", "5 per minute")
    RESET_RATE_LIMIT = os.getenv("RESET_RATE_LIMIT", "3 per minute")
    PASSKEY_CHALLENGE_TTL_SECONDS = int(os.getenv("PASSKEY_CHALLENGE_TTL_SECONDS", "180"))
    PASSWORD_RESET_TOKEN_MAX_AGE_SECONDS = int(os.getenv("PASSWORD_RESET_TOKEN_MAX_AGE_SECONDS", "3600"))
    PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL")
    PASSWORD_RESET_BASE_URL = os.getenv("PASSWORD_RESET_BASE_URL") or PUBLIC_BASE_URL
    CRITICAL_POST_RATE_LIMIT = os.getenv("CRITICAL_POST_RATE_LIMIT", "20 per minute")
    HOMEPAGE_EDITOR_CAN_PUBLISH = _bool_env("HOMEPAGE_EDITOR_CAN_PUBLISH", True)
    ROLE_SWITCH_ALLOWED_USERS = os.getenv("ROLE_SWITCH_ALLOWED_USERS") or os.getenv("ROLE_SWITCH_ALLOWED_EMAIL", "mehmetcinocevi@gmail.com")
    PASSKEY_ENABLED = _bool_env("PASSKEY_ENABLED", False)
    PASSKEY_RP_ID = os.getenv("PASSKEY_RP_ID", "")
    PASSKEY_RP_NAME = os.getenv("PASSKEY_RP_NAME", "SAR-X ARFF")
    PASSKEY_ORIGIN = os.getenv("PASSKEY_ORIGIN", "")
    PASSKEY_ALLOWED_ORIGINS = os.getenv("PASSKEY_ALLOWED_ORIGINS", "")

    # Upload/file security
    ALLOWED_UPLOAD_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "gif", "webp", "doc", "docx", "xls", "xlsx"}
    DRILL_MAX_FILE_SIZE = int(os.getenv("DRILL_MAX_FILE_SIZE", str(16 * 1024 * 1024)))
    MAX_EXPORT_ROWS = int(os.getenv("MAX_EXPORT_ROWS", "10000"))
    STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "local")
    LOCAL_UPLOAD_ROOT = os.getenv("LOCAL_UPLOAD_ROOT")
    LOCAL_UPLOAD_URL_PREFIX = os.getenv("LOCAL_UPLOAD_URL_PREFIX", "/static/uploads")
    GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME")
    GCS_PROJECT_ID = os.getenv("GCS_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")
    GCS_UPLOAD_PREFIX = os.getenv("GCS_UPLOAD_PREFIX", "")
    GCS_PUBLIC_BASE_URL = os.getenv("GCS_PUBLIC_BASE_URL")
    GCS_CACHE_CONTROL = os.getenv("GCS_CACHE_CONTROL", "public, max-age=3600")
    GCS_MAKE_UPLOADS_PUBLIC = _bool_env("GCS_MAKE_UPLOADS_PUBLIC", False)
    GOOGLE_DRIVE_CLIENT_ID = os.getenv("GOOGLE_DRIVE_CLIENT_ID")
    GOOGLE_DRIVE_CLIENT_SECRET = os.getenv("GOOGLE_DRIVE_CLIENT_SECRET")
    GOOGLE_DRIVE_REFRESH_TOKEN = os.getenv("GOOGLE_DRIVE_REFRESH_TOKEN")
    GOOGLE_DRIVE_TOKEN_URI = os.getenv("GOOGLE_DRIVE_TOKEN_URI", "https://oauth2.googleapis.com/token")
    GOOGLE_DRIVE_REDIRECT_URI = os.getenv("GOOGLE_DRIVE_REDIRECT_URI")
    GOOGLE_DRIVE_PARENT_FOLDER_ID = os.getenv("GOOGLE_DRIVE_PARENT_FOLDER_ID", "root")
    GOOGLE_DRIVE_DRILLS_ROOT_FOLDER_NAME = os.getenv("GOOGLE_DRIVE_DRILLS_ROOT_FOLDER_NAME", "SAR-X Tatbikat Belgeleri")

    # Scheduler/runtime
    ENABLE_SCHEDULER = _bool_env("ENABLE_SCHEDULER", False)
    ALLOW_CLOUD_RUN_WEB_SCHEDULER = _bool_env("ALLOW_CLOUD_RUN_WEB_SCHEDULER", False)
    ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION = _bool_env("ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION", False)
    AUTO_CREATE_TABLES = _bool_env("AUTO_CREATE_TABLES", False)
    ALLOW_SQLITE_IN_PRODUCTION = _bool_env("ALLOW_SQLITE_IN_PRODUCTION", False)
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    DEMO_TOOLS_ENABLED = _bool_env("DEMO_TOOLS_ENABLED", False)

    # Mail / Secret Manager
    MAIL_HOST = os.getenv("MAIL_HOST", "smtp.gmail.com")
    MAIL_PORT = int(os.getenv("MAIL_PORT", "587"))
    MAIL_USE_TLS = _bool_env("MAIL_USE_TLS", True)
    MAIL_USERNAME = os.getenv("MAIL_USERNAME")
    MAIL_FROM_EMAIL = os.getenv("MAIL_FROM_EMAIL")
    MAIL_REPLY_TO = os.getenv("MAIL_REPLY_TO")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
    MAIL_SECRET_PROJECT_ID = os.getenv("MAIL_SECRET_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")
    MAIL_PASSWORD_SECRET_NAME = os.getenv("MAIL_PASSWORD_SECRET_NAME")
    MAIL_PASSWORD_SECRET_VERSION = os.getenv("MAIL_PASSWORD_SECRET_VERSION", "latest")

    # Security headers
    CSP_POLICY = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' https: data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )


class DevelopmentConfig(BaseConfig):
    ENV = "development"
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///sar_veritabani.db")
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
    ENABLE_SCHEDULER = _bool_env("ENABLE_SCHEDULER", True)
    AUTO_CREATE_TABLES = _bool_env("AUTO_CREATE_TABLES", True)
    DEMO_TOOLS_ENABLED = _bool_env("DEMO_TOOLS_ENABLED", True)


class TestingConfig(BaseConfig):
    ENV = "testing"
    TESTING = True
    DEBUG = False
    SECRET_KEY = os.getenv("SECRET_KEY", "test-secret-key-only")
    SQLALCHEMY_DATABASE_URI = os.getenv("TEST_DATABASE_URL", "sqlite:///:memory:")
    SQLALCHEMY_ENGINE_OPTIONS = {
        "connect_args": {"check_same_thread": False},
        "poolclass": StaticPool,
    }
    WTF_CSRF_ENABLED = False
    ENABLE_SCHEDULER = False
    AUTO_CREATE_TABLES = False
    RATELIMIT_STORAGE_URI = "memory://"
    RATELIMIT_DEFAULT = "10000 per hour"
    DEMO_TOOLS_ENABLED = _bool_env("DEMO_TOOLS_ENABLED", True)


class ProductionConfig(BaseConfig):
    ENV = "production"
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True
    SESSION_COOKIE_SAMESITE = "Lax"
    ENABLE_SCHEDULER = _bool_env("ENABLE_SCHEDULER", False)
    AUTO_CREATE_TABLES = _bool_env("AUTO_CREATE_TABLES", False)


config_by_name = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
