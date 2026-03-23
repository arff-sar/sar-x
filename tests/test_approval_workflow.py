import json

from flask_login import login_user

from decorators import sync_authorization_registry
from extensions import db
from models import ApprovalRequest, IslemLog, Kullanici
from routes.admin.approvals import _apply_approval
from tests.factories import KullaniciFactory


def _login(client, user_id):
    with client.session_transaction() as session:
        session.clear()
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_role_change_can_become_pending_and_applied_after_approval(client, app):
    with app.app_context():
        sync_authorization_registry()
        owner = KullaniciFactory(rol="sistem_sorumlusu", is_deleted=False, kullanici_adi="owner@sarx.com")
        admin = KullaniciFactory(rol="admin", is_deleted=False, kullanici_adi="admin@sarx.com")
        target = KullaniciFactory(rol="ekip_uyesi", is_deleted=False, kullanici_adi="target@sarx.com")
        db.session.add_all([owner, admin, target])
        db.session.commit()
        owner_id, admin_id, target_id = owner.id, admin.id, target.id

    _login(client, admin_id)
    response = client.post(
        f"/kullanici-guncelle/{target_id}",
        data={"rol": "admin", "tam_ad": "Target User", "k_adi": "target@sarx.com"},
        follow_redirects=True,
    )
    assert response.status_code == 403
    with app.app_context():
        approval = ApprovalRequest.query.filter_by(target_id=target_id, approval_type="role_change").first()
        assert approval is None
        assert db.session.get(Kullanici, target_id).rol == "ekip_uyesi"

        approval = ApprovalRequest(
            approval_type="role_change",
            target_model="Kullanici",
            target_id=target_id,
            requested_by_id=admin_id,
            request_payload=json.dumps(
                {
                    "user_id": target_id,
                    "tam_ad": "Target User",
                    "k_adi": "target@sarx.com",
                    "rol": "admin",
                    "h_id": None,
                    "allow_permissions": [],
                    "deny_permissions": [],
                },
                ensure_ascii=False,
            ),
        )
        db.session.add(approval)
        db.session.commit()
        approval_id = approval.id

    with app.app_context():
        approval = db.session.get(ApprovalRequest, approval_id)
        with app.test_request_context():
            login_user(db.session.get(Kullanici, owner_id))
            assert _apply_approval(approval) is True
        approval.status = "approved"
        approval.approved_by_id = owner_id
        db.session.commit()
        db.session.expire_all()
        approved = db.session.get(ApprovalRequest, approval_id)
        assert approved.status == "approved"
        assert IslemLog.query.filter_by(event_key="role.assignment.change", target_id=target_id).count() >= 1


def test_unauthorized_user_cannot_access_approval_center(client, app):
    with app.app_context():
        user = KullaniciFactory(rol="ekip_uyesi", is_deleted=False)
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    response = client.get("/admin/approvals")
    assert response.status_code == 403
