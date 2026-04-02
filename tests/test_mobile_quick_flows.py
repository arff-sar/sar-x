from extensions import db
from models import MaintenanceFormField, MaintenanceFormTemplate, WorkOrder
from tests.factories import EquipmentTemplateFactory, HavalimaniFactory, InventoryAssetFactory, KullaniciFactory


def _login(client, user):
    with client.session_transaction() as sess:
        sess.clear()
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


def test_quick_asset_route_updates_status(client, app):
    airport = HavalimaniFactory(kodu="RZE")
    manager = KullaniciFactory(rol="yetkili", havalimani=airport)
    template = EquipmentTemplateFactory(name="Kesici")
    asset = InventoryAssetFactory(equipment_template=template, airport=airport, serial_no="K-01", qr_code="K-QR-01")
    db.session.add_all([airport, manager, template, asset])
    db.session.commit()
    _login(client, manager)

    response = client.post(
        f"/asset/{asset.id}/quick",
        data={"status": "arizali", "maintenance_state": "ariza", "note": "Sahada arıza tespiti"},
        follow_redirects=True,
    )
    assert response.status_code == 200

    db.session.refresh(asset)
    assert asset.status == "pasif"


def test_mobile_inspection_can_open_corrective_work_order(client, app):
    airport = HavalimaniFactory(kodu="VAN")
    manager = KullaniciFactory(rol="yetkili", havalimani=airport)
    template = EquipmentTemplateFactory(name="Gaz Dedektörü")
    asset = InventoryAssetFactory(equipment_template=template, airport=airport, serial_no="GD-01", qr_code="GD-QR-01")
    checklist = MaintenanceFormTemplate(name="Mobil Inspection Formu", description="Test")
    db.session.add_all([airport, manager, template, asset, checklist])
    db.session.flush()
    field = MaintenanceFormField(
        form_template_id=checklist.id,
        field_key="kritik_sensor_kontrolu",
        label="Kritik Sensör Kontrolü",
        field_type="pass_fail",
        is_required=True,
        order_index=1,
    )
    db.session.add(field)
    db.session.flush()

    order = WorkOrder(
        work_order_no="WO-MOB-1",
        asset=asset,
        maintenance_type="kontrol",
        work_order_type="inspection",
        description="Saha inspection",
        created_user=manager,
        assigned_user=manager,
        status="acik",
        priority="orta",
        checklist_template_id=checklist.id,
    )
    db.session.add(order)
    db.session.commit()
    _login(client, manager)

    response = client.post(
        f"/inspection/{order.id}/mobile",
        data={f"field_{field.id}": "fail", "auto_corrective": "on"},
        follow_redirects=True,
    )
    assert response.status_code == 200

    corrective = WorkOrder.query.filter_by(source_type="inspection_failure", asset_id=asset.id).first()
    assert corrective is not None
    assert corrective.work_order_type == "corrective"


def test_quick_close_route_completes_work_order(client, app):
    airport = HavalimaniFactory(kodu="ERZ")
    manager = KullaniciFactory(rol="yetkili", havalimani=airport)
    template = EquipmentTemplateFactory(name="Hidrolik Kesici")
    asset = InventoryAssetFactory(equipment_template=template, airport=airport, serial_no="HK-01", qr_code="HK-QR-01")
    order = WorkOrder(
        work_order_no="WO-QC-1",
        asset=asset,
        maintenance_type="bakim",
        description="Hızlı kapanış testi",
        created_user=manager,
        assigned_user=manager,
        status="acik",
        priority="orta",
    )
    db.session.add_all([airport, manager, template, asset, order])
    db.session.commit()
    _login(client, manager)

    response = client.post(
        f"/work-orders/{order.id}/quick-close",
        data={"result": "Tamamlandı", "labor_hours": 0.5},
        follow_redirects=True,
    )
    assert response.status_code == 200
    db.session.refresh(order)
    assert order.status == "tamamlandi"


def test_legacy_quick_maintenance_get_opens_real_work_order_form(client, app):
    airport = HavalimaniFactory(kodu="GZT")
    manager = KullaniciFactory(rol="sahip", havalimani=airport)
    template = EquipmentTemplateFactory(name="Projektor")
    asset = InventoryAssetFactory(equipment_template=template, airport=airport, serial_no="PRJ-01", qr_code="PRJ-QR-01")
    db.session.add_all([airport, manager, template, asset])
    db.session.commit()
    _login(client, manager)

    response = client.get(f"/bakim/asset/{asset.id}/hizli", follow_redirects=False)

    assert response.status_code == 302
    assert "/work-orders/" in response.headers["Location"]
    assert "/quick-close" in response.headers["Location"]
    assert WorkOrder.query.filter_by(asset_id=asset.id).count() == 1
