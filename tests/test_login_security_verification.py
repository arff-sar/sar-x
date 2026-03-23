from extensions import db
from models import LoginVisualChallenge, get_tr_now
from tests.factories import KullaniciFactory
from tests.test_auth import _extract_challenge_answer


def test_security_verification_visible_on_login(client):
    response = client.get("/login")
    html = response.data.decode("utf-8")
    assert response.status_code == 200
    assert "GÜVENLİK DOĞRULAMASI" in html
    assert "/login/captcha/" in html


def test_login_rejects_missing_security_verification(client, app):
    app.config["WTF_CSRF_ENABLED"] = False
    response = client.post("/login", data={"kullanici_adi": "x@sarx.com", "sifre": "123456"}, follow_redirects=True)
    html = response.data.decode("utf-8")
    assert response.status_code == 400
    assert "Güvenlik doğrulaması başarısız oldu." in html
    assert "SAR-X-AUTH-1202" in html


def test_login_rejects_invalid_security_verification(client, app):
    app.config["WTF_CSRF_ENABLED"] = False
    client.get("/login")
    response = client.post(
        "/login",
        data={"kullanici_adi": "x@sarx.com", "sifre": "123456", "security_verification": "999"},
        follow_redirects=True,
    )
    html = response.data.decode("utf-8")
    assert response.status_code == 400
    assert "Güvenlik doğrulaması başarısız oldu." in html
    assert "SAR-X-AUTH-1202" in html


def test_login_accepts_valid_security_verification(client, app):
    app.config["WTF_CSRF_ENABLED"] = False
    user = KullaniciFactory(kullanici_adi="secure@sarx.com", is_deleted=False, rol="sahip")
    db.session.add(user)
    db.session.commit()
    answer = _extract_challenge_answer(client, app)
    response = client.post(
        "/login",
        data={"kullanici_adi": "secure@sarx.com", "sifre": "123456", "security_verification": answer},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert response.request.path == "/dashboard"


def test_lockout_still_works_with_failed_security_verification(client, app):
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["AUTH_LOCKOUT_ATTEMPTS"] = 2
    client.get("/login")
    first = client.post("/login", data={"kullanici_adi": "lock@sarx.com", "sifre": "x", "security_verification": "0"})
    second = client.post("/login", data={"kullanici_adi": "lock@sarx.com", "sifre": "x", "security_verification": "0"})
    assert first.status_code == 400
    assert second.status_code == 400


def test_expired_visual_captcha_is_rejected(client, app):
    app.config["WTF_CSRF_ENABLED"] = False
    client.get("/login")
    with client.session_transaction() as session:
        token = session.get("login_visual_captcha_token")
    challenge = LoginVisualChallenge.query.filter_by(token=token).first()
    challenge.expires_at = get_tr_now().replace(tzinfo=None)
    db.session.commit()

    response = client.post(
        "/login",
        data={"kullanici_adi": "expired@sarx.com", "sifre": "123456", "security_verification": challenge.code},
        follow_redirects=True,
    )

    html = response.data.decode("utf-8")
    assert response.status_code == 400
    assert "Güvenlik doğrulaması başarısız oldu." in html
    assert "SAR-X-AUTH-1202" in html
    assert "Yeni kod yüklendi" in html
