from extensions import db
from models import Kutu
from tests.factories import EquipmentTemplateFactory, HavalimaniFactory, InventoryAssetFactory, KutuFactory, KullaniciFactory, MalzemeFactory


def _login(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_box_create_generates_airport_based_code_and_brand(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        manager = KullaniciFactory(rol="yetkili", havalimani=airport, is_deleted=False)
        KutuFactory(kodu="ERZ-SAR-01", havalimani=airport, marka="Marka A")
        KutuFactory(kodu="ERZ-SAR-02", havalimani=airport, marka="Marka B")
        db.session.add_all([airport, manager])
        db.session.commit()
        manager_id = manager.id
        airport_id = airport.id

    _login(client, manager_id)
    response = client.post(
        "/kutular/yeni",
        data={"havalimani_id": str(airport_id), "konum": "Ana Depo", "marka": "RescuePro"},
        follow_redirects=True,
    )
    assert response.status_code == 200

    with app.app_context():
        created = Kutu.query.filter_by(havalimani_id=airport_id, kodu="ERZ-SAR-03").first()
        assert created is not None
        assert created.marka == "RescuePro"
        assert created.konum == "Ana Depo"


def test_box_brand_can_be_updated_from_detail(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Samsun Havalimanı", kodu="SZF")
        manager = KullaniciFactory(rol="yetkili", havalimani=airport, is_deleted=False)
        box = KutuFactory(kodu="SZF-SAR-01", havalimani=airport, marka="Eski Marka", konum="Raf 1")
        db.session.add_all([airport, manager, box])
        db.session.commit()
        manager_id = manager.id

    _login(client, manager_id)
    response = client.post(
        "/kutu/SZF-SAR-01/guncelle",
        data={"konum": "Raf 2", "marka": "Yeni Marka"},
        follow_redirects=True,
    )
    assert response.status_code == 200

    with app.app_context():
        updated = Kutu.query.filter_by(kodu="SZF-SAR-01").first()
        assert updated is not None
        assert updated.konum == "Raf 2"
        assert updated.marka == "Yeni Marka"


def test_personnel_only_sees_own_airport_boxes(client, app):
    with app.app_context():
        airport_one = HavalimaniFactory(ad="Ankara", kodu="ESB")
        airport_two = HavalimaniFactory(ad="İstanbul", kodu="SAW")
        user = KullaniciFactory(rol="personel", havalimani=airport_one, is_deleted=False)
        KutuFactory(kodu="ESB-SAR-01", havalimani=airport_one)
        KutuFactory(kodu="SAW-SAR-01", havalimani=airport_two)
        db.session.add_all([airport_one, airport_two, user])
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    response = client.get("/kutular")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "ESB-SAR-01" in html
    assert "SAW-SAR-01" not in html


def test_airport_manager_cannot_archive_other_airport_box(client, app):
    with app.app_context():
        airport_one = HavalimaniFactory(ad="İzmir", kodu="ADB")
        airport_two = HavalimaniFactory(ad="Dalaman", kodu="DLM")
        manager = KullaniciFactory(rol="yetkili", havalimani=airport_one, is_deleted=False)
        foreign_box = KutuFactory(kodu="DLM-SAR-01", havalimani=airport_two)
        db.session.add_all([airport_one, airport_two, manager, foreign_box])
        db.session.commit()
        manager_id = manager.id

    _login(client, manager_id)
    response = client.post("/kutu/DLM-SAR-01/arsivle", data={})
    assert response.status_code == 404


def test_owner_can_create_box_for_any_airport(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Trabzon", kodu="TZX")
        owner = KullaniciFactory(rol="sahip", is_deleted=False)
        db.session.add_all([airport, owner])
        db.session.commit()
        owner_id = owner.id
        airport_id = airport.id

    _login(client, owner_id)
    response = client.post(
        "/kutular/yeni",
        data={"havalimani_id": str(airport_id), "konum": "Araç Depo", "marka": "Omni"},
        follow_redirects=True,
    )
    assert response.status_code == 200

    with app.app_context():
        created = Kutu.query.filter_by(havalimani_id=airport_id).first()
        assert created is not None
        assert created.kodu.startswith("TZX-SAR-")


def test_airport_manager_can_archive_own_airport_box(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Muş", kodu="MSR")
        manager = KullaniciFactory(rol="yetkili", havalimani=airport, is_deleted=False)
        box = KutuFactory(kodu="MSR-SAR-01", havalimani=airport)
        db.session.add_all([airport, manager, box])
        db.session.commit()
        manager_id = manager.id

    _login(client, manager_id)
    response = client.post("/kutu/MSR-SAR-01/arsivle", data={}, follow_redirects=True)
    assert response.status_code == 200

    with app.app_context():
        archived = Kutu.query.filter_by(kodu="MSR-SAR-01").first()
        assert archived is not None and archived.is_deleted is True


def test_inventory_detail_button_targets_asset_detail_not_box(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Kars", kodu="KSY")
        manager = KullaniciFactory(rol="yetkili", havalimani=airport, is_deleted=False)
        box = KutuFactory(kodu="KSY-SAR-01", havalimani=airport)
        material = MalzemeFactory(ad="Termal Kamera", kutu=box, havalimani=airport, is_deleted=False)
        template = EquipmentTemplateFactory(name="Termal Kamera", category="Optik", brand="FLIR", model_code="K65")
        asset = InventoryAssetFactory(equipment_template=template, airport=airport, status="aktif")
        db.session.add_all([airport, manager, box, material, template, asset])
        db.session.flush()
        asset.legacy_material_id = material.id
        db.session.commit()
        manager_id = manager.id
        asset_id = asset.id
        box_code = box.kodu

    _login(client, manager_id)
    response = client.get("/envanter")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert f'/asset/{asset_id}/detay' in html
    assert f'/kutu/{box_code}" class="row-btn">📦 Bağlı Kutuyu Gör' in html
    assert f'/kutu/{box_code}" class="row-btn">🔍 Envanter Detayı' not in html


def test_asset_detail_page_renders_core_inventory_fields(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Erzincan", kodu="ERC")
        manager = KullaniciFactory(rol="yetkili", havalimani=airport, is_deleted=False)
        box = KutuFactory(kodu="ERC-SAR-01", havalimani=airport)
        material = MalzemeFactory(ad="Hidrolik Ayırıcı", kutu=box, havalimani=airport, is_deleted=False)
        template = EquipmentTemplateFactory(name="Hidrolik Ayırıcı", category="Kurtarma", brand="Holmatro", model_code="SP 5240")
        asset = InventoryAssetFactory(equipment_template=template, airport=airport, serial_no="SN-445", status="aktif")
        db.session.add_all([airport, manager, box, material, template, asset])
        db.session.flush()
        asset.legacy_material_id = material.id
        db.session.commit()
        manager_id = manager.id
        asset_id = asset.id

    _login(client, manager_id)
    response = client.get(f"/asset/{asset_id}/detay")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Envanter Bilgileri" in html
    assert "Kategori / Tip" in html
    assert "Marka / Model" in html
    assert "Seri No" in html
    assert "Bağlı Kutuyu Gör" in html
    assert "Bakım Özeti" in html


def test_box_archive_and_delete_lifecycle(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Erzurum", kodu="ERZ")
        owner = KullaniciFactory(rol="sahip", havalimani=airport, is_deleted=False)
        archive_box = KutuFactory(kodu="ERZ-SAR-20", havalimani=airport)
        delete_box = KutuFactory(kodu="ERZ-SAR-21", havalimani=airport)
        db.session.add_all([airport, owner, archive_box, delete_box])
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    archive_response = client.post("/kutu/ERZ-SAR-20/arsivle", data={}, follow_redirects=True)
    delete_response = client.post("/kutu/ERZ-SAR-21/sil", data={}, follow_redirects=True)

    assert archive_response.status_code == 200
    assert delete_response.status_code == 200

    with app.app_context():
        archived = Kutu.query.filter_by(kodu="ERZ-SAR-20").first()
        deleted = Kutu.query.filter_by(kodu="ERZ-SAR-21").first()
        assert archived is not None and archived.is_deleted is True
        assert deleted is None
