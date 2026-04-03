from extensions import db
from models import Kutu, Malzeme
from tests.factories import EquipmentTemplateFactory, HavalimaniFactory, InventoryAssetFactory, KutuFactory, KullaniciFactory, MalzemeFactory


def _login(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_box_create_generates_airport_based_code_and_brand(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        manager = KullaniciFactory(rol="yetkili", havalimani=airport, is_deleted=False)
        KutuFactory(kodu="ERZ-BOX-01", havalimani=airport, marka="Marka A")
        KutuFactory(kodu="ERZ-BOX-02", havalimani=airport, marka="Marka B")
        db.session.add_all([airport, manager])
        db.session.commit()
        manager_id = manager.id
        airport_id = airport.id

    _login(client, manager_id)
    response = client.post(
        "/kutular/yeni",
        data={"havalimani_id": str(airport_id), "marka": "RescuePro"},
        follow_redirects=True,
    )
    assert response.status_code == 200

    with app.app_context():
        created = Kutu.query.filter_by(havalimani_id=airport_id, kodu="ERZ-BOX-03").first()
        assert created is not None
        assert created.marka == "RescuePro"


def test_box_brand_can_be_updated_from_detail(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Samsun Havalimanı", kodu="SZF")
        manager = KullaniciFactory(rol="yetkili", havalimani=airport, is_deleted=False)
        box = KutuFactory(kodu="SZF-SAR-01", havalimani=airport, marka="Eski Marka")
        db.session.add_all([airport, manager, box])
        db.session.commit()
        manager_id = manager.id

    _login(client, manager_id)
    response = client.post(
        "/kutu/SZF-SAR-01/guncelle",
        data={"marka": "Yeni Marka"},
        follow_redirects=True,
    )
    assert response.status_code == 200

    with app.app_context():
        updated = Kutu.query.filter_by(kodu="SZF-SAR-01").first()
        assert updated is not None
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
        data={"havalimani_id": str(airport_id), "marka": "Omni"},
        follow_redirects=True,
    )
    assert response.status_code == 200

    with app.app_context():
        created = Kutu.query.filter_by(havalimani_id=airport_id).first()
        assert created is not None
        assert created.kodu.startswith("TZX-BOX-")


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


def test_inventory_accordion_actions_are_simplified(client, app):
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
        box_code = box.kodu

    _login(client, manager_id)
    response = client.get("/envanter")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert f"/kutu/{box_code}" in html
    assert "🔍 Envanter Detayı" not in html
    assert "📱 Hızlı" not in html
    assert "Hızlı Zimmet" in html


def test_box_brand_filter_matches_turkish_character_variants(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="İzmir", kodu="ADB")
        owner = KullaniciFactory(rol="sahip", is_deleted=False)
        wanted = KutuFactory(kodu="ADB-SAR-01", havalimani=airport, marka="Öztürk")
        other = KutuFactory(kodu="ADB-SAR-02", havalimani=airport, marka="Başka Marka")
        db.session.add_all([airport, owner, wanted, other])
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    response = client.get("/kutular?marka=ozturk")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "ADB-SAR-01" in html
    assert "ADB-SAR-02" not in html


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
    assert "Bakım Durumu" in html
    assert 'data-testid="asset-summary-shell"' in html
    assert 'data-testid="asset-info-groups"' in html
    assert "Varlık Kimliği" in html
    assert "Operasyon ve Doküman" in html
    assert "Demirbaş No" in html
    assert "Garanti" in html
    assert "Kullanım Kılavuzu" in html


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
    delete_archived_response = client.post("/kutu/ERZ-SAR-20/sil", data={}, follow_redirects=True)

    assert archive_response.status_code == 200
    assert delete_response.status_code == 200
    assert delete_archived_response.status_code == 200

    with app.app_context():
        archived = Kutu.query.filter_by(kodu="ERZ-SAR-20").first()
        deleted = Kutu.query.filter_by(kodu="ERZ-SAR-21").first()
        assert archived is None
        assert deleted is None


def test_box_management_filter_layout_is_aligned_and_location_removed(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        owner = KullaniciFactory(rol="sahip", havalimani=airport, is_deleted=False)
        box = KutuFactory(kodu="ERZ-SAR-01", havalimani=airport, marka="Pelican")
        db.session.add_all([airport, owner, box])
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    response = client.get("/kutular")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert html.count("<label>Havalimanı</label>") == 1
    assert "box-toolbar-row" in html
    assert "box-filter-grid" in html
    assert "box-filter-actions" in html
    assert "box-create-form" in html
    assert "Filtrele" in html and "Temizle" in html
    assert "Yeni Kutu Oluştur" in html
    assert '>İçerik</th>' in html
    assert '<th>QR</th>' not in html
    assert 'title="Erzurum Havalimanı"' in html
    assert ">Konum<" not in html


def test_box_detail_uses_accordion_edit_pattern(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Van", kodu="VAN")
        manager = KullaniciFactory(rol="yetkili", havalimani=airport, is_deleted=False)
        box = KutuFactory(kodu="VAN-SAR-01", havalimani=airport)
        material = MalzemeFactory(ad="Telsiz", seri_no="SN-500", kutu=box, havalimani=airport, is_deleted=False)
        template = EquipmentTemplateFactory(name="Telsiz", brand="Motorola", model_code="DP4400")
        asset = InventoryAssetFactory(equipment_template=template, airport=airport, status="aktif")
        db.session.add_all([airport, manager, box, material, template, asset])
        db.session.flush()
        asset.legacy_material_id = material.id
        db.session.commit()
        manager_id = manager.id

    _login(client, manager_id)
    response = client.get("/kutu/VAN-SAR-01")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert 'data-box-accordion' in html


def test_archive_page_scopes_rows_to_team_lead_airport(client, app):
    with app.app_context():
        airport_one = HavalimaniFactory(ad="Erzurum", kodu="ERZ")
        airport_two = HavalimaniFactory(ad="Trabzon", kodu="TZX")
        lead = KullaniciFactory(rol="yetkili", havalimani=airport_one, is_deleted=False)
        own_box = KutuFactory(kodu="ERZ-SAR-90", havalimani=airport_one)
        own_material = MalzemeFactory(ad="ERZ Arşiv Kaydı", kutu=own_box, havalimani=airport_one, is_deleted=True)
        own_material.deleted_at = own_material.deleted_at or own_material.created_at
        own_user = KullaniciFactory(
            rol="ekip_uyesi",
            havalimani=airport_one,
            is_deleted=True,
            tam_ad="ERZ Arşiv Personeli",
            kullanici_adi="erz-archive@sarx.com",
        )
        own_user.deleted_at = own_user.deleted_at or own_user.created_at
        remote_box = KutuFactory(kodu="TZX-SAR-90", havalimani=airport_two)
        remote_material = MalzemeFactory(ad="TZX Arşiv Kaydı", kutu=remote_box, havalimani=airport_two, is_deleted=True)
        remote_material.deleted_at = remote_material.deleted_at or remote_material.created_at
        remote_user = KullaniciFactory(
            rol="ekip_uyesi",
            havalimani=airport_two,
            is_deleted=True,
            tam_ad="TZX Arşiv Personeli",
            kullanici_adi="tzx-archive@sarx.com",
        )
        remote_user.deleted_at = remote_user.deleted_at or remote_user.created_at
        db.session.add_all([
            airport_one,
            airport_two,
            lead,
            own_box,
            own_material,
            own_user,
            remote_box,
            remote_material,
            remote_user,
        ])
        db.session.commit()
        lead_id = lead.id

    _login(client, lead_id)
    response = client.get("/arsiv")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "ERZ Arşiv Kaydı" in html
    assert "ERZ Arşiv Personeli" in html
    assert "TZX Arşiv Kaydı" not in html
    assert "TZX Arşiv Personeli" not in html


def test_team_lead_cannot_restore_other_airport_archived_record(client, app):
    with app.app_context():
        airport_one = HavalimaniFactory(ad="Erzurum", kodu="ERZ")
        airport_two = HavalimaniFactory(ad="Trabzon", kodu="TZX")
        lead = KullaniciFactory(rol="yetkili", havalimani=airport_one, is_deleted=False)
        remote_box = KutuFactory(kodu="TZX-SAR-91", havalimani=airport_two)
        remote_material = MalzemeFactory(ad="TZX Korumalı Kayıt", kutu=remote_box, havalimani=airport_two, is_deleted=True)
        remote_material.deleted_at = remote_material.deleted_at or remote_material.created_at
        db.session.add_all([airport_one, airport_two, lead, remote_box, remote_material])
        db.session.commit()
        lead_id = lead.id
        remote_material_id = remote_material.id

    _login(client, lead_id)
    response = client.post(
        "/arsiv_islem",
        data={"model_tipi": "malzeme", "kayit_id": str(remote_material_id), "islem_tipi": "geri_yukle"},
        follow_redirects=False,
    )

    assert response.status_code == 403

    with app.app_context():
        protected = db.session.get(Malzeme, remote_material_id)
        assert protected is not None
        assert protected.is_deleted is True


def test_personnel_sees_box_detail_without_edit_controls(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Ankara", kodu="ESB")
        personel = KullaniciFactory(rol="personel", havalimani=airport, is_deleted=False)
        box = KutuFactory(kodu="ESB-SAR-01", havalimani=airport)
        material = MalzemeFactory(ad="Halat", kutu=box, havalimani=airport, is_deleted=False)
        template = EquipmentTemplateFactory(name="Halat")
        asset = InventoryAssetFactory(equipment_template=template, airport=airport, status="aktif")
        db.session.add_all([airport, personel, box, material, template, asset])
        db.session.flush()
        asset.legacy_material_id = material.id
        db.session.commit()
        user_id = personel.id

    _login(client, user_id)
    response = client.get("/kutu/ESB-SAR-01")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Düzenle" not in html
    assert "Kutudan Sil" not in html
