from extensions import db
from models import ConsumableItem, ConsumableStockMovement, Notification
from tests.factories import HavalimaniFactory, KullaniciFactory


def _login(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_consumable_out_movement_reduces_stock_and_creates_alert(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        user = KullaniciFactory(rol="depo_sorumlusu", havalimani=airport, is_deleted=False)
        item = ConsumableItem(code="CON-TST", title="Eldiven", category="KKD", unit="kutu", min_stock_level=5, critical_level=2, is_active=True)
        db.session.add_all([airport, user, item])
        db.session.flush()
        db.session.add(
            ConsumableStockMovement(
                consumable_id=item.id,
                airport_id=airport.id,
                movement_type="in",
                quantity=6,
                performed_by_id=user.id,
            )
        )
        db.session.commit()
        user_id = user.id
        item_id = item.id

    _login(client, user_id)
    response = client.post(
        "/sarf-malzemeler",
        data={
            "item_id": str(item_id),
            "movement_type": "out",
            "quantity": "5",
            "reference_note": "Saha kullanımı",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    with app.app_context():
        movements = ConsumableStockMovement.query.filter_by(consumable_id=item_id, is_deleted=False).all()
        balance = sum((1 if row.movement_type in {"in", "adjust", "transfer"} else -1) * float(row.quantity or 0) for row in movements)
        assert balance == 1
        notification = Notification.query.filter_by(user_id=user_id, type="consumable_critical_stock").first()
        assert notification is not None
