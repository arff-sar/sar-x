from extensions import db
from tests.factories import EquipmentTemplateFactory, HavalimaniFactory, InventoryAssetFactory, KullaniciFactory


def _login(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_role_labels_render_in_turkish_with_tooltips(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        owner = KullaniciFactory(rol="sahip", havalimani=airport, is_deleted=False)
        admin_user = KullaniciFactory(rol="admin", havalimani=airport, tam_ad="Admin Kullanici", is_deleted=False)
        editor_user = KullaniciFactory(rol="editor", tam_ad="Editor Kullanici", is_deleted=False)
        db.session.add_all([airport, owner, admin_user, editor_user])
        db.session.commit()
        owner_id = owner.id
        admin_user_id = admin_user.id

    _login(client, owner_id)
    response = client.get(f"/kullanicilar?user_id={admin_user_id}")
    roles_response = client.get("/admin/roles")
    html = response.data.decode("utf-8")
    roles_html = roles_response.data.decode("utf-8")

    assert response.status_code == 200
    assert roles_response.status_code == 200
    assert "Admin" in html
    assert "Tüm havalimanlarını readonly kapsamda izler; kayıtları denetler, ancak değişiklik yapmaz." in html
    assert f'data-selected-user-id="{admin_user_id}"' in html
    assert "Ekip Üyesi" in roles_html
    assert 'data-tooltip-trigger' in roles_html


def test_hierarchy_action_is_hidden_from_quick_asset_view(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Trabzon Havalimanı", kodu="TZX")
        template = EquipmentTemplateFactory(name="Jenerator")
        user = KullaniciFactory(rol="bakim_sorumlusu", havalimani=airport, is_deleted=False)
        asset = InventoryAssetFactory(equipment_template=template, airport=airport, status="aktif")
        db.session.add_all([airport, template, user, asset])
        db.session.commit()
        user_id = user.id
        asset_id = asset.id

    _login(client, user_id)
    response = client.get(f"/asset/{asset_id}/quick")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Hiyerarşi" not in html
    assert "Bakım Akışı Başlat" in html or "Bakım Formunu Aç" in html
