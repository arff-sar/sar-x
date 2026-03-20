from datetime import timedelta

from extensions import db
from models import MaintenanceHistory, MaintenancePlan, WorkOrder, get_tr_now
from tests.factories import EquipmentTemplateFactory, HavalimaniFactory, InventoryAssetFactory, KullaniciFactory


def _login(client, user):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


def test_work_order_can_be_opened_and_closed(client, app):
    airport = HavalimaniFactory(kodu="ESB")
    manager = KullaniciFactory(rol="yetkili", havalimani=airport)
    template = EquipmentTemplateFactory(name="Solunum Seti", maintenance_period_days=30)
    asset = InventoryAssetFactory(equipment_template=template, airport=airport, serial_no="WO-SN-1", qr_code="WO-QR-1")
    db.session.add_all([airport, manager, template, asset])
    db.session.commit()
    _login(client, manager)

    create_response = client.post(
        "/bakim/is-emri/yeni",
        data={
            "asset_id": asset.id,
            "maintenance_type": "bakim",
            "description": "Aylık kontrol",
            "priority": "orta",
            "target_date": get_tr_now().date().strftime("%Y-%m-%d"),
            "assigned_user_id": manager.id,
        },
        follow_redirects=True,
    )
    assert create_response.status_code == 200

    work_order = WorkOrder.query.order_by(WorkOrder.id.desc()).first()
    assert work_order is not None
    assert work_order.status == "acik"

    close_response = client.post(
        f"/bakim/is-emri/{work_order.id}/kapat",
        data={
            "result": "Bakım tamamlandı",
            "used_parts": "Filtre",
            "labor_hours": 1.5,
            "extra_notes": "Test başarılı",
        },
        follow_redirects=True,
    )
    assert close_response.status_code == 200

    db.session.refresh(work_order)
    assert work_order.status == "tamamlandi"
    assert work_order.completed_at is not None
    history = MaintenanceHistory.query.filter_by(work_order_id=work_order.id).first()
    assert history is not None


def test_next_maintenance_date_is_calculated_after_closure(client, app):
    today = get_tr_now().date()
    airport = HavalimaniFactory(kodu="ADB")
    owner = KullaniciFactory(rol="sahip")
    template = EquipmentTemplateFactory(name="Basınç Tüpü", maintenance_period_days=20)
    asset = InventoryAssetFactory(
        equipment_template=template,
        airport=airport,
        serial_no="PLAN-SN-1",
        qr_code="PLAN-QR-1",
        maintenance_period_days=20,
    )
    plan = MaintenancePlan(
        name="Test Plan",
        asset=asset,
        equipment_template=template,
        owner_airport_id=airport.id,
        period_days=20,
        start_date=today,
        is_active=True,
    )
    work_order = WorkOrder(
        work_order_no="WO-PLAN-1",
        asset=asset,
        maintenance_type="bakim",
        description="Planlı bakım",
        created_user=owner,
        assigned_user=owner,
        status="acik",
        priority="yuksek",
    )
    db.session.add_all([airport, owner, template, asset, plan, work_order])
    db.session.commit()
    _login(client, owner)

    response = client.post(
        f"/bakim/is-emri/{work_order.id}/kapat",
        data={"result": "Tamamlandı"},
        follow_redirects=True,
    )
    assert response.status_code == 200

    db.session.refresh(asset)
    expected_date = today + timedelta(days=20)
    assert asset.next_maintenance_date == expected_date
