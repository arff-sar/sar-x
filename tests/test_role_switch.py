from extensions import db
from tests.factories import KullaniciFactory


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
    assert "Geçici aktif rolünüzü seçin" in html
    assert "Sistem Sahibi" in html
    assert "Salt Okunur" in html


def test_other_users_do_not_see_role_switch_dropdown(client, app):
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
    assert "Geçici aktif rolünüzü seçin" not in html


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
    response = client.post("/role-switch", data={"role": "readonly"}, follow_redirects=True)
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Geçici aktif rol güncellendi: Salt Okunur" in html
    assert "Geçici Rol" in html
    with client.session_transaction() as session:
        assert session.get("temporary_role_override") == "readonly"

    forbidden_response = client.get("/kullanicilar")
    assert forbidden_response.status_code == 403

    dashboard_response = client.get("/dashboard")
    assert dashboard_response.status_code == 200
    assert "Salt Okunur" in dashboard_response.data.decode("utf-8")


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
        session["temporary_role_override"] = "readonly"

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


def test_role_switch_endpoint_is_forbidden_for_other_users(client, app):
    with app.app_context():
        user = KullaniciFactory(
            rol="sahip",
            is_deleted=False,
            tam_ad="Yetkisiz Kullanıcı",
            kullanici_adi="owner@sarx.com",
        )
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    response = client.post("/role-switch", data={"role": "readonly"}, follow_redirects=False)

    assert response.status_code == 403
