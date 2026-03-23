from extensions import db
from tests.factories import HavalimaniFactory, KullaniciFactory


def _login(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_editor_sees_content_menu_but_not_management(client, app):
    with app.app_context():
        user = KullaniciFactory(rol="editor", is_deleted=False)
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    response = client.get("/admin/homepage")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "İçerik Yönetimi" in html
    assert 'href="/kullanicilar"' not in html
    assert 'href="/site-yonetimi"' not in html
    assert "Raporlar" not in html
    assert 'sidebar-group is-open' in html


def test_airport_manager_only_sees_operational_groups(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        user = KullaniciFactory(rol="yetkili", havalimani=airport, is_deleted=False)
        db.session.add_all([airport, user])
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    response = client.get("/dashboard")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Operasyon" in html
    assert "İçerik Yönetimi" not in html
    assert "Site Ayarları" not in html
    assert "Roller / Yetkiler" not in html
    assert "Raporlar" not in html
