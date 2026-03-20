from extensions import db
from tests.factories import KullaniciFactory
from tests.test_auth import _extract_challenge_answer


def _failed_login_attempt(client, app, username, password):
    answer = _extract_challenge_answer(client, app)
    return client.post(
        "/login",
        data={
            "kullanici_adi": username,
            "sifre": password,
            "security_verification": answer,
        },
    )


def test_login_lockout_after_failed_attempts(client, app):
    app.config["AUTH_LOCKOUT_ATTEMPTS"] = 3
    app.config["AUTH_LOCKOUT_MINUTES"] = 1
    app.config["LOGIN_RATE_LIMIT"] = "100 per minute"

    user = KullaniciFactory(kullanici_adi="lock@test.com", is_deleted=False)
    user.sifre_set("correct-password")
    db.session.add(user)
    db.session.commit()

    for _ in range(3):
        fail_response = _failed_login_attempt(client, app, "lock@test.com", "wrong-password")
        assert fail_response.status_code == 200

    blocked_response = _failed_login_attempt(client, app, "lock@test.com", "correct-password")

    assert blocked_response.status_code == 429
    assert "başarısız giriş denemesi" in blocked_response.data.decode("utf-8")
