from extensions import db
from models import WorkOrder, WorkOrderPartUsage
from tests.factories import (
    EquipmentTemplateFactory,
    HavalimaniFactory,
    InventoryAssetFactory,
    KullaniciFactory,
    SparePartFactory,
    SparePartStockFactory,
)


def _login(client, user):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


def test_work_order_close_consumes_spare_parts(client, app):
    airport = HavalimaniFactory(kodu="TZX")
    manager = KullaniciFactory(rol="yetkili", havalimani=airport)
    template = EquipmentTemplateFactory(name="Pompa")
    asset = InventoryAssetFactory(equipment_template=template, airport=airport, serial_no="P-01", qr_code="P-QR-01")
    spare_part = SparePartFactory(part_code="POMPA-FILTRE", title="Pompa Filtresi")
    stock = SparePartStockFactory(
        spare_part=spare_part,
        airport_stock=airport,
        quantity_on_hand=5,
        quantity_reserved=0,
        reorder_point=1,
    )
    work_order = WorkOrder(
        work_order_no="WO-PART-1",
        asset=asset,
        maintenance_type="bakim",
        description="Parça tüketimli bakım",
        created_user=manager,
        assigned_user=manager,
        status="acik",
        priority="orta",
    )
    db.session.add_all([airport, manager, template, asset, spare_part, stock, work_order])
    db.session.commit()
    _login(client, manager)

    response = client.post(
        f"/bakim/is-emri/{work_order.id}/kapat",
        data={
            "result": "Bakım tamamlandı",
            "used_parts": "POMPA-FILTRE:2",
            "labor_hours": 1.0,
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    usage = WorkOrderPartUsage.query.filter_by(work_order_id=work_order.id).first()
    assert usage is not None
    assert usage.quantity_used == 2

    db.session.refresh(stock)
    assert stock.quantity_on_hand == 3

