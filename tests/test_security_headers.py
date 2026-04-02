from datetime import timedelta

from app import create_app
from extensions import db
from tests.factories import KullaniciFactory


def test_security_headers_added(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert "Content-Security-Policy" in response.headers
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert "Permissions-Policy" in response.headers


def test_production_config_enables_secure_cookie_flags(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x" * 48)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("ALLOW_SQLITE_IN_PRODUCTION", "1")
    monkeypatch.setenv("ENABLE_SCHEDULER", "0")
    monkeypatch.setenv("ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION", "1")

    app = create_app("production")
    assert app.config["SESSION_COOKIE_SECURE"] is True
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert app.config["REMEMBER_COOKIE_SECURE"] is True
    assert app.config["REMEMBER_COOKIE_HTTPONLY"] is True
    assert app.config["REMEMBER_COOKIE_SAMESITE"] == "Lax"
    assert app.config["REMEMBER_COOKIE_DURATION"] == timedelta(days=7)


def test_production_config_allows_remember_cookie_duration_override(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x" * 48)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("ALLOW_SQLITE_IN_PRODUCTION", "1")
    monkeypatch.setenv("ENABLE_SCHEDULER", "0")
    monkeypatch.setenv("REMEMBER_COOKIE_DURATION_DAYS", "3")
    monkeypatch.setenv("ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION", "1")

    app = create_app("production")

    assert app.config["REMEMBER_COOKIE_DURATION"] == timedelta(days=3)


def test_create_app_defaults_to_production_when_env_is_missing(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("FLASK_ENV", raising=False)
    monkeypatch.delenv("FLASK_RUN_FROM_CLI", raising=False)
    monkeypatch.setenv("SECRET_KEY", "x" * 48)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("ALLOW_SQLITE_IN_PRODUCTION", "1")
    monkeypatch.setenv("ENABLE_SCHEDULER", "0")
    monkeypatch.setenv("ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION", "1")

    app = create_app()

    assert app.config["ENV"] == "production"
    assert app.config["DEBUG"] is False
    assert app.config["SESSION_COOKIE_SECURE"] is True
    assert app.config["REMEMBER_COOKIE_SECURE"] is True


def test_create_app_allows_implicit_development_for_flask_cli(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("FLASK_ENV", raising=False)
    monkeypatch.setenv("FLASK_RUN_FROM_CLI", "true")
    monkeypatch.setenv("SECRET_KEY", "x" * 48)

    app = create_app()

    assert app.config["ENV"] == "development"
    assert app.config["DEBUG"] is True
    assert app.config["SESSION_COOKIE_SECURE"] is False


def test_create_app_rejects_invalid_env_name(monkeypatch):
    monkeypatch.setenv("APP_ENV", "prodlike")

    try:
        try:
            create_app()
            assert False, "create_app() invalid APP_ENV değerini reddetmeliydi."
        except RuntimeError as exc:
            assert "Geçersiz uygulama ortamı tanımı" in str(exc)
    finally:
        monkeypatch.delenv("APP_ENV", raising=False)


def test_production_defaults_to_memory_rate_limit_storage_when_unset(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x" * 48)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("ALLOW_SQLITE_IN_PRODUCTION", "1")
    monkeypatch.setenv("ENABLE_SCHEDULER", "0")
    monkeypatch.delenv("RATELIMIT_STORAGE_URI", raising=False)
    monkeypatch.delenv("ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION", raising=False)

    app = create_app("production")
    assert app.config["RATELIMIT_STORAGE_URI"] == "memory://"


def test_authenticated_dashboard_response_uses_private_no_store_cache_headers(client, app):
    user = KullaniciFactory(rol="sahip", is_deleted=False)
    db.session.add(user)
    db.session.commit()

    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert response.headers.get("Cache-Control") == "no-store, no-cache, must-revalidate, max-age=0, private"
    assert response.headers.get("Pragma") == "no-cache"
    assert response.headers.get("Expires") == "0"
    assert "Cookie" in response.headers.get("Vary", "")
