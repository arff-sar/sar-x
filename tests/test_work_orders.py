from datetime import timedelta

from extensions import db
from models import MaintenanceHistory, MaintenancePlan, UserPermissionOverride, WorkOrder, get_tr_now
from tests.factories import EquipmentTemplateFactory, HavalimaniFactory, InventoryAssetFactory, KullaniciFactory


def _login(client, user):
    with client.session_transaction() as sess:
        sess.clear()
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


def test_work_order_can_be_opened_and_closed(client, app):
    airport = HavalimaniFactory(kodu="ESB")
    manager = KullaniciFactory(rol="yetkili", havalimani=airport)
    template = EquipmentTemplateFactory(name="Solunum Seti", maintenance_period_days=30)
    asset = InventoryAssetFactory(equipment_template=template, airport=airport, serial_no="WO-SN-1", qr_code="WO-QR-1")
    db.session.add_all([airport, manager, template, asset])
    db.session.commit()
    _login(client, manager)

    create_response = client.post(
        "/bakim/is-emri/yeni",
        data={
            "asset_id": asset.id,
            "maintenance_type": "bakim",
            "description": "Aylık kontrol",
            "priority": "orta",
            "target_date": get_tr_now().date().strftime("%Y-%m-%d"),
            "assigned_user_id": manager.id,
        },
        follow_redirects=True,
    )
    assert create_response.status_code == 200

    work_order = WorkOrder.query.order_by(WorkOrder.id.desc()).first()
    assert work_order is not None
    assert work_order.status == "acik"

    close_response = client.post(
        f"/bakim/is-emri/{work_order.id}/kapat",
        data={
            "result": "Bakım tamamlandı",
            "used_parts": "Filtre",
            "labor_hours": 1.5,
            "extra_notes": "Test başarılı",
        },
        follow_redirects=True,
    )
    assert close_response.status_code == 200

    db.session.refresh(work_order)
    assert work_order.status == "tamamlandi"
    assert work_order.completed_at is not None
    history = MaintenanceHistory.query.filter_by(work_order_id=work_order.id).first()
    assert history is not None


def test_work_orders_page_filter_toolbar_and_type_labels_are_localized(client, app):
    airport = HavalimaniFactory(kodu="ESB")
    owner = KullaniciFactory(rol="sahip", havalimani=airport)
    template = EquipmentTemplateFactory(name="Yangın Söndürme Seti")
    asset = InventoryAssetFactory(
        equipment_template=template,
        airport=airport,
        serial_no="WO-TR-1",
        qr_code="WO-TR-QR-1",
    )
    work_order = WorkOrder(
        work_order_no="WO-TR-LABEL-1",
        asset=asset,
        maintenance_type="bakim",
        work_order_type="emergency",
        description="Yerelleştirme testi",
        created_user=owner,
        assigned_user=owner,
        status="acik",
        priority="kritik",
    )
    db.session.add_all([airport, owner, template, asset, work_order])
    db.session.commit()
    _login(client, owner)

    response = client.get("/bakim/is-emirleri?work_order_type=emergency")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert 'class="work-order-filter-form"' in html
    assert 'class="work-order-filter-actions"' in html
    assert "İş Emri Tipi" in html
    assert "value=\"emergency\" selected" in html
    assert ">ÖNLEYİCİ<" in html
    assert ">ACİL<" in html
    assert ">KALİBRASYON<" in html
    assert ">MUAYENE<" in html
    assert ">DÜZELTİCİ<" in html
    assert "<th>İŞ TİPİ</th>" in html
    assert ">KRİTİK<" in html
    assert ">KRITIK<" not in html
    assert "WO Tipi" not in html
    assert ">EMERGENCY<" not in html


def test_work_order_detail_uses_turkish_uppercase_for_visual_labels(client, app):
    airport = HavalimaniFactory(kodu="ADB")
    owner = KullaniciFactory(rol="sahip", havalimani=airport)
    template = EquipmentTemplateFactory(name="Ölçüm Cihazı")
    asset = InventoryAssetFactory(
        equipment_template=template,
        airport=airport,
        serial_no="WO-DET-TR-1",
        qr_code="WO-DET-TR-QR-1",
    )
    work_order = WorkOrder(
        work_order_no="WO-DET-TR-1",
        asset=asset,
        maintenance_type="bakim",
        work_order_type="inspection",
        source_type="is_emri",
        description="Türkçe upper görünüm testi",
        created_user=owner,
        assigned_user=owner,
        status="acik",
        priority="kritik",
    )
    db.session.add_all([airport, owner, template, asset, work_order])
    db.session.commit()
    _login(client, owner)

    response = client.get(f"/bakim/is-emri/{work_order.id}")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "KRİTİK" in html
    assert "KRITIK" not in html


