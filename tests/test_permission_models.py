from decorators import get_effective_permissions, sync_authorization_registry, update_permission_matrix
from extensions import db
from models import Permission, Role, RolePermission
from tests.factories import KullaniciFactory


def test_sync_authorization_registry_is_idempotent(app):
    with app.app_context():
        first_sync = sync_authorization_registry()
        db.session.commit()
        second_sync = sync_authorization_registry()

        assert first_sync is True
        assert second_sync is False


def test_role_permission_db_assignment_works(app):
    with app.app_context():
        sync_authorization_registry()
        db.session.commit()
        role = Role.query.filter_by(key="editor").first()
        permission = Permission.query.filter_by(key="users.manage").first()
        db.session.add(RolePermission(role_id=role.id, permission_id=permission.id, is_allowed=True))
        user = KullaniciFactory(rol="editor", is_deleted=False)
        db.session.add(user)
        db.session.commit()

        permissions = get_effective_permissions(user)
        assert "users.manage" in permissions


def test_metadata_fallback_still_works(app):
    with app.app_context():
        update_permission_matrix("editor", allow_permissions=["logs.view"], deny_permissions=[])
        user = KullaniciFactory(rol="editor", is_deleted=False)
        db.session.add(user)
        db.session.flush()
        user_id = user.id
        db.session.commit()

        permissions = get_effective_permissions(db.session.get(type(user), user_id))
        assert "logs.view" in permissions
