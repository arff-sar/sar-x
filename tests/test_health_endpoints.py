from extensions import db
from models import SiteAyarlari
from types import SimpleNamespace


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


def test_ready_endpoint_reports_migration_mismatch_in_production(client, app, monkeypatch):
    import app as app_module

    app.config["ENV"] = "production"

    monkeypatch.setattr(
        app_module,
        "_production_release_readiness_state",
        lambda _app: {
            "missing_tables": [],
            "missing_columns": [],
            "seed_ready": True,
            "migration_status": "behind",
            "expected_heads": ["head-expected"],
            "current_versions": ["head-current"],
        },
    )

    response = client.get("/ready")
    payload = response.get_json()

    assert response.status_code == 503
    assert payload["status"] == "degraded"
    assert payload["database"] == "schema_incomplete"
    assert payload["migration_status"] == "behind"
    assert payload["migration_expected_heads"] == ["head-expected"]
    assert payload["migration_current_versions"] == ["head-current"]


def test_anonymous_user_cannot_access_admin_management(client):
    response = client.get("/kullanicilar")
    assert response.status_code in [302, 403]


def test_public_announcements_renders_with_snapshot_loader_failure(client):
    def broken_loader(*_args, **_kwargs):
        raise RuntimeError("temporary db issue")

    client.application.extensions["public_site_snapshot_loader"] = broken_loader

    response = client.get("/duyurular")
    assert response.status_code == 200


def test_table_exists_uses_runtime_url_with_unmasked_password_during_isolated_inspection(app, monkeypatch):
    import extensions as extensions_module

    calls = {}

    class FakeURL:
        def __str__(self):
            return "postgresql://sarx:***@db.example.com/sarx"

        def render_as_string(self, hide_password=False):
            calls["hide_password"] = hide_password
            return "postgresql://sarx:real-secret@db.example.com/sarx"

    class FakeEngine:
        url = FakeURL()

    class FakeTempEngine:
        def dispose(self):
            calls["disposed"] = True

    class FakeInspector:
        def has_table(self, table_name):
            calls["table_name"] = table_name
            return True

    monkeypatch.setattr(extensions_module, "_session_in_transaction", lambda: True)
    monkeypatch.setattr(extensions_module, "_supports_isolated_inspection", lambda: True)
    monkeypatch.setattr(extensions_module, "db", SimpleNamespace(engine=FakeEngine()))

    def fake_create_engine(url, poolclass=None):
        calls["url"] = url
        calls["poolclass"] = poolclass
        return FakeTempEngine()

    monkeypatch.setattr(extensions_module, "create_engine", fake_create_engine)
    monkeypatch.setattr(extensions_module, "inspect", lambda target: FakeInspector())

    with app.app_context():
        app.extensions["schema_cache"] = {"tables": {}, "columns": {}}
        assert extensions_module.table_exists("auth_lockout") is True

    assert calls["hide_password"] is False
    assert calls["url"] == "postgresql://sarx:real-secret@db.example.com/sarx"
    assert calls["table_name"] == "auth_lockout"
    assert calls["disposed"] is True
