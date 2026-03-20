from demo_data import seed_demo_data
from extensions import db
from models import InventoryAsset, Kullanici, MaintenanceHistory, WorkOrder


def _login(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def _field_value(field_type):
    if field_type in {"checkbox", "boolean", "yes_no"}:
        return "evet"
    if field_type == "pass_fail":
        return "pass"
    if field_type in {"number", "numeric_reading"}:
        return "12"
    return "Demo saha kontrolu tamamlandi"


def test_demo_asset_maintenance_flow_can_be_completed(client, app):
    app.config["DEMO_TOOLS_ENABLED"] = True
    with app.app_context():
        seed_demo_data(reset=True)
        asset = InventoryAsset.query.filter_by(is_deleted=False).first()
        assert asset is not None
        asset_id = asset.id
        user = (
            Kullanici.query.filter_by(havalimani_id=asset.havalimani_id, is_deleted=False)
            .filter(Kullanici.rol.in_(["bakim_sorumlusu", "yetkili", "admin", "sahip", "personel"]))
            .first()
        )
        user_id = user.id

    _login(client, user_id)
    response = client.post(f"/bakim/asset/{asset_id}/hizli", follow_redirects=False)
    assert response.status_code == 302
    assert "/work-orders/" in response.headers["Location"]

    with app.app_context():
        order = (
            WorkOrder.query.filter_by(asset_id=asset_id, is_deleted=False)
            .order_by(WorkOrder.opened_at.desc())
            .first()
        )
        assert order is not None
        checklist_fields = order.checklist_template.fields if order.checklist_template else []
        payload = {
            "result": "Demo bakim tamamlandi",
            "extra_notes": "Checklist saha personeli tarafindan dolduruldu.",
            "labor_hours": "1.5",
        }
        for field in checklist_fields:
            payload[f"field_{field.id}"] = _field_value(field.field_type)

    close_response = client.post(
        f"/work-orders/{order.id}/quick-close",
        data=payload,
        follow_redirects=True,
    )
    html = close_response.data.decode("utf-8")

    assert close_response.status_code == 200
    assert "İş emri tamamlandı" in html or "İş emri hızlı akışla tamamlandı." in html

    with app.app_context():
        order = db.session.get(WorkOrder, order.id)
        assert order.status == "tamamlandi"
        history = MaintenanceHistory.query.filter_by(work_order_id=order.id).first()
        assert history is not None
        assert history.result == "Demo bakim tamamlandi"
