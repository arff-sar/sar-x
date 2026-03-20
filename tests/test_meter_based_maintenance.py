from extensions import db
from models import MaintenanceTriggerRule, MeterDefinition, WorkOrder
from tests.factories import EquipmentTemplateFactory, HavalimaniFactory, InventoryAssetFactory, KullaniciFactory


def _login(client, user):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


def test_meter_reading_can_trigger_work_order(client, app):
    airport = HavalimaniFactory(kodu="AYT")
    manager = KullaniciFactory(rol="yetkili", havalimani=airport)
    template = EquipmentTemplateFactory(name="Jeneratör")
    asset = InventoryAssetFactory(equipment_template=template, airport=airport, serial_no="GEN-01", qr_code="GEN-QR-01")
    db.session.add_all([airport, manager, template, asset])
    db.session.flush()
    meter = MeterDefinition(name="Çalışma Saati", meter_type="hours", unit="h", asset_id=asset.id, equipment_template_id=template.id)
    db.session.add(meter)
    db.session.flush()

    trigger = MaintenanceTriggerRule(
        name="100 Saat Bakım",
        trigger_type="hours",
        asset_id=asset.id,
        equipment_template_id=template.id,
        meter_definition_id=meter.id,
        threshold_value=100,
        warning_lead_value=10,
        auto_create_work_order=True,
        is_active=True,
    )
    db.session.add(trigger)
    db.session.commit()
    _login(client, manager)

    response = client.post(
        "/bakim/sayaclar",
        data={
            "asset_id": asset.id,
            "meter_definition_id": meter.id,
            "reading_value": 105,
            "note": "Saha okuması",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    created_order = WorkOrder.query.filter_by(asset_id=asset.id, source_type="meter_trigger").first()
    assert created_order is not None

    meter_history_response = client.get(f"/api/bakim/asset/{asset.id}/sayac-gecmisi")
    assert meter_history_response.status_code == 200
    meter_rows = meter_history_response.get_json()["veri"]
    assert any(row["value"] == 105 for row in meter_rows)
