from extensions import db
from models import Role
from tests.factories import HavalimaniFactory, KullaniciFactory


def _login(client, user_id):
    with client.session_transaction() as session:
        session.clear()
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_mehmet_user_sees_role_switch_dropdown(client, app):
    with app.app_context():
        user = KullaniciFactory(
            rol="sahip",
            is_deleted=False,
            tam_ad="Mehmet",
            kullanici_adi="mehmetcinocevi@gmail.com",
        )
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    response = client.get("/dashboard")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert 'id="userMenuToggle"' in html
    assert 'id="roleSwitchLaunch"' in html
    assert 'aria-label="Rol değiştir menüsünü aç"' in html
    assert "Geçici aktif rolünüzü seçin" in html
    assert "Sistem Sorumlusu" in html
    assert "Ekip Sorumlusu" in html
    assert "Ekip Üyesi" in html
    assert "Admin" in html
    assert "Bakım Sorumlusu" not in html
    assert "Salt Okunur" not in html


def test_non_allow_list_owner_does_not_see_role_switch_dropdown(client, app):
    with app.app_context():
        user = KullaniciFactory(
            rol="sahip",
            is_deleted=False,
            tam_ad="Başka Kullanıcı",
            kullanici_adi="owner@sarx.com",
        )
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    response = client.get("/dashboard")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert 'id="userMenuToggle"' not in html
    assert 'id="roleSwitchLaunch"' not in html
    assert "Geçici aktif rolünüzü seçin" not in html


def test_non_allow_list_owner_cannot_switch_role(client, app):
    with app.app_context():
        user = KullaniciFactory(
            rol="sistem_sahibi",
            is_deleted=False,
            tam_ad="Legacy Sistem Sahibi",
            kullanici_adi="legacy-owner@sarx.com",
        )
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    response = client.post("/role-switch", data={"role": "admin"}, follow_redirects=False)
    assert response.status_code == 403


def test_mehmet_user_can_switch_role_and_session_persists(client, app):
    with app.app_context():
        user = KullaniciFactory(
            rol="sahip",
            is_deleted=False,
            tam_ad="Mehmet",
            kullanici_adi="mehmetcinocevi@gmail.com",
        )
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    response = client.post("/role-switch", data={"role": "admin"}, follow_redirects=True)
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Geçici aktif rol güncellendi: Admin" in html
    assert "Geçici Rol" in html
    with client.session_transaction() as session:
        assert session.get("temporary_role_override") == "admin"

    users_response = client.get("/kullanicilar")
    assert users_response.status_code == 403

    dashboard_response = client.get("/dashboard")
    assert dashboard_response.status_code == 200
    assert "Admin" in dashboard_response.data.decode("utf-8")
    with app.app_context():
        refreshed = db.session.get(type(user), user_id)
        assert refreshed.rol == "sahip"


def test_mehmet_user_can_clear_role_override(client, app):
    with app.app_context():
        user = KullaniciFactory(
            rol="sahip",
            is_deleted=False,
            tam_ad="Mehmet",
            kullanici_adi="mehmetcinocevi@gmail.com",
        )
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    with client.session_transaction() as session:
        session["temporary_role_override"] = "admin"

    response = client.post("/role-switch", data={"role": "__default__"}, follow_redirects=True)
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Geçici rol kaldırıldı. Varsayılan rolünüz yeniden etkin." in html
    with client.session_transaction() as session:
        assert "temporary_role_override" not in session


def test_role_switch_rejects_unsupported_roles(client, app):
    with app.app_context():
        user = KullaniciFactory(
            rol="sahip",
            is_deleted=False,
            tam_ad="Mehmet",
            kullanici_adi="mehmetcinocevi@gmail.com",
        )
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    response = client.post("/role-switch", data={"role": "unsupported-role"}, follow_redirects=True)
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Desteklenmeyen rol seçimi gönderildi." in html
    with client.session_transaction() as session:
        assert "temporary_role_override" not in session


def test_role_switch_dropdown_lists_active_custom_roles_from_db(client, app):
    with app.app_context():
        user = KullaniciFactory(
            rol="sahip",
            is_deleted=False,
            tam_ad="Mehmet",
            kullanici_adi="mehmetcinocevi@gmail.com",
        )
        custom_role = Role(
            key="operasyon_izleyici",
            label="Operasyon İzleyici",
            scope="global",
            is_system=False,
            is_active=True,
        )
        inactive_role = Role(
            key="pasif_rol",
            label="Pasif Rol",
            scope="global",
            is_system=False,
            is_active=False,
        )
        db.session.add_all([user, custom_role, inactive_role])
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    response = client.get("/dashboard")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Operasyon İzleyici" in html
    assert "Pasif Rol" not in html


