def test_post_without_csrf_token_rejected(client, app):
    app.config["WTF_CSRF_ENABLED"] = True

    response = client.post(
        "/sifre-sifirla-talep",
        data={"kullanici_adi": "someone@example.com"},
    )

    assert response.status_code == 400
    assert "Güvenlik" in response.data.decode("utf-8")
