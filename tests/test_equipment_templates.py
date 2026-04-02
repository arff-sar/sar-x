import json

from extensions import db
from models import EquipmentTemplate, InventoryAsset, InventoryCategory, MaintenanceFormField, MaintenanceFormTemplate
from tests.factories import HavalimaniFactory, KullaniciFactory


def _login(client, user):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


def test_owner_can_configure_equipment_template_from_existing_inventory(client, app):
    admin = KullaniciFactory(rol="sahip")
    airport = HavalimaniFactory(kodu="ESB")
    category = InventoryCategory(name="Elektronik", is_active=True, is_deleted=False, created_by_user_id=admin.id)
    template = EquipmentTemplate(
        name="Termal Kamera",
        category="Elektronik",
        brand="FLIR",
        model_code="K1",
        maintenance_period_days=60,
        is_active=True,
    )
    asset = InventoryAsset(
        equipment_template=template,
        airport=airport,
        serial_no="TK-001",
        qr_code="TK-QR-001",
        status="aktif",
    )
    db.session.add_all([admin, airport, category, template, asset])
    db.session.commit()
    _login(client, admin)

    response = client.post(
        "/bakim/ekipman-sablonlari",
        data={
            "selected_template_id": template.id,
            "category": "Elektronik",
            "name": "Termal Kamera",
            "brand": "FLIR",
            "model_code": "K1",
            "maintenance_period_days": 90,
            "instruction_title": "Termal Kamera Bakım Talimatı",
            "instruction_description": "Lens ve pil kontrolü yapılır.",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    refreshed = EquipmentTemplate.query.get(template.id)
    assert refreshed is not None
    assert refreshed.maintenance_period_days == 90
    assert refreshed.maintenance_instruction is not None
    assert refreshed.maintenance_instruction.title == "Termal Kamera Bakım Talimatı"
    assert refreshed.maintenance_instruction.description == "Lens ve pil kontrolü yapılır."


def test_equipment_template_form_renders_select_fields_and_hides_critical_label(client, app):
    admin = KullaniciFactory(rol="sahip")
    airport = HavalimaniFactory(kodu="ADB")
    category = InventoryCategory(name="Sensör", is_active=True, is_deleted=False, created_by_user_id=admin.id)
    template = EquipmentTemplate(name="Gaz Ölçüm Cihazı", category="Sensör", brand="MSA", model_code="ALTAIR", is_active=True)
    asset = InventoryAsset(
        equipment_template=template,
        airport=airport,
        serial_no="GO-001",
        qr_code="GO-QR-001",
        status="aktif",
    )
    db.session.add_all([admin, airport, category, template, asset])
    db.session.commit()
    _login(client, admin)

    response = client.get("/bakim/ekipman-sablonlari")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert 'name="selected_template_id"' in html
    assert 'id="instructionCategorySelect"' in html
    assert 'id="instructionNameSelect"' in html
    assert 'id="instructionBrandSelect"' in html
    assert 'id="instructionModelSelect"' in html
    assert 'data-maintenance-accordion="central-template"' in html
    assert 'data-maintenance-accordion="central-catalog"' in html
    assert 'data-maintenance-accordion="maintenance-form-create"' in html
    assert 'data-maintenance-accordion="maintenance-form-delete"' in html
    assert 'data-maintenance-accordion="central-template" open' not in html
    assert 'data-maintenance-accordion="central-catalog" open' not in html
    assert 'data-maintenance-accordion="maintenance-form-create" open' not in html
    assert 'data-maintenance-accordion="maintenance-form-delete" open' not in html
    assert "Kritik Seviyesi" not in html


def test_template_without_inventory_asset_cannot_be_configured_in_maintenance_panel(client, app):
    admin = KullaniciFactory(rol="sahip")
    category = InventoryCategory(name="Elektronik", is_active=True, is_deleted=False, created_by_user_id=admin.id)
    template = EquipmentTemplate(name="Depo Yedeği", category="Elektronik", brand="MSA", model_code="X2", is_active=True)
    db.session.add_all([admin, category, template])
    db.session.commit()
    _login(client, admin)

    response = client.post(
        "/bakim/ekipman-sablonlari",
        data={
            "selected_template_id": template.id,
            "category": "Elektronik",
            "name": "Depo Yedeği",
            "brand": "MSA",
            "model_code": "X2",
            "maintenance_period_days": 120,
        },
        follow_redirects=True,
    )
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "sistemde tanımlı ve envantere eklenmiş bir ekipman seçin" in html
    assert EquipmentTemplate.query.get(template.id).maintenance_instruction is None


def test_airport_manager_can_add_asset_from_central_template(client, app):
    airport = HavalimaniFactory(kodu="ESB")
    manager = KullaniciFactory(rol="yetkili", havalimani=airport)
    template = EquipmentTemplate(name="Gaz Ölçüm Cihazı", category="Sensör", maintenance_period_days=60, is_active=True)
    db.session.add_all([airport, manager, template])
    db.session.commit()
    _login(client, manager)

    response = client.post(
        f"/merkezi-sablondan-envantere-ekle/{template.id}",
        data={
            "kutu_kodu": "DEP-10",
            "seri_no": "ESB-0001",
            "stok": 1,
            "durum": "Aktif",
            "ad": "Gaz Ölçüm Cihazı",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    asset = InventoryAsset.query.filter_by(serial_no="ESB-0001").first()
    assert asset is not None
    assert asset.havalimani_id == airport.id
    assert asset.equipment_template_id == template.id
    assert (asset.asset_code or "").startswith("ARFF-SAR-")
    assert (asset.qr_code or "").startswith("http")


def test_same_template_can_be_used_by_two_airports_with_different_serial(client, app):
    h1 = HavalimaniFactory(kodu="ESB")
    h2 = HavalimaniFactory(kodu="SAW")
    owner = KullaniciFactory(rol="sahip")
    template = EquipmentTemplate(name="Basınç Regülatörü", category="Mekanik", maintenance_period_days=120, is_active=True)
    db.session.add_all([h1, h2, owner, template])
    db.session.commit()
    _login(client, owner)

    client.post(
        f"/merkezi-sablondan-envantere-ekle/{template.id}",
        data={
            "havalimani_id": h1.id,
            "kutu_kodu": "A-01",
            "seri_no": "ESB-SN-1",
            "ad": "Basınç Regülatörü",
        },
        follow_redirects=True,
    )
    client.post(
        f"/merkezi-sablondan-envantere-ekle/{template.id}",
        data={
            "havalimani_id": h2.id,
            "kutu_kodu": "B-01",
            "seri_no": "SAW-SN-1",
            "ad": "Basınç Regülatörü",
        },
        follow_redirects=True,
    )

    assets = InventoryAsset.query.filter_by(equipment_template_id=template.id).all()
    assert len(assets) == 2
    assert {asset.havalimani_id for asset in assets} == {h1.id, h2.id}
    assert {asset.serial_no for asset in assets} == {"ESB-SN-1", "SAW-SN-1"}


def test_non_owner_cannot_create_central_template_in_maintenance_panel(client, app):
    manager = KullaniciFactory(rol="yetkili")
    db.session.add(manager)
    db.session.commit()
    _login(client, manager)

    response = client.post(
        "/bakim/ekipman-sablonlari",
        data={"name": "Yetkisiz Şablon", "category": "Elektronik", "maintenance_period_days": 120},
    )
    assert response.status_code == 403


def test_cannot_create_maintenance_form_when_no_equipment_template_exists(client, app):
    admin = KullaniciFactory(rol="sahip")
    db.session.add(admin)
    db.session.commit()
    _login(client, admin)

    response = client.post(
        "/bakim/ekipman-sablonlari",
        data={
            "form_action": "create_maintenance_form",
            "form_equipment_template_id": "",
            "periyot_turu": "gunluk",
            "maintenance_steps_payload": json.dumps(["Kontrol adımı"]),
        },
        follow_redirects=True,
    )
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Önce merkezi ekipman şablonu oluşturulmalıdır." in html
    assert MaintenanceFormTemplate.query.count() == 0


def test_can_create_maintenance_form_with_equipment_period_and_steps(client, app):
    admin = KullaniciFactory(rol="sahip")
    template = EquipmentTemplate(
        name="Jeneratör",
        category="Elektrik",
        brand="CAT",
        model_code="X1",
        is_active=True,
    )
    db.session.add_all([admin, template])
    db.session.commit()
    _login(client, admin)

    response = client.post(
        "/bakim/ekipman-sablonlari",
        data={
            "form_action": "create_maintenance_form",
            "form_equipment_template_id": template.id,
            "periyot_turu": "aylik",
            "maintenance_steps_payload": json.dumps(
                [
                    "  Yağ seviyesini kontrol et  ",
                    "Filtreyi kontrol et",
                    "yağ   seviyesini kontrol et",
                ]
            ),
        },
        follow_redirects=True,
    )
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Bakım formu oluşturuldu." in html

    created = MaintenanceFormTemplate.query.filter_by(
        equipment_template_id=template.id,
        period_type="aylik",
        is_deleted=False,
    ).first()
    assert created is not None
    assert created.name.startswith("Jeneratör - Aylık Bakım Formu")
    assert len(created.fields) == 2
    assert [field.label for field in created.fields] == ["Yağ seviyesini kontrol et", "Filtreyi kontrol et"]
    assert [field.order_index for field in created.fields] == [1, 2]
    assert all(field.field_type == "yes_no" for field in created.fields)


def test_maintenance_form_requires_at_least_one_non_empty_step(client, app):
    admin = KullaniciFactory(rol="sahip")
    template = EquipmentTemplate(name="Kompresör", category="Mekanik", is_active=True)
    db.session.add_all([admin, template])
    db.session.commit()
    _login(client, admin)

    response = client.post(
        "/bakim/ekipman-sablonlari",
        data={
            "form_action": "create_maintenance_form",
            "form_equipment_template_id": template.id,
            "periyot_turu": "gunluk",
            "maintenance_steps_payload": json.dumps(["", "   "]),
        },
        follow_redirects=True,
    )
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "En az 1 bakım adımı eklemelisiniz." in html
    assert MaintenanceFormTemplate.query.filter_by(
        equipment_template_id=template.id,
        period_type="gunluk",
        is_deleted=False,
    ).count() == 0


def test_duplicate_equipment_and_period_is_blocked_for_maintenance_form(client, app):
    admin = KullaniciFactory(rol="sahip")
    template = EquipmentTemplate(name="Kompresör", category="Mekanik", is_active=True)
    existing_form = MaintenanceFormTemplate(
        name="Kompresör - Günlük Bakım Formu",
        equipment_template=template,
        period_type="gunluk",
        is_active=True,
    )
    db.session.add_all([admin, template, existing_form])
    db.session.commit()
    _login(client, admin)

    response = client.post(
        "/bakim/ekipman-sablonlari",
        data={
            "form_action": "create_maintenance_form",
            "form_equipment_template_id": template.id,
            "periyot_turu": "gunluk",
            "maintenance_steps_payload": json.dumps(["Basınç göstergesini kontrol et"]),
        },
        follow_redirects=True,
    )
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Bu ekipman ve periyot için bakım formu zaten kayıtlı." in html
    assert MaintenanceFormTemplate.query.filter_by(
        equipment_template_id=template.id,
        period_type="gunluk",
        is_deleted=False,
    ).count() == 1


def test_team_lead_can_create_and_delete_maintenance_form(client, app):
    leader = KullaniciFactory(rol="yetkili")
    template = EquipmentTemplate(name="Kule Fanı", category="Elektrik", is_active=True)
    db.session.add_all([leader, template])
    db.session.commit()
    _login(client, leader)

    create_response = client.post(
        "/bakim/ekipman-sablonlari",
        data={
            "form_action": "create_maintenance_form",
            "form_equipment_template_id": template.id,
            "periyot_turu": "yillik",
            "maintenance_steps_payload": json.dumps(["Kanatları kontrol et", "Elektrik bağlantısını kontrol et"]),
        },
        follow_redirects=True,
    )
    create_html = create_response.data.decode("utf-8")

    assert create_response.status_code == 200
    assert "Bakım formu oluşturuldu." in create_html

    created = MaintenanceFormTemplate.query.filter_by(
        equipment_template_id=template.id,
        period_type="yillik",
        is_deleted=False,
    ).first()
    assert created is not None
    assert len(created.fields) == 2

    delete_response = client.post(
        "/bakim/ekipman-sablonlari",
        data={
            "form_action": "delete_maintenance_form",
            "form_template_id": created.id,
        },
        follow_redirects=True,
    )
    delete_html = delete_response.data.decode("utf-8")

    assert delete_response.status_code == 200
    assert "Bakım formu silindi." in delete_html

    deleted_form = MaintenanceFormTemplate.query.get(created.id)
    assert deleted_form is not None
    assert deleted_form.is_deleted is True
    assert deleted_form.is_active is False
    assert MaintenanceFormField.query.filter_by(form_template_id=created.id, is_deleted=False).count() == 0


def test_team_member_cannot_create_or_delete_maintenance_form(client, app):
    maintenance_member = KullaniciFactory(rol="bakim_sorumlusu")
    template = EquipmentTemplate(name="Jeneratör", category="Elektrik", is_active=True)
    existing_form = MaintenanceFormTemplate(
        name="Jeneratör - Günlük Bakım Formu",
        equipment_template=template,
        period_type="gunluk",
        is_active=True,
    )
    db.session.add_all([maintenance_member, template, existing_form])
    db.session.commit()
    _login(client, maintenance_member)

    create_response = client.post(
        "/bakim/ekipman-sablonlari",
        data={
            "form_action": "create_maintenance_form",
            "form_equipment_template_id": template.id,
            "periyot_turu": "aylik",
            "maintenance_steps_payload": json.dumps(["Yakıt seviyesini kontrol et"]),
        },
        follow_redirects=False,
    )
    assert create_response.status_code == 403

    delete_response = client.post(
        "/bakim/ekipman-sablonlari",
        data={
            "form_action": "delete_maintenance_form",
            "form_template_id": existing_form.id,
        },
        follow_redirects=False,
    )
    assert delete_response.status_code == 403
