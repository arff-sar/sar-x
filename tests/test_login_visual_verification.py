import re

from extensions import db
from models import LoginVisualChallenge, get_tr_now
from tests.factories import KullaniciFactory
from tests.test_auth import _extract_challenge_answer


def test_login_page_uses_shorter_default_captcha_ttl(client):
    response = client.get("/login")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert 'data-lifetime="60"' in html
    assert re.search(r'data-remaining="([5-9][0-9]|60)"', html)
    assert 'maxlength="5"' in html


def _current_captcha_token(client):
    with client.session_transaction() as session:
        return session.get("login_visual_captcha_token")


def test_login_get_rotates_captcha_token_on_each_render(client):
    first_response = client.get("/login")
    first_token = _current_captcha_token(client)
    first_challenge = LoginVisualChallenge.query.filter_by(token=first_token).first()

    second_response = client.get("/login")
    second_token = _current_captcha_token(client)
    second_challenge = LoginVisualChallenge.query.filter_by(token=second_token).first()
    db.session.refresh(first_challenge)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_token
    assert second_token
    assert first_token != second_token
    assert first_challenge.invalidated_at is not None
    assert second_challenge.invalidated_at is None


def test_old_challenge_cannot_be_reused_after_login_page_refresh(client, app):
    app.config["WTF_CSRF_ENABLED"] = False
    user = KullaniciFactory(kullanici_adi="refresh-cycle@sarx.com", is_deleted=False, rol="sahip")
    db.session.add(user)
    db.session.commit()

    client.get("/login")
    old_token = _current_captcha_token(client)
    old_challenge = LoginVisualChallenge.query.filter_by(token=old_token).first()
    old_code = old_challenge.code

    client.get("/login")
    current_token = _current_captcha_token(client)
    db.session.refresh(old_challenge)

    assert current_token != old_token
    assert old_challenge.invalidated_at is not None

    response = client.post(
        "/login",
        data={"kullanici_adi": "refresh-cycle@sarx.com", "sifre": "123456", "security_verification": old_code},
        follow_redirects=True,
    )
    assert response.status_code == 400
    assert "Güvenlik doğrulaması yanlış" in response.data.decode("utf-8")


def test_login_page_renders_visual_captcha_block(client):
    response = client.get("/login")
    html = response.data.decode("utf-8")
    token = _current_captcha_token(client)

    assert response.status_code == 200
    assert 'meta name="csrf-token"' in html
    assert 'id="captchaImage"' in html
    assert 'id="captchaRefresh"' in html
    assert 'id="captchaTimer"' in html
    assert 'id="captchaAnswer"' in html
    assert 'id="captchaTokenField"' in html
    assert f'value="{token}"' in html
    assert "autoRefreshStateMessage = 'Doğrulama kodu yenileniyor...'" in html
    assert "Yenile" not in html
    assert "/login/captcha/" in html


def test_login_page_styles_captcha_input_without_default_blue_focus(client):
    response = client.get("/login")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert ".captcha-input:focus," in html
    assert ".captcha-input:focus-visible" in html
    assert "outline: none !important;" in html
    assert "font-family: var(--sans) !important;" in html
    assert "text-align: center;" in html
    assert "line-height: 44px;" in html


def test_captcha_refresh_invalidates_previous_code(client, app):
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["LOGIN_CAPTCHA_TTL_SECONDS"] = 120
    user = KullaniciFactory(kullanici_adi="refresh@sarx.com", is_deleted=False, rol="sahip")
    db.session.add(user)
    db.session.commit()

    old_code = _extract_challenge_answer(client, app)
    old_token = _current_captcha_token(client)
    old_challenge = LoginVisualChallenge.query.filter_by(token=old_token).first()
    refresh_response = client.post("/login/captcha/refresh")
    payload = refresh_response.get_json()
    new_token = _current_captcha_token(client)
    new_challenge = LoginVisualChallenge.query.filter_by(token=new_token).first()
    db.session.refresh(old_challenge)

    assert refresh_response.status_code == 200
    assert old_token != new_token
    assert payload["captcha"]["token"] == new_token
    assert old_token not in payload["captcha"]["image_url"]
    assert new_token in payload["captcha"]["image_url"]
    assert payload["captcha"]["ttl_seconds"] == 120
    assert payload["captcha"]["remaining_seconds"] >= 110
    assert old_challenge.invalidated_at is not None
    assert new_challenge.expires_at > old_challenge.expires_at
    assert "no-store" in refresh_response.headers["Cache-Control"]
    old_image_response = client.get(f"/login/captcha/{old_token}.svg")
    assert "Kod yenilendi" in old_image_response.data.decode("utf-8")

    response = client.post(
        "/login",
        data={"kullanici_adi": "refresh@sarx.com", "sifre": "123456", "security_verification": old_code},
        follow_redirects=True,
    )

    assert response.status_code == 400
    assert "Güvenlik doğrulaması yanlış" in response.data.decode("utf-8")


