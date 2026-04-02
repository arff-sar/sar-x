from decorators import (
    CANONICAL_ROLE_ADMIN,
    CANONICAL_ROLE_SYSTEM,
    CANONICAL_ROLE_TEAM_LEAD,
    CANONICAL_ROLE_TEAM_MEMBER,
    actor_can_view_target_user,
    can_assign_role,
    get_effective_role,
    get_effective_permissions,
    update_permission_matrix,
)
from extensions import db
from tests.factories import HavalimaniFactory, KullaniciFactory


REMOVED_ROLES = [
    "readonly",
    "personel",
    "admin",
    "bakim_sorumlusu",
    "havalimani_yoneticisi",
    "yetkili",
    "sahip",
]

REMOVED_ROLE_ALIAS_MAP = {
    "readonly": CANONICAL_ROLE_ADMIN,
    "personel": CANONICAL_ROLE_TEAM_MEMBER,
    "admin": CANONICAL_ROLE_ADMIN,
    "bakim_sorumlusu": CANONICAL_ROLE_TEAM_MEMBER,
    "havalimani_yoneticisi": CANONICAL_ROLE_TEAM_LEAD,
    "yetkili": CANONICAL_ROLE_TEAM_LEAD,
    "sahip": CANONICAL_ROLE_SYSTEM,
}


def test_removed_roles_map_to_canonical_effective_roles(app):
    with app.app_context():
        for role_key, canonical_role in REMOVED_ROLE_ALIAS_MAP.items():
            user = KullaniciFactory.build(rol=role_key)
            assert get_effective_role(user) == canonical_role


def test_legacy_maintenance_role_keeps_restricted_permission_profile(app):
    with app.app_context():
        user = KullaniciFactory.build(rol="bakim_sorumlusu")
        assert get_effective_role(user) == CANONICAL_ROLE_TEAM_MEMBER
        assert get_effective_permissions(user) == set()


def test_removed_role_aliases_follow_canonical_permission_matrix_overrides(app):
    with app.app_context():
        custom_permission = "custom.removed_role_alias_permission"
        update_permission_matrix("admin", allow_permissions=[custom_permission], deny_permissions=[])
        user = KullaniciFactory.build(rol="readonly")
        permissions = get_effective_permissions(user)
        assert custom_permission in permissions


def test_system_role_can_assign_removed_role_aliases(app):
    with app.app_context():
        actor = KullaniciFactory.build(rol=CANONICAL_ROLE_SYSTEM)
        assert can_assign_role(actor, "ekip_uyesi") is True
        assert can_assign_role(actor, "ekip_sorumlusu") is True
        for role_key in REMOVED_ROLES:
            assert can_assign_role(actor, role_key) is True


def test_team_roles_are_airport_scoped_for_user_visibility(app):
    with app.app_context():
        airport_one = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        airport_two = HavalimaniFactory(ad="Trabzon Havalimanı", kodu="TZX")
        lead = KullaniciFactory(rol="ekip_sorumlusu", havalimani=airport_one, is_deleted=False)
        member_actor = KullaniciFactory(rol="ekip_uyesi", havalimani=airport_one, is_deleted=False)
        member_same_airport = KullaniciFactory(rol="ekip_uyesi", havalimani=airport_one, is_deleted=False)
        member_other_airport = KullaniciFactory(rol="ekip_uyesi", havalimani=airport_two, is_deleted=False)
        db.session.add_all([airport_one, airport_two, lead, member_actor, member_same_airport, member_other_airport])
        db.session.commit()

        assert actor_can_view_target_user(lead, member_same_airport) is True
        assert actor_can_view_target_user(lead, member_other_airport) is False
        assert actor_can_view_target_user(member_actor, member_same_airport) is False
