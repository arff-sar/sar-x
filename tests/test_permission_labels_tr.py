from extensions import db
from tests.factories import KullaniciFactory


def _login(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_permission_matrix_renders_turkish_labels_and_descriptions(client, app):
    user = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner@sarx.com")
    db.session.add(user)
    db.session.commit()
    user_id = user.id

    _login(client, user_id)
    response = client.get("/admin/permissions")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Gösterge Panelini Görüntüleme" in html
    assert "dashboard.view" in html
    assert 'data-tooltip-trigger' in html
    assert 'role="tooltip"' in html
    assert "Dashboard ekranı, kritik KPI kartları, uyarılar ve yönetici özet bloklarına erişebilir." in html


def test_user_and_role_screens_render_role_descriptions(client, app):
    owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner2@sarx.com")
    staff = KullaniciFactory(rol="bakim_sorumlusu", is_deleted=False, kullanici_adi="maint@sarx.com")
    db.session.add_all([owner, staff])
    db.session.commit()

    _login(client, owner.id)
    roles_response = client.get("/admin/roles")
    users_response = client.get(f"/kullanicilar?user_id={staff.id}")

    roles_html = roles_response.data.decode("utf-8")
    users_html = users_response.data.decode("utf-8")

    assert roles_response.status_code == 200
    assert users_response.status_code == 200
    assert "Bakım Sorumlusu" in roles_html
    assert "Bakım planları, iş emirleri ve bakım formlarını yönetebilir." in roles_html
    assert 'data-tooltip-trigger' in roles_html
    assert "Bakım Sorumlusu" in users_html
    assert "Bakım planları, iş emirleri ve bakım formlarını yönetebilir." in users_html
    assert f'data-selected-user-id="{staff.id}"' in users_html
