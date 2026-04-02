from extensions import create_notification, db
from models import Notification
from tests.factories import KullaniciFactory


def _login(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_notification_created_and_marked_read(client, app):
    with app.app_context():
        user = KullaniciFactory(rol="personel", is_deleted=False)
        db.session.add(user)
        db.session.commit()
        notification = create_notification(
            user.id,
            "low_stock",
            "Düşük stok",
            "Kritik parça stoğu azaldı.",
            link_url="/yedek-parcalar",
            severity="warning",
        )
        user_id = user.id
        notification_id = notification.id

    _login(client, user_id)
    page = client.get("/admin/notifications")
    assert page.status_code == 200
    assert "Düşük stok" in page.data.decode("utf-8")

    response = client.post(f"/admin/notifications/read/{notification_id}", follow_redirects=False)
    assert response.status_code == 302
    with app.app_context():
        item = db.session.get(Notification, notification_id)
        assert item.is_read is True


def test_mark_all_notifications_read(client, app):
    with app.app_context():
        user = KullaniciFactory(rol="personel", is_deleted=False)
        db.session.add(user)
        db.session.commit()
        create_notification(user.id, "info", "Test 1", "Mesaj 1")
        create_notification(user.id, "info", "Test 2", "Mesaj 2")
        user_id = user.id

    _login(client, user_id)
    response = client.post("/admin/notifications/read-all", follow_redirects=True)
    assert response.status_code == 200
    with app.app_context():
        unread = Notification.query.filter_by(user_id=user_id, is_read=False).count()
        assert unread == 0


def test_notification_read_redirect_rejects_external_link(client, app):
    with app.app_context():
        user = KullaniciFactory(rol="personel", is_deleted=False)
        db.session.add(user)
        db.session.commit()
        notification = create_notification(
            user.id,
            "security-check",
            "Güvenlik",
            "Harici link fallback testi",
            link_url="https://attacker.example/phish",
            severity="info",
        )
        user_id = user.id
        notification_id = notification.id

    _login(client, user_id)
    response = client.post(f"/admin/notifications/read/{notification_id}", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/admin/notifications")
