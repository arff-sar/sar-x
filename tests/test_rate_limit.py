from tests.test_auth import _extract_challenge_answer


def _login_attempt(client, app, username, password):
    answer = _extract_challenge_answer(client, app)
    return client.post(
        "/login",
        data={
            "kullanici_adi": username,
            "sifre": password,
            "security_verification": answer,
        },
    )


def test_login_rate_limit_applies(client, app):
    app.config["LOGIN_RATE_LIMIT"] = "2 per minute"

    response_1 = _login_attempt(client, app, "limit@test.com", "wrong")
    response_2 = _login_attempt(client, app, "limit@test.com", "wrong")
    response_3 = _login_attempt(client, app, "limit@test.com", "wrong")

    assert response_1.status_code == 200
    assert response_2.status_code == 200
    assert response_3.status_code == 429
    assert "İstek Limiti" in response_3.data.decode("utf-8")
