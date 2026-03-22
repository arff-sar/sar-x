from extensions import db
from models import SiteAyarlari


def test_health_endpoint_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ok"
    assert payload["service"] == "sar-x"

def test_ready_endpoint_checks_database(client):
    if SiteAyarlari.query.first() is None:
        db.session.add(SiteAyarlari(baslik="Test", alt_metin="", iletisim_notu=""))
        db.session.commit()

    response = client.get("/ready")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["database"] == "ok"
    assert payload["status"] == "ready"
    assert payload["missing_tables"] == []
    assert payload["seed_ready"] is True


def test_ready_endpoint_reports_missing_critical_tables(client, monkeypatch):
    import app as app_module

    original_table_exists = app_module.table_exists

    def fake_table_exists(table_name):
        if table_name == "site_ayarlari":
            return False
        return original_table_exists(table_name)

    monkeypatch.setattr(app_module, "table_exists", fake_table_exists)

    response = client.get("/ready")
    payload = response.get_json()

    assert response.status_code == 503
    assert payload["status"] == "degraded"
    assert payload["database"] == "schema_incomplete"
    assert "site_ayarlari" in payload["missing_tables"]
    assert payload["seed_ready"] is False


def test_ready_endpoint_reports_missing_seed_record(client, monkeypatch):
    import app as app_module

    monkeypatch.setattr(app_module, "_site_settings_seed_ready", lambda: False)

    response = client.get("/ready")
    payload = response.get_json()

    assert response.status_code == 503
    assert payload["status"] == "degraded"
    assert payload["database"] == "schema_incomplete"
    assert payload["missing_tables"] == []
    assert payload["seed_ready"] is False


def test_anonymous_user_cannot_access_admin_management(client):
    response = client.get("/kullanicilar")
    assert response.status_code in [302, 403]


def test_public_announcements_renders_with_snapshot_loader_failure(client):
    def broken_loader(*_args, **_kwargs):
        raise RuntimeError("temporary db issue")

    client.application.extensions["public_site_snapshot_loader"] = broken_loader

    response = client.get("/duyurular")
    assert response.status_code == 200
