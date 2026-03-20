from datetime import timedelta

from extensions import db
from models import CalibrationSchedule, Notification, get_tr_now
from tests.factories import EquipmentTemplateFactory, HavalimaniFactory, InventoryAssetFactory, KullaniciFactory


def _login(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_calibration_overdue_filter_and_upcoming_notification(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Trabzon Havalimanı", kodu="TZX")
        user = KullaniciFactory(rol="bakim_sorumlusu", havalimani=airport, is_deleted=False)
        template = EquipmentTemplateFactory(name="Gaz Ölçüm Cihazı", category="Olcum")
        overdue_asset = InventoryAssetFactory(equipment_template=template, airport=airport, next_calibration_date=get_tr_now().date() - timedelta(days=2))
        upcoming_asset = InventoryAssetFactory(equipment_template=template, airport=airport, next_calibration_date=get_tr_now().date() + timedelta(days=5))
        db.session.add_all([airport, user, template, overdue_asset, upcoming_asset])
        db.session.flush()
        db.session.add_all([
            CalibrationSchedule(asset_id=overdue_asset.id, period_days=180, warning_days=15, provider="Lab A", is_active=True),
            CalibrationSchedule(asset_id=upcoming_asset.id, period_days=180, warning_days=15, provider="Lab B", is_active=True),
        ])
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    report_response = client.get("/reports?report=calibration&calibration_state=overdue")
    dashboard_response = client.get("/dashboard")
    sync_response = client.post("/dashboard/alerts/sync")
    report_html = report_response.data.decode("utf-8")

    assert report_response.status_code == 200
    assert dashboard_response.status_code == 200
    assert sync_response.status_code == 204
    assert "Gaz Ölçüm Cihazı" in report_html
    assert "gecikmis" in report_html

    with app.app_context():
        notification = Notification.query.filter_by(user_id=user_id, type="calibration_upcoming").first()
        assert notification is not None
