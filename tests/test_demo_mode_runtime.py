from decorators import ROLE_PERSONNEL
from demo_data import DEMO_SEED_TAG, get_platform_demo_status, seed_demo_data
from extensions import db
from models import DemoSeedRecord, Havalimani, Kutu, Malzeme, Kullanici
from tests.factories import KullaniciFactory


def _login(client, user_id):
    with client.session_transaction() as session:
        session.clear()
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_demo_mode_management_is_restricted_to_owner_or_admin(client, app):
    app.config["DEMO_TOOLS_ENABLED"] = True
    owner = KullaniciFactory(rol="sahip")
    admin = KullaniciFactory(rol="admin")
    regular_user = KullaniciFactory(rol=ROLE_PERSONNEL)
    db.session.add_all([owner, admin, regular_user])
    db.session.commit()

    _login(client, regular_user.id)
    forbidden = client.post("/demo-veri/olustur", data={"confirm_demo_seed": "DEMO"})
    assert forbidden.status_code == 403

    _login(client, admin.id)
    allowed = client.post(
        "/demo-veri/olustur",
        data={"confirm_demo_seed": "DEMO", "demo_reset": "1"},
        follow_redirects=False,
    )
    assert allowed.status_code == 302

    with app.app_context():
        assert get_platform_demo_status()["active"] is True


def test_demo_mode_active_shows_demo_inventory_to_non_admin_users(client, app):
    app.config["DEMO_TOOLS_ENABLED"] = True

    with app.app_context():
        seed_demo_data(reset=True)
        airport = Havalimani.query.filter_by(kodu="ERZ", is_deleted=False).first()
        assert airport is not None

        real_box = Kutu(kodu=f"{airport.kodu}-REAL-KUTU", konum="Gerçek Depo", havalimani_id=airport.id)
        db.session.add(real_box)
        db.session.flush()

        real_material = Malzeme(
            ad="GERCEK KAYIT MALZEMESI",
            seri_no="REAL-MAT-0001",
            teknik_ozellikler="Gerçek kayıt",
            stok_miktari=1,
            durum="Aktif",
            kritik_mi=False,
            kutu_id=real_box.id,
            havalimani_id=airport.id,
        )
        db.session.add(real_material)
        db.session.commit()

        viewer = Kullanici.query.filter_by(rol=ROLE_PERSONNEL, is_deleted=False).first()
        assert viewer is not None

        demo_row = DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG, model_name="Malzeme").first()
        assert demo_row is not None
        demo_material = db.session.get(Malzeme, demo_row.record_id)
        assert demo_material is not None
        demo_material_name = demo_material.ad

    _login(client, viewer.id)
    response = client.get("/envanter")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "GERCEK KAYIT MALZEMESI" not in html
    assert demo_material_name in html
