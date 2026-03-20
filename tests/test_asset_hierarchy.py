from extensions import db
from models import InventoryAsset
from tests.factories import EquipmentTemplateFactory, HavalimaniFactory, InventoryAssetFactory, KullaniciFactory


def _login(client, user):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


def test_parent_child_asset_relationship_and_hierarchy_route(client, app):
    airport = HavalimaniFactory(kodu="HTY")
    manager = KullaniciFactory(rol="yetkili", havalimani=airport)
    template = EquipmentTemplateFactory(name="ARFF Aracı")
    parent_asset = InventoryAssetFactory(equipment_template=template, airport=airport, serial_no="PARENT-1", qr_code="PARENT-QR-1")
    child_asset = InventoryAssetFactory(
        equipment_template=template,
        airport=airport,
        serial_no="CHILD-1",
        qr_code="CHILD-QR-1",
        parent_asset=parent_asset,
    )
    db.session.add_all([airport, manager, template, parent_asset, child_asset])
    db.session.commit()

    _login(client, manager)
    response = client.get(f"/asset/{parent_asset.id}/hiyerarsi")
    assert response.status_code == 200
    assert "CHILD-1" in response.data.decode("utf-8")

    refreshed_child = db.session.get(InventoryAsset, child_asset.id)
    assert refreshed_child.parent_asset_id == parent_asset.id

