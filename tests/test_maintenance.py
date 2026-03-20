from datetime import timedelta

from extensions import db
from models import WorkOrder, get_tr_now
from tests.factories import EquipmentTemplateFactory, HavalimaniFactory, InventoryAssetFactory, KullaniciFactory


def _login(client, user):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


def test_unauthorized_user_cannot_manage_maintenance(client, app):
    airport = HavalimaniFactory(kodu="IST")
    personel = KullaniciFactory(rol="personel", havalimani=airport)
    db.session.add_all([airport, personel])
    db.session.commit()
    _login(client, personel)

    response = client.get("/bakim/is-emri/yeni")
    assert response.status_code == 403


def test_maintenance_statistics_and_open_orders_api(client, app):
    today = get_tr_now().date()
    airport = HavalimaniFactory(kodu="ESB")
    owner = KullaniciFactory(rol="sahip")
    template = EquipmentTemplateFactory(name="Pompa", maintenance_period_days=10)
    asset_due = InventoryAssetFactory(
        equipment_template=template,
        airport=airport,
        serial_no="API-SN-1",
        qr_code="API-QR-1",
        next_maintenance_date=today + timedelta(days=2),
        is_critical=True,
        status="arizali",
    )
    asset_overdue = InventoryAssetFactory(
        equipment_template=template,
        airport=airport,
        serial_no="API-SN-2",
        qr_code="API-QR-2",
        next_maintenance_date=today - timedelta(days=1),
    )
    open_order = WorkOrder(
        work_order_no="WO-API-1",
        asset=asset_due,
        maintenance_type="ariza",
        description="Pompa arızası",
        created_user=owner,
        status="acik",
        priority="kritik",
    )
    db.session.add_all([airport, owner, template, asset_due, asset_overdue, open_order])
    db.session.commit()
    _login(client, owner)

    stats_resp = client.get("/api/bakim/istatistikler")
    assert stats_resp.status_code == 200
    stats = stats_resp.get_json()["veri"]
    assert stats["yaklasan_bakim"] >= 1
    assert stats["geciken_bakim"] >= 1
    assert stats["acik_is_emri"] >= 1
    assert stats["kritik_ariza"] >= 1

    order_resp = client.get("/api/bakim/acik-is-emirleri")
    assert order_resp.status_code == 200
    order_rows = order_resp.get_json()["veri"]
    assert any(row["is_emri_no"] == "WO-API-1" for row in order_rows)


def test_upcoming_and_history_endpoints_work(client, app):
    today = get_tr_now().date()
    airport = HavalimaniFactory(kodu="SAW")
    manager = KullaniciFactory(rol="yetkili", havalimani=airport)
    template = EquipmentTemplateFactory(name="Gaz Dedektörü", maintenance_period_days=15)
    asset = InventoryAssetFactory(
        equipment_template=template,
        airport=airport,
        serial_no="HIS-SN-1",
        qr_code="HIS-QR-1",
        next_maintenance_date=today + timedelta(days=5),
    )
    db.session.add_all([airport, manager, template, asset])
    db.session.commit()
    _login(client, manager)

    upcoming_resp = client.get("/api/bakim/yaklasan-kayitlar")
    assert upcoming_resp.status_code == 200
    upcoming_rows = upcoming_resp.get_json()["veri"]
    assert any(row["asset_id"] == asset.id for row in upcoming_rows)

    work_order = WorkOrder(
        work_order_no="WO-HIS-1",
        asset=asset,
        maintenance_type="bakim",
        description="Periyodik bakım",
        created_user=manager,
        assigned_user=manager,
        status="acik",
        priority="orta",
    )
    db.session.add(work_order)
    db.session.commit()

    client.post(
        f"/bakim/is-emri/{work_order.id}/kapat",
        data={"result": "Tamamlandı"},
        follow_redirects=True,
    )

    history_resp = client.get(f"/api/bakim/asset/{asset.id}/gecmis")
    assert history_resp.status_code == 200
    history_rows = history_resp.get_json()["veri"]
    assert len(history_rows) >= 1


def test_maintenance_api_requires_permission(client, app):
    airport = HavalimaniFactory(kodu="BTZ")
    warehouse_user = KullaniciFactory(rol="depo_sorumlusu", havalimani=airport)
    db.session.add_all([airport, warehouse_user])
    db.session.commit()
    _login(client, warehouse_user)

    response = client.get("/api/bakim/istatistikler")

    assert response.status_code == 403