def test_role_switch_endpoint_is_forbidden_for_other_users(client, app):
    with app.app_context():
        user = KullaniciFactory(
            rol="personel",
            is_deleted=False,
            tam_ad="Yetkisiz Kullanıcı",
            kullanici_adi="personel@sarx.com",
        )
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    response = client.post("/role-switch", data={"role": "admin"}, follow_redirects=False)

    assert response.status_code == 403


def test_non_privileged_user_does_not_see_role_switch_dropdown(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Rize-Artvin Havalimanı", kodu="RZV")
        user = KullaniciFactory(
            rol="personel",
            havalimani=airport,
            is_deleted=False,
            tam_ad="Yetkisiz Personel",
            kullanici_adi="personel@sarx.com",
        )
        db.session.add_all([airport, user])
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    response = client.get("/dashboard")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert 'id="userMenuToggle"' not in html
    assert "Geçici aktif rolünüzü seçin" not in html


def test_role_switch_override_is_cleared_on_logout(client, app):
    with app.app_context():
        user = KullaniciFactory(
            rol="sahip",
            is_deleted=False,
            tam_ad="Mehmet",
            kullanici_adi="mehmetcinocevi@gmail.com",
        )
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    client.post("/role-switch", data={"role": "admin"}, follow_redirects=True)
    response = client.post("/logout", follow_redirects=True)

    assert response.status_code == 200
    with client.session_transaction() as session:
        assert "temporary_role_override" not in session


def test_invalid_or_inactive_role_override_is_sanitized_on_request(client, app):
    with app.app_context():
        user = KullaniciFactory(
            rol="sahip",
            is_deleted=False,
            tam_ad="Mehmet",
            kullanici_adi="mehmetcinocevi@gmail.com",
        )
        inactive_role = Role(
            key="pasif_rol",
            label="Pasif Rol",
            scope="global",
            is_system=False,
            is_active=False,
        )
        db.session.add_all([user, inactive_role])
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    with client.session_transaction() as session:
        session["temporary_role_override"] = "pasif_rol"

    response = client.get("/dashboard")
    assert response.status_code == 200
    with client.session_transaction() as session:
        assert "temporary_role_override" not in session


def test_control_plane_endpoints_blocked_during_impersonation(client, app):
    with app.app_context():
        user = KullaniciFactory(
            rol="sahip",
            is_deleted=False,
            tam_ad="Mehmet",
            kullanici_adi="mehmetcinocevi@gmail.com",
        )
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    client.post("/role-switch", data={"role": "admin"}, follow_redirects=True)
    response = client.get("/admin/roles", follow_redirects=False)
    assert response.status_code == 403


def test_settings_control_plane_endpoints_blocked_during_impersonation(client, app):
    with app.app_context():
        user = KullaniciFactory(
            rol="sahip",
            is_deleted=False,
            tam_ad="Mehmet",
            kullanici_adi="mehmetcinocevi@gmail.com",
        )
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    client.post("/role-switch", data={"role": "admin"}, follow_redirects=True)
    response = client.post("/demo-veri/olustur", data={"confirm_demo_seed": "DEMO"}, follow_redirects=False)
    assert response.status_code == 403


def test_role_switch_audit_payload_tracks_real_and_effective_roles(client, app, monkeypatch):
    events = []

    def _fake_audit(event, outcome="success", **context):
        events.append((event, outcome, context))

    monkeypatch.setattr("routes.auth.audit_log", _fake_audit)

    with app.app_context():
        user = KullaniciFactory(
            rol="sahip",
            is_deleted=False,
            tam_ad="Mehmet",
            kullanici_adi="mehmetcinocevi@gmail.com",
        )
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    response = client.post("/role-switch", data={"role": "admin"}, follow_redirects=False)
    assert response.status_code == 302

    switch_events = [item for item in events if item[0].startswith("auth.role_switch")]
    assert switch_events
    _, _, payload = switch_events[-1]
    assert payload["real_user_email"] == "mehmetcinocevi@gmail.com"
    assert payload["base_role"] == "sahip"
    assert payload["acting_role"] == "admin"
