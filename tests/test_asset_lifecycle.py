from extensions import db
from models import InventoryAsset, IslemLog, Malzeme
from tests.factories import EquipmentTemplateFactory, HavalimaniFactory, InventoryAssetFactory, KutuFactory, KullaniciFactory, MalzemeFactory


def _login(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_asset_lifecycle_logs_disposed_and_transfer_updates_location(client, app):
    with app.app_context():
        airport_one = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        airport_two = HavalimaniFactory(ad="Kars Havalimanı", kodu="KSY")
        manager = KullaniciFactory(rol="admin", havalimani=airport_one, is_deleted=False)
        template = EquipmentTemplateFactory(name="Termal Kamera", category="Olcum")
        box = KutuFactory(kodu="ERZ-KUTU-01", havalimani=airport_one)
        material = MalzemeFactory(ad="Termal Kamera", kutu=box, havalimani=airport_one, is_deleted=False)
        transfer_material = MalzemeFactory(ad="Projektor", kutu=box, havalimani=airport_one, is_deleted=False)
        disposed_asset = InventoryAssetFactory(equipment_template=template, airport=airport_one, depot_location=box.kodu, status="aktif")
        transfer_asset = InventoryAssetFactory(equipment_template=template, airport=airport_one, depot_location=box.kodu, status="aktif")
        db.session.add_all([airport_one, airport_two, manager, template, box, material, transfer_material, disposed_asset, transfer_asset])
        db.session.flush()
        disposed_asset.legacy_material_id = material.id
        transfer_asset.legacy_material_id = transfer_material.id
        db.session.commit()
        manager_id = manager.id
        disposed_asset_id = disposed_asset.id
        transfer_asset_id = transfer_asset.id
        airport_two_id = airport_two.id

    _login(client, manager_id)
    dispose_response = client.post(
        "/asset-lifecycle",
        data={"asset_id": str(disposed_asset_id), "lifecycle_status": "disposed", "lifecycle_note": "Hurdaya ayrıldı"},
        follow_redirects=True,
    )
    inventory_response = client.get("/envanter")
    html = inventory_response.data.decode("utf-8")
    transfer_response = client.post(
        "/asset-lifecycle",
        data={"asset_id": str(transfer_asset_id), "lifecycle_status": "transferred", "target_airport_id": str(airport_two_id), "lifecycle_note": "Birim devri"},
        follow_redirects=True,
    )

    assert dispose_response.status_code == 200
    assert transfer_response.status_code == 200
    assert inventory_response.status_code == 200

    with app.app_context():
        disposed_asset = db.session.get(InventoryAsset, disposed_asset_id)
        transfer_asset = db.session.get(InventoryAsset, transfer_asset_id)
        transfer_material = Malzeme.query.filter_by(id=transfer_asset.legacy_material_id).first()
        log_row = IslemLog.query.filter_by(event_key="asset.lifecycle.change", target_id=transfer_asset_id).first()
        assert log_row is not None
        assert disposed_asset.lifecycle_status == "disposed"
        assert transfer_asset.havalimani_id == airport_two_id
        assert transfer_material.havalimani_id == airport_two_id
        assert "Termal Kamera" not in html
