from datetime import timedelta

import captcha_helper as captcha_module
from extensions import db
from models import LoginVisualChallenge, get_tr_now
from routes import auth as auth_module


def _active_captcha_token(client):
    with client.session_transaction() as session_state:
        return session_state.get(captcha_module.LOGIN_CAPTCHA_SESSION_KEY)


def test_captcha_helper_ttl_and_normalize_branches(app):
    with app.app_context():
        app.config["LOGIN_CAPTCHA_TTL_SECONDS"] = "invalid-value"
        assert captcha_module._ttl_seconds() == captcha_module.LOGIN_CAPTCHA_DEFAULT_TTL

        app.config["LOGIN_CAPTCHA_TTL_SECONDS"] = 5
        assert captcha_module._ttl_seconds() == 30

    assert captcha_module._normalize_code(" a-1 ?b ") == "A1B"


def test_captcha_svg_placeholder_branches(client):
    client.get("/login")
    token = _active_captcha_token(client)
    assert token

    mismatch = client.get("/login/captcha/wrong-token.svg")
    assert mismatch.status_code == 200
    assert "Kod yenilendi" in mismatch.data.decode("utf-8")

    challenge = LoginVisualChallenge.query.filter_by(token=token).first()
    challenge.expires_at = get_tr_now().replace(tzinfo=None) - timedelta(seconds=1)
    db.session.commit()

    expired = client.get(f"/login/captcha/{token}.svg")
    assert expired.status_code == 200
    assert "Süre doldu" in expired.data.decode("utf-8")

    challenge.expires_at = get_tr_now().replace(tzinfo=None) + timedelta(seconds=120)
    challenge.invalidated_at = None
    challenge.code = ""
    db.session.commit()

    missing_code = client.get(f"/login/captcha/{token}.svg")
    assert missing_code.status_code == 200
    assert "Kod bulunamadı" in missing_code.data.decode("utf-8")


def test_captcha_svg_active_render_branch(client):
    client.get("/login")
    token = _active_captcha_token(client)
    challenge = LoginVisualChallenge.query.filter_by(token=token).first()
    assert challenge is not None
    assert challenge.code

    response = client.get(f"/login/captcha/{token}.svg")
    svg = response.data.decode("utf-8")
    db.session.refresh(challenge)

    assert response.status_code == 200
    assert "captchaBg" in svg
    assert 'font-size="24"' in svg
    assert "Güvenlik doğrulama kodu" in svg
    assert challenge.last_rendered_at is not None


def test_auth_helpers_client_ip_and_identifier_branches(app):
    with app.test_request_context("/"):
        assert auth_module._client_ip() == "unknown"
        assert auth_module._auth_identifier("TeSt@Sarx.com").startswith("test@sarx.com|unknown")

    with app.test_request_context("/", headers={"X-Forwarded-For": "1.2.3.4, 5.6.7.8"}):
        assert auth_module._client_ip() == "1.2.3.4"
        assert auth_module._auth_identifier("user@sarx.com").startswith("user@sarx.com|1.2.3.4")


def test_auth_helpers_password_reset_branches(app):
    with app.app_context():
        app.config["PASSWORD_RESET_TOKEN_MAX_AGE_SECONDS"] = "oops"
        assert auth_module._get_password_reset_token_max_age() == 3600

        app.config["PASSWORD_RESET_TOKEN_MAX_AGE_SECONDS"] = -5
        assert auth_module._get_password_reset_token_max_age() == 1

        assert auth_module._validate_password_reset_value("weak") is not None
        assert auth_module._validate_password_reset_value("Strong#123") is None

    with app.test_request_context(
        "/",
        headers={
            "X-Forwarded-Host": "sarx.example.com",
            "X-Forwarded-Proto": "https",
        },
    ):
        assert auth_module._get_password_reset_base_url() == "https://sarx.example.com/"