def test_next_maintenance_date_is_calculated_after_closure(client, app):
    today = get_tr_now().date()
    airport = HavalimaniFactory(kodu="ADB")
    owner = KullaniciFactory(rol="sahip")
    template = EquipmentTemplateFactory(name="Basınç Tüpü", maintenance_period_days=20)
    asset = InventoryAssetFactory(
        equipment_template=template,
        airport=airport,
        serial_no="PLAN-SN-1",
        qr_code="PLAN-QR-1",
        maintenance_period_days=20,
    )
    plan = MaintenancePlan(
        name="Test Plan",
        asset=asset,
        equipment_template=template,
        owner_airport_id=airport.id,
        period_days=20,
        start_date=today,
        is_active=True,
    )
    work_order = WorkOrder(
        work_order_no="WO-PLAN-1",
        asset=asset,
        maintenance_type="bakim",
        description="Planlı bakım",
        created_user=owner,
        assigned_user=owner,
        status="acik",
        priority="yuksek",
    )
    db.session.add_all([airport, owner, template, asset, plan, work_order])
    db.session.commit()
    _login(client, owner)

    response = client.post(
        f"/bakim/is-emri/{work_order.id}/kapat",
        data={"result": "Tamamlandı"},
        follow_redirects=True,
    )
    assert response.status_code == 200

    db.session.refresh(asset)
    expected_date = today + timedelta(days=20)
    assert asset.next_maintenance_date == expected_date


