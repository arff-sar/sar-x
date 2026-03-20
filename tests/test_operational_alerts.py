from datetime import timedelta

from extensions import db
from models import AssetOperationalState, Notification, get_tr_now
from tests.factories import EquipmentTemplateFactory, HavalimaniFactory, InventoryAssetFactory, KullaniciFactory


def _login(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_warranty_and_out_of_service_alerts_are_created(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Kars Havalimanı", kodu="KSY")
        user = KullaniciFactory(rol="yetkili", havalimani=airport, is_deleted=False)
        template = EquipmentTemplateFactory(name="Gaz Ölçüm Cihazı", category="Olcum")
        asset = InventoryAssetFactory(
            equipment_template=template,
            airport=airport,
            status="aktif",
            warranty_end_date=get_tr_now().date() + timedelta(days=10),
        )
        db.session.add_all([airport, user, template, asset])
        db.session.flush()
        state = AssetOperationalState(asset_id=asset.id, lifecycle_status="out_of_service")
        asset.is_critical = True
        db.session.add(state)
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    response = client.get("/dashboard")
    assert response.status_code == 200
    sync_response = client.post("/dashboard/alerts/sync")
    assert sync_response.status_code == 204

    with app.app_context():
        warranty_notification = Notification.query.filter_by(user_id=user_id, type="warranty_expiring").first()
        service_notification = Notification.query.filter_by(user_id=user_id, type="critical_out_of_service").first()
        assert warranty_notification is not None
        assert service_notification is not None
