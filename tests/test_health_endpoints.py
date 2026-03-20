def test_health_endpoint_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ok"
    assert payload["service"] == "sar-x"


def test_ready_endpoint_checks_database(client):
    response = client.get("/ready")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["database"] == "ok"
    assert payload["status"] == "ready"


def test_anonymous_user_cannot_access_admin_management(client):
    response = client.get("/kullanicilar")
    assert response.status_code in [302, 403]
