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

    app = create_app("production")
    assert app.config["SESSION_COOKIE_SECURE"] is True
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert app.config["REMEMBER_COOKIE_SECURE"] is True
    assert app.config["REMEMBER_COOKIE_HTTPONLY"] is True
    assert app.config["REMEMBER_COOKIE_SAMESITE"] == "Lax"


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
