from decorators import (
    CANONICAL_ROLE_ADMIN,
    CANONICAL_ROLE_SYSTEM,
    CANONICAL_ROLE_TEAM_LEAD,
    CANONICAL_ROLE_TEAM_MEMBER,
    get_effective_role,
)
from extensions import db
from models import Kullanici, Role
from tests.factories import HavalimaniFactory, KullaniciFactory


def _login(client, user_id):
    with client.session_transaction() as session:
        session.clear()
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_legacy_roles_map_to_canonical_effective_roles(app):
    with app.app_context():
        assert get_effective_role(KullaniciFactory.build(rol="sahip")) == CANONICAL_ROLE_SYSTEM
        assert get_effective_role(KullaniciFactory.build(rol="yetkili")) == CANONICAL_ROLE_TEAM_LEAD
        assert get_effective_role(KullaniciFactory.build(rol="bakim_sorumlusu")) == CANONICAL_ROLE_TEAM_MEMBER
        assert get_effective_role(KullaniciFactory.build(rol="readonly")) == CANONICAL_ROLE_ADMIN


def test_user_management_role_select_shows_only_canonical_roles(client, app):
    with app.app_context():
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-canonical@sarx.com")
        db.session.add(owner)
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    response = client.get("/kullanicilar")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Sistem Sorumlusu" in html
    assert "Ekip Sorumlusu" in html
    assert "Ekip Üyesi" in html
    assert "Admin" in html
    assert "Bakım Sorumlusu" not in html
    assert "Depo Sorumlusu" not in html
    assert "Genel Müdürlük" not in html


def test_admin_can_view_all_users_but_cannot_access_role_management(client, app):
    with app.app_context():
        erzurum = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        trabzon = HavalimaniFactory(ad="Trabzon Havalimanı", kodu="TZX")
        admin_user = KullaniciFactory(rol="admin", is_deleted=False, kullanici_adi="admin-global@sarx.com")
        first_user = KullaniciFactory(rol="ekip_uyesi", is_deleted=False, tam_ad="Erzurum Uye", havalimani=erzurum)
        second_user = KullaniciFactory(rol="ekip_uyesi", is_deleted=False, tam_ad="Trabzon Uye", havalimani=trabzon)
        db.session.add_all([erzurum, trabzon, admin_user, first_user, second_user])
        db.session.commit()
        admin_id = admin_user.id

    _login(client, admin_id)
    users_response = client.get("/kullanicilar")
    roles_response = client.get("/admin/roles")

    assert users_response.status_code == 200
    assert "Erzurum Uye" in users_response.data.decode("utf-8")
    assert "Trabzon Uye" in users_response.data.decode("utf-8")
    assert roles_response.status_code == 403


def test_team_lead_can_only_create_team_member_in_own_airport(client, app):
    with app.app_context():
        own_airport = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        other_airport = HavalimaniFactory(ad="Trabzon Havalimanı", kodu="TZX")
        lead = KullaniciFactory(
            rol="ekip_sorumlusu",
            is_deleted=False,
            kullanici_adi="lead@sarx.com",
            havalimani=own_airport,
        )
        db.session.add_all([own_airport, other_airport, lead])
        db.session.commit()
        lead_id = lead.id
        own_airport_id = own_airport.id
        other_airport_id = other_airport.id

    _login(client, lead_id)
    response = client.post(
        "/kullanici-ekle",
        data={
            "tam_ad": "Saha Uyesi",
            "k_adi": "saha-uyesi@sarx.com",
            "sifre": "GucluTest@123",
            "rol": "ekip_sorumlusu",
            "h_id": other_airport_id,
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    with app.app_context():
        created = Kullanici.query.filter_by(kullanici_adi="saha-uyesi@sarx.com").first()
        assert created is not None
        assert created.rol == CANONICAL_ROLE_TEAM_MEMBER
        assert created.havalimani_id == own_airport_id


def test_owner_can_create_and_deactivate_custom_role(client, app):
    with app.app_context():
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-roleman@sarx.com")
        db.session.add(owner)
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    create_response = client.post(
        "/admin/roles/create",
        data={
            "label": "Denetim Koordinatörü",
            "key": "denetim_koordinatoru",
            "scope": "global",
            "description": "Denetim amaçlı özel rol",
            "base_role_key": "admin",
        },
        follow_redirects=True,
    )
    assert create_response.status_code == 200
    assert "Özel rol oluşturuldu." in create_response.data.decode("utf-8")

    with app.app_context():
        role = Role.query.filter_by(key="denetim_koordinatoru").first()
        assert role is not None
        assert role.is_system is False
        assert role.is_active is True

    delete_response = client.post(
        "/admin/roles/denetim_koordinatoru/delete",
        data={},
        follow_redirects=True,
    )
    assert delete_response.status_code == 200
    assert "Özel rol pasife alındı." in delete_response.data.decode("utf-8")

    with app.app_context():
        role = Role.query.filter_by(key="denetim_koordinatoru").first()
        assert role is not None
        assert role.is_active is False


def test_owner_cannot_delete_core_role(client, app):
    with app.app_context():
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-core-role@sarx.com")
        db.session.add(owner)
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    response = client.post("/admin/roles/admin/delete", data={}, follow_redirects=True)
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Çekirdek roller silinemez." in html