def test_owner_can_create_work_order_across_airports(client, app):
    airport_a = HavalimaniFactory(kodu="ERZ")
    airport_b = HavalimaniFactory(kodu="KCO")
    owner = KullaniciFactory(rol="sahip")
    assignee_other_airport = KullaniciFactory(rol="personel", havalimani=airport_b)
    template = EquipmentTemplateFactory(name="Kurtarma Ekipmanı", maintenance_period_days=15)
    asset_airport_a = InventoryAssetFactory(
        equipment_template=template,
        airport=airport_a,
        serial_no="OWN-SN-1",
        qr_code="OWN-QR-1",
    )
    db.session.add_all([airport_a, airport_b, owner, assignee_other_airport, template, asset_airport_a])
    db.session.commit()
    _login(client, owner)

    response = client.post(
        "/bakim/is-emri/yeni",
        data={
            "asset_id": asset_airport_a.id,
            "assigned_user_id": assignee_other_airport.id,
            "maintenance_type": "bakim",
            "description": "Global owner cross-airport create",
            "priority": "orta",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    created = WorkOrder.query.order_by(WorkOrder.id.desc()).first()
    assert created is not None
    assert created.asset_id == asset_airport_a.id
    assert created.assigned_user_id == assignee_other_airport.id


def test_airport_manager_sees_only_own_scope_on_create_form(client, app):
    airport_a = HavalimaniFactory(kodu="TZX")
    airport_b = HavalimaniFactory(kodu="ADA")
    manager = KullaniciFactory(rol="ekip_sorumlusu", havalimani=airport_a)
    own_user = KullaniciFactory(rol="personel", havalimani=airport_a, tam_ad="Kendi Personel")
    other_user = KullaniciFactory(rol="personel", havalimani=airport_b, tam_ad="Diger Personel")
    template = EquipmentTemplateFactory(name="Scope Test Cihazı")
    own_asset = InventoryAssetFactory(equipment_template=template, airport=airport_a, serial_no="SC-A-1", qr_code="SC-A-QR")
    other_asset = InventoryAssetFactory(equipment_template=template, airport=airport_b, serial_no="SC-B-1", qr_code="SC-B-QR")
    db.session.add_all([airport_a, airport_b, manager, own_user, other_user, template, own_asset, other_asset])
    db.session.commit()
    _login(client, manager)

    response = client.get("/bakim/is-emri/yeni")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Kendi Personel" in html
    assert "Diger Personel" not in html
    assert "SC-A-1" in html
    assert "SC-B-1" not in html


def test_airport_manager_cannot_create_with_out_of_scope_asset_or_user(client, app):
    airport_a = HavalimaniFactory(kodu="BJV")
    airport_b = HavalimaniFactory(kodu="GZT")
    manager = KullaniciFactory(rol="ekip_sorumlusu", havalimani=airport_a)
    own_user = KullaniciFactory(rol="personel", havalimani=airport_a)
    other_user = KullaniciFactory(rol="personel", havalimani=airport_b)
    template = EquipmentTemplateFactory(name="Scope Guard Cihazı")
    own_asset = InventoryAssetFactory(equipment_template=template, airport=airport_a, serial_no="GUARD-A", qr_code="GUARD-A-QR")
    other_asset = InventoryAssetFactory(equipment_template=template, airport=airport_b, serial_no="GUARD-B", qr_code="GUARD-B-QR")
    db.session.add_all([airport_a, airport_b, manager, own_user, other_user, template, own_asset, other_asset])
    db.session.commit()
    _login(client, manager)

    success = client.post(
        "/bakim/is-emri/yeni",
        data={
            "asset_id": own_asset.id,
            "assigned_user_id": own_user.id,
            "maintenance_type": "bakim",
            "description": "Own scope create",
            "priority": "orta",
        },
        follow_redirects=True,
    )
    assert success.status_code == 200

    invalid_asset = client.post(
        "/bakim/is-emri/yeni",
        data={
            "asset_id": other_asset.id,
            "assigned_user_id": own_user.id,
            "maintenance_type": "bakim",
            "description": "Out of scope asset",
            "priority": "orta",
        },
        follow_redirects=False,
    )
    assert invalid_asset.status_code in {302, 403}

    invalid_user = client.post(
        "/bakim/is-emri/yeni",
        data={
            "asset_id": own_asset.id,
            "assigned_user_id": other_user.id,
            "maintenance_type": "bakim",
            "description": "Out of scope user",
            "priority": "orta",
        },
        follow_redirects=False,
    )
    assert invalid_user.status_code == 403


def test_create_button_and_form_are_visible_with_create_permission_even_without_edit(client, app):
    airport = HavalimaniFactory(kodu="SAW")
    manager = KullaniciFactory(rol="ekip_sorumlusu", havalimani=airport)
    template = EquipmentTemplateFactory(name="Create Permission Cihazı")
    asset = InventoryAssetFactory(equipment_template=template, airport=airport, serial_no="CRT-01", qr_code="CRT-QR-01")
    db.session.add_all(
        [
            airport,
            manager,
            template,
            asset,
            UserPermissionOverride(user=manager, permission_key="workorder.edit", is_allowed=False),
        ]
    )
    db.session.commit()

    _login(client, manager)
    manager_list = client.get("/bakim/is-emirleri")
    manager_html = manager_list.data.decode("utf-8")
    assert manager_list.status_code == 200
    assert "İş Emri Oluştur" in manager_html
    assert client.get("/bakim/is-emri/yeni").status_code == 200
    create_response = client.post(
        "/bakim/is-emri/yeni",
        data={
            "asset_id": asset.id,
            "assigned_user_id": manager.id,
            "maintenance_type": "bakim",
            "description": "Create var, edit yok",
            "priority": "orta",
        },
        follow_redirects=True,
    )
    assert create_response.status_code == 200


def test_create_button_hidden_and_form_forbidden_without_create_permission(client, app):
    viewer = KullaniciFactory(rol="ekip_sorumlusu")
    db.session.add_all(
        [
            viewer,
            UserPermissionOverride(user=viewer, permission_key="workorder.create", is_allowed=False),
        ]
    )
    db.session.commit()

    _login(client, viewer)
    viewer_list = client.get("/bakim/is-emirleri")
    viewer_html = viewer_list.data.decode("utf-8")
    assert viewer_list.status_code == 200
    assert "İş Emri Oluştur" not in viewer_html
    assert client.get("/bakim/is-emri/yeni").status_code == 403
    assert client.post("/bakim/is-emri/yeni", data={"asset_id": 1, "description": "x"}, follow_redirects=False).status_code == 403