def test_refresh_returns_working_new_captcha(client, app):
    app.config["WTF_CSRF_ENABLED"] = False
    user = KullaniciFactory(kullanici_adi="refresh-success@sarx.com", is_deleted=False, rol="sahip")
    db.session.add(user)
    db.session.commit()

    _extract_challenge_answer(client, app)
    refresh_response = client.post("/login/captcha/refresh")
    new_token = _current_captcha_token(client)
    new_challenge = LoginVisualChallenge.query.filter_by(token=new_token).first()

    assert refresh_response.status_code == 200

    valid_response = client.post(
        "/login",
        data={"kullanici_adi": "refresh-success@sarx.com", "sifre": "123456", "security_verification": new_challenge.code},
        follow_redirects=True,
    )
    assert valid_response.status_code == 200
    assert valid_response.request.path == "/dashboard"


def test_stale_hidden_token_requests_new_code(client, app):
    app.config["WTF_CSRF_ENABLED"] = False
    user = KullaniciFactory(kullanici_adi="stale-token@sarx.com", is_deleted=False, rol="sahip")
    db.session.add(user)
    db.session.commit()

    client.get("/login")
    old_token = _current_captcha_token(client)
    old_challenge = LoginVisualChallenge.query.filter_by(token=old_token).first()
    assert old_challenge is not None

    refresh_response = client.post("/login/captcha/refresh")
    new_token = _current_captcha_token(client)
    db.session.refresh(old_challenge)

    assert refresh_response.status_code == 200
    assert new_token != old_token
    assert old_challenge.invalidated_at is not None

    response = client.post(
        "/login",
        data={
            "kullanici_adi": "stale-token@sarx.com",
            "sifre": "123456",
            "security_verification": old_challenge.code,
            "security_verification_token": old_token,
        },
        follow_redirects=True,
    )

    assert response.status_code == 400
    assert "Güvenlik doğrulaması doğrulanamadı. Lütfen yeni kod alın." in response.data.decode("utf-8")


def test_valid_challenge_is_consumed_before_password_check(client, app):
    app.config["WTF_CSRF_ENABLED"] = False
    user = KullaniciFactory(kullanici_adi="consume@sarx.com", is_deleted=False, rol="sahip")
    db.session.add(user)
    db.session.commit()

    client.get("/login")
    token = _current_captcha_token(client)
    challenge = LoginVisualChallenge.query.filter_by(token=token).first()
    assert challenge is not None

    first_response = client.post(
        "/login",
        data={
            "kullanici_adi": "consume@sarx.com",
            "sifre": "yanlis-sifre",
            "security_verification": challenge.code,
            "security_verification_token": token,
        },
        follow_redirects=True,
    )
    db.session.refresh(challenge)

    assert first_response.status_code == 200
    assert "Şifre veya Kullanıcı Adı yanlış." in first_response.data.decode("utf-8")
    assert challenge.invalidated_at is not None

    second_response = client.post(
        "/login",
        data={
            "kullanici_adi": "consume@sarx.com",
            "sifre": "123456",
            "security_verification": challenge.code,
            "security_verification_token": token,
        },
        follow_redirects=True,
    )

    assert second_response.status_code == 400
    assert "Güvenlik doğrulaması doğrulanamadı. Lütfen yeni kod alın." in second_response.data.decode("utf-8")


def test_expired_captcha_requires_new_code(client, app):
    app.config["WTF_CSRF_ENABLED"] = False
    user = KullaniciFactory(kullanici_adi="expire@sarx.com", is_deleted=False, rol="sahip")
    db.session.add(user)
    db.session.commit()

    code = _extract_challenge_answer(client, app)
    token = _current_captcha_token(client)
    challenge = LoginVisualChallenge.query.filter_by(token=token).first()
    challenge.expires_at = get_tr_now().replace(tzinfo=None)
    db.session.commit()

    response = client.post(
        "/login",
        data={"kullanici_adi": "expire@sarx.com", "sifre": "123456", "security_verification": code},
        follow_redirects=True,
    )

    assert response.status_code == 400
    assert "süresi doldu" in response.data.decode("utf-8")


def test_login_page_renders_with_snapshot_loader_failure(client):
    def broken_loader(*_args, **_kwargs):
        raise RuntimeError("temporary db issue")

    client.application.extensions["public_site_snapshot_loader"] = broken_loader
    response = client.get("/login")
    assert response.status_code == 200


def test_captcha_svg_requires_active_session_token(client):
    client.get("/login")
    token = _current_captcha_token(client)
    assert token

    with client.session_transaction() as session:
        session.pop("login_visual_captcha_token", None)

    response = client.get(f"/login/captcha/{token}.svg")

    assert response.status_code == 200
    assert "Kod yenilendi" in response.data.decode("utf-8")
    assert response.headers["Vary"] == "Cookie"


def test_service_worker_skips_login_and_captcha_requests(client):
    response = client.get("/sw.js")
    body = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "AUTH_CACHE_BYPASS_PREFIXES" in body
    assert "'/login'" in body
    assert "requestUrl.pathname.startsWith(prefix + '/')" in body
