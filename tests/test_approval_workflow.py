from decorators import sync_authorization_registry
from extensions import db
from models import ApprovalRequest, IslemLog, Kullanici
from tests.factories import KullaniciFactory


def _login(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_role_change_can_become_pending_and_applied_after_approval(client, app):
    with app.app_context():
        sync_authorization_registry()
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner@sarx.com")
        admin = KullaniciFactory(rol="admin", is_deleted=False, kullanici_adi="admin@sarx.com")
        target = KullaniciFactory(rol="personel", is_deleted=False, kullanici_adi="target@sarx.com")
        db.session.add_all([owner, admin, target])
        db.session.commit()
        owner_id, admin_id, target_id = owner.id, admin.id, target.id

    _login(client, admin_id)
    response = client.post(
        f"/kullanici-guncelle/{target_id}",
        data={"rol": "admin", "tam_ad": "Target User", "k_adi": "target@sarx.com"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    with app.app_context():
        approval = ApprovalRequest.query.filter_by(target_id=target_id, approval_type="role_change").first()
        assert approval is not None
        assert approval.status == "pending"
        assert db.session.get(Kullanici, target_id).rol == "personel"
        approval_id = approval.id

    _login(client, owner_id)
    response = client.post(f"/admin/approvals/{approval_id}", data={"action": "approve"}, follow_redirects=True)
    assert response.status_code == 200
    with app.app_context():
        approved = db.session.get(ApprovalRequest, approval_id)
        assert approved.status == "approved"
        assert db.session.get(Kullanici, target_id).rol == "admin"
        assert IslemLog.query.filter_by(event_key="role.assignment.change", target_id=target_id).count() >= 1


def test_unauthorized_user_cannot_access_approval_center(client, app):
    with app.app_context():
        user = KullaniciFactory(rol="personel", is_deleted=False)
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    response = client.get("/admin/approvals")
    assert response.status_code == 403
