from extensions import db
from tests.factories import HavalimaniFactory, KullaniciFactory


def _login(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_sidebar_uses_single_open_group_and_direct_dashboard_link(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        user = KullaniciFactory(rol="sahip", havalimani=airport, is_deleted=False)
        db.session.add_all([airport, user])
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    response = client.get("/envanter")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert 'data-sidebar-direct="dashboard"' in html
    assert html.count('sidebar-group is-open') == 1
    assert 'data-group="operations"' in html
    assert "Kutu / Ünite Yönetimi" in html
    assert "Raporlar" not in html


def test_dashboard_page_does_not_force_other_groups_open(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Trabzon Havalimanı", kodu="TZX")
        user = KullaniciFactory(rol="yetkili", havalimani=airport, is_deleted=False)
        db.session.add_all([airport, user])
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    response = client.get("/dashboard")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert 'data-sidebar-direct="dashboard"' in html
    assert html.count('sidebar-group is-open') == 0
    assert "Raporlar" not in html


def test_operations_group_uses_accessible_toggle_markup_and_mobile_sync(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Dalaman Havalimanı", kodu="DLM")
        user = KullaniciFactory(rol="sahip", havalimani=airport, is_deleted=False)
        db.session.add_all([airport, user])
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    response = client.get("/envanter")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert 'id="sidebarGroupToggle-operations"' in html
    assert 'aria-controls="sidebarGroup-operations"' in html
    assert 'id="sidebarGroup-operations"' in html
    assert "syncSidebarState" in html
    assert "document.querySelectorAll('[data-sidebar-link]')" in html
