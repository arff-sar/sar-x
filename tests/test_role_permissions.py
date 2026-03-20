from decorators import get_effective_permissions, update_permission_matrix
from extensions import db
from tests.factories import KullaniciFactory


def _login(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_editor_role_permissions_are_scoped_to_homepage(app):
    with app.app_context():
        user = KullaniciFactory(rol="editor", is_deleted=False)
        db.session.add(user)
        db.session.commit()

        permissions = get_effective_permissions(user)
        assert "homepage.view" in permissions
        assert "homepage.edit" in permissions
        assert "users.manage" not in permissions
        assert "settings.manage" not in permissions


def test_permission_matrix_changes_are_applied(client, app):
    with app.app_context():
        update_permission_matrix("editor", allow_permissions=[], deny_permissions=["homepage.view"])
        user = KullaniciFactory(rol="editor", is_deleted=False)
        db.session.add(user)
        db.session.flush()
        user_id = user.id
        db.session.commit()

    _login(client, user_id)
    response = client.get("/admin/homepage")
    assert response.status_code == 403
