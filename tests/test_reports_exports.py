from extensions import db
from tests.factories import EquipmentTemplateFactory, HavalimaniFactory, InventoryAssetFactory, KullaniciFactory


def _login(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_reports_export_is_closed_for_unauthorized_user(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Kars Havalimanı", kodu="KSY")
        user = KullaniciFactory(rol="personel", havalimani=airport, is_deleted=False)
        db.session.add_all([airport, user])
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    response = client.get("/reports/export/inventory/csv")
    assert response.status_code == 403


def test_reports_export_respects_row_limit(client, app):
    app.config["MAX_EXPORT_ROWS"] = 1
    with app.app_context():
        airport = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        template = EquipmentTemplateFactory(name="Kesici", category="Kurtarma")
        asset_one = InventoryAssetFactory(equipment_template=template, airport=airport, serial_no="ERZ-A1")
        asset_two = InventoryAssetFactory(equipment_template=template, airport=airport, serial_no="ERZ-A2")
        user = KullaniciFactory(rol="sahip", havalimani=airport, is_deleted=False)
        db.session.add_all([airport, template, asset_one, asset_two, user])
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    response = client.get("/reports/export/inventory/csv", follow_redirects=True)
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "satır limitini aşıyor" in html
