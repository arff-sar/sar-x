from decorators import ROLE_PERSONNEL
from demo_data import DEMO_SEED_TAG, get_platform_demo_status, platform_demo_is_active, seed_demo_data
from extensions import db
from models import DemoSeedRecord, EquipmentTemplate, Havalimani, InventoryAsset, Kutu, Malzeme, PPERecord, Kullanici
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

        real_box = Kutu(kodu=f"{airport.kodu}-REAL-KUTU", havalimani_id=airport.id)
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


def test_demo_mode_scopes_maintenance_and_ppe_modules(client, app):
    app.config["DEMO_TOOLS_ENABLED"] = True

    with app.app_context():
        seed_demo_data(reset=True)
        airport = Havalimani.query.filter_by(kodu="ERZ", is_deleted=False).first()
        assert airport is not None
        demo_ppe_row = DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG, model_name="PPERecord").first()
        assert demo_ppe_row is not None
        demo_ppe = db.session.get(PPERecord, demo_ppe_row.record_id)
        assert demo_ppe is not None
        viewer_id = demo_ppe.user_id

        real_template = EquipmentTemplate(
            name="GERCEK DEMO DISI EKIPMAN",
            category="Test",
            is_active=True,
        )
        db.session.add(real_template)
        db.session.flush()

        real_box = Kutu(kodu=f"{airport.kodu}-REAL-KUTU-2", havalimani_id=airport.id)
        db.session.add(real_box)
        db.session.flush()

        real_material = Malzeme(
            ad="GERCEK BAKIM MALZEMESI",
            seri_no="REAL-MAINT-0001",
            kutu_id=real_box.id,
            havalimani_id=airport.id,
            is_deleted=False,
        )
        db.session.add(real_material)
        db.session.flush()

        real_asset = InventoryAsset(
            equipment_template_id=real_template.id,
            havalimani_id=airport.id,
            legacy_material_id=real_material.id,
            serial_no="REAL-ASSET-MAINT-0001",
            qr_code="REAL-ASSET-MAINT-QR-0001",
            status="aktif",
        )
        db.session.add(real_asset)

        real_ppe = PPERecord(
            user_id=viewer_id,
            airport_id=airport.id,
            item_name="GERCEK KKD KAYDI",
            quantity=1,
            status="aktif",
            created_by_id=viewer_id,
        )
        db.session.add(real_ppe)
        db.session.commit()

        demo_asset_row = DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG, model_name="InventoryAsset").first()
        assert demo_asset_row is not None
        demo_asset = db.session.get(InventoryAsset, demo_asset_row.record_id)
        assert demo_asset is not None
        assert demo_ppe is not None
        demo_asset_serial = demo_asset.serial_no
        demo_ppe_name = demo_ppe.item_name

    _login(client, viewer_id)
    maintenance_response = client.get("/bakim")
    maintenance_html = maintenance_response.data.decode("utf-8")
    assert maintenance_response.status_code == 200
    assert "REAL-ASSET-MAINT-0001" not in maintenance_html
    assert demo_asset_serial in maintenance_html

    ppe_response = client.get("/kkd")
    ppe_html = ppe_response.data.decode("utf-8")
    assert ppe_response.status_code == 200
    assert "GERCEK KKD KAYDI" not in ppe_html
    assert demo_ppe_name in ppe_html


def test_platform_demo_scope_forced_off_in_production_runtime(app):
    app.config["DEMO_TOOLS_ENABLED"] = True
    with app.app_context():
        seed_demo_data(reset=True)
        assert get_platform_demo_status()["active"] is True
        assert platform_demo_is_active() is True

    app.config["ENV"] = "production"
    app.config["DEMO_TOOLS_ENABLED"] = False
    with app.app_context():
        assert platform_demo_is_active() is False
