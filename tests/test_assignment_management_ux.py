import io
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pypdf import PdfReader
from sqlalchemy import event

from extensions import db
from models import (
    AssignmentItem,
    AssignmentRecipient,
    AssignmentRecord,
    AssetMeterReading,
    ConsumableItem,
    ConsumableStockMovement,
    MaintenanceTriggerRule,
    MeterDefinition,
)
from tests.factories import (
    AssignmentRecordFactory,
    EquipmentTemplateFactory,
    HavalimaniFactory,
    InventoryAssetFactory,
    KullaniciFactory,
    KutuFactory,
    MalzemeFactory,
)


def _login(client, user_id):
    with client.session_transaction() as session:
        session.clear()
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def _build_assignment(*, assignment_no, airport, delivered_by, recipient, material, status="active"):
    record = AssignmentRecordFactory(
        assignment_no=assignment_no,
        assignment_date=date(2026, 3, 19),
        airport=airport,
        delivered_by=delivered_by,
        created_by=delivered_by,
        status=status,
    )
    db.session.add(record)
    db.session.flush()
    db.session.add(AssignmentRecipient(assignment_id=record.id, user_id=recipient.id))
    db.session.add(
        AssignmentItem(
            assignment_id=record.id,
            material_id=material.id,
            item_name=material.ad,
            quantity=1,
            unit="adet",
        )
    )
    return record


def _extract_pdf_text(pdf_bytes):
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def test_zimmet_filter_by_recipient_limits_assignments_and_updates_summary(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        box = KutuFactory(kodu="K-ERZ-1", havalimani=airport)
        owner = KullaniciFactory(rol="sistem_sorumlusu", is_deleted=False, kullanici_adi="owner-zimmet@sarx.com")
        recipient_one = KullaniciFactory(
            rol="bakim_sorumlusu",
            is_deleted=False,
            tam_ad="Ayse Arama",
            kullanici_adi="ayse@sarx.com",
            havalimani=airport,
        )
        recipient_two = KullaniciFactory(
            rol="depo_sorumlusu",
            is_deleted=False,
            tam_ad="Mehmet Depo",
            kullanici_adi="mehmet@sarx.com",
            havalimani=airport,
        )
        material_one = MalzemeFactory(ad="Termal Kamera", seri_no="TERM-01", stok_miktari=2, kutu=box, havalimani=airport)
        material_two = MalzemeFactory(ad="Koruyucu Kask", seri_no="KASK-02", stok_miktari=4, kutu=box, havalimani=airport)
        db.session.add_all([airport, box, owner, recipient_one, recipient_two, material_one, material_two])
        db.session.flush()
        _build_assignment(
            assignment_no="ZMT-TEST-001",
            airport=airport,
            delivered_by=owner,
            recipient=recipient_one,
            material=material_one,
        )
        _build_assignment(
            assignment_no="ZMT-TEST-002",
            airport=airport,
            delivered_by=owner,
            recipient=recipient_two,
            material=material_two,
            status="returned",
        )
        db.session.commit()
        owner_id = owner.id
        recipient_one_id = recipient_one.id

    _login(client, owner_id)
    response = client.get(f"/zimmetler?recipient_id={recipient_one_id}")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "ZMT-TEST-001" in html
    assert "ZMT-TEST-002" not in html
    assert "Teslim alan: Ayse Arama" in html
    assert "<strong>1 kayıt</strong> mevcut filtrelerle listeleniyor." in html


def test_zimmet_create_panel_renders_selection_summaries_and_material_metadata(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Trabzon Havalimanı", kodu="TZX")
        box = KutuFactory(kodu="K-TZX-1", havalimani=airport)
        owner = KullaniciFactory(rol="sistem_sorumlusu", is_deleted=False, kullanici_adi="owner-panel@sarx.com")
        recipient = KullaniciFactory(
            rol="bakim_sorumlusu",
            is_deleted=False,
            tam_ad="Fatma Ekip",
            kullanici_adi="fatma@sarx.com",
            havalimani=airport,
        )
        material = MalzemeFactory(
            ad="Solunum Seti",
            seri_no="SOL-778",
            stok_miktari=3,
            kutu=box,
            havalimani=airport,
        )
        db.session.add_all([airport, box, owner, recipient, material])
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    response = client.get("/zimmetler")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert 'id="assignmentRecipientCounter"' in html
    assert 'id="assignmentMaterialCounter"' in html
    assert 'class="assignment-filter-actions"' in html
    assert 'id="assignmentRecipientQuickSelect"' in html
    assert 'id="assignmentMaterialQuickSelect"' in html
    assert 'id="assignmentRecipientSelection"' in html
    assert 'id="assignmentMaterialSelection"' in html
    assert 'data-selected-summary="recipient"' in html
    assert 'data-selected-summary="material"' in html
    assert 'id="assignmentRecipientAvailable" hidden' in html
    assert 'id="assignmentMaterialAvailable" hidden' in html
    assert 'id="assignmentRecipientToggle"' in html
    assert 'id="assignmentMaterialToggle"' in html
    assert 'data-choice-card' in html
    assert 'data-choice-inputs' in html
    assert "Fatma Ekip" in html
    assert ("Ekip Üyesi" in html) or ("Bakım Sorumlusu" in html)
    assert "Solunum Seti" in html
    assert "Seri No: SOL-778" in html
    assert "Stok 3" in html
    assert "Teslim alan personel seçin" in html
    assert "Zimmetlenecek malzemeyi seçin" in html
    assert "Henüz personel seçilmedi" in html
    assert "Henüz malzeme seçilmedi" in html
    assert "Tüm personel listesini aç" in html
    assert "Tüm malzeme listesini aç" in html
    assert 'name="delivered_by_name"' in html
    assert "manuel metin olarak kaydedilir" in html


def test_zimmet_selected_recipient_query_marks_choice_card_checked(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Adana Havalimanı", kodu="ADA")
        box = KutuFactory(kodu="K-ADA-1", havalimani=airport)
        owner = KullaniciFactory(rol="sistem_sorumlusu", is_deleted=False, kullanici_adi="owner-checked@sarx.com")
        recipient = KullaniciFactory(
            rol="ekip_uyesi",
            is_deleted=False,
            tam_ad="Secili Personel",
            kullanici_adi="secili@sarx.com",
            havalimani=airport,
        )
        material = MalzemeFactory(ad="Halat", seri_no="HLT-11", stok_miktari=1, kutu=box, havalimani=airport)
        db.session.add_all([airport, box, owner, recipient, material])
        db.session.commit()
        owner_id = owner.id
        recipient_id = recipient.id

    _login(client, owner_id)
    response = client.get(f"/zimmetler?recipient_id={recipient_id}")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert f'name="recipient_ids" value="{recipient_id}" checked' in html
    assert "quickSelectId: 'assignmentRecipientQuickSelect'" in html
    assert "quickSelectId: 'assignmentMaterialQuickSelect'" in html
    assert "Secili Personel için aktif zimmetler" in html
    assert "Hızlı seçimle kişi ekleyin; ayrıntılı tarama gerekirse listeyi ayrıca açabilirsiniz." in html
    assert 'id="assignmentRecipientEmpty"' in html
    assert 'id="assignmentMaterialEmpty"' in html
    assert 'id="assignmentRecipientAvailable" hidden' in html


def test_personnel_sees_own_active_assignment_panel(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Samsun Havalimanı", kodu="SZF")
        box = KutuFactory(kodu="K-SZF-1", havalimani=airport)
        owner = KullaniciFactory(rol="sistem_sorumlusu", is_deleted=False, kullanici_adi="owner-self@sarx.com")
        recipient = KullaniciFactory(
            rol="ekip_uyesi",
            is_deleted=False,
            tam_ad="Kendi Personeli",
            kullanici_adi="self@sarx.com",
            havalimani=airport,
        )
        material = MalzemeFactory(ad="Yangın Battaniyesi", seri_no="YB-01", stok_miktari=1, kutu=box, havalimani=airport)
        db.session.add_all([airport, box, owner, recipient, material])
        db.session.flush()
        _build_assignment(
            assignment_no="ZMT-SELF-001",
            airport=airport,
            delivered_by=owner,
            recipient=recipient,
            material=material,
        )
        db.session.commit()
        recipient_id = recipient.id

    _login(client, recipient_id)
    response = client.get("/zimmetler")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Size Atanan Aktif Malzemeler" in html
    assert "ZMT-SELF-001" in html
    assert "Yangın Battaniyesi" in html


def test_admin_cannot_create_assignment_when_not_owner_or_airport_manager(client, app):
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        airport = HavalimaniFactory(ad="Balıkesir Havalimanı", kodu="BZI")
        admin = KullaniciFactory(rol="admin", is_deleted=False, kullanici_adi="admin-zimmet@sarx.com", havalimani=airport)
        recipient = KullaniciFactory(rol="personel", is_deleted=False, tam_ad="Alıcı Personel", havalimani=airport)
        box = KutuFactory(kodu="K-BZI-1", havalimani=airport)
        material = MalzemeFactory(ad="Kurtarma Çantası", seri_no="KC-10", stok_miktari=2, kutu=box, havalimani=airport)
        db.session.add_all([airport, admin, recipient, box, material])
        db.session.commit()
        admin_id = admin.id
        recipient_id = recipient.id
        material_id = material.id
        airport_id = airport.id

    _login(client, admin_id)
    response = client.post(
        "/zimmetler",
        data={
            "assignment_date": "2026-03-20",
            "airport_id": airport_id,
            "delivered_by_name": "Harici Teslim Yetkilisi",
            "recipient_ids": [str(recipient_id)],
            "item_ids": [str(material_id)],
            f"item_qty_{material_id}": "1",
            f"item_unit_{material_id}": "adet",
        },
    )

    assert response.status_code == 403


def test_assignment_creation_saves_manual_delivered_by_name_and_multiple_items(client, app):
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        airport = HavalimaniFactory(ad="Erzincan Havalimanı", kodu="ERC")
        owner = KullaniciFactory(rol="sistem_sorumlusu", is_deleted=False, kullanici_adi="owner-multi@sarx.com", havalimani=airport)
        recipient = KullaniciFactory(rol="personel", is_deleted=False, tam_ad="Çoklu Alıcı", havalimani=airport)
        box = KutuFactory(kodu="K-ERC-1", havalimani=airport)
        material_one = MalzemeFactory(ad="Baret", seri_no="BAR-01", stok_miktari=2, kutu=box, havalimani=airport)
        material_two = MalzemeFactory(ad="Reflektif Yelek", seri_no="RY-02", stok_miktari=3, kutu=box, havalimani=airport)
        db.session.add_all([airport, owner, recipient, box, material_one, material_two])
        db.session.commit()
        owner_id = owner.id
        recipient_id = recipient.id
        airport_id = airport.id
        material_one_id = material_one.id
        material_two_id = material_two.id

    _login(client, owner_id)
    response = client.post(
        "/zimmetler",
        data={
            "assignment_date": "2026-03-20",
            "airport_id": airport_id,
            "delivered_by_name": "Nöbetçi Amir",
            "recipient_ids": [str(recipient_id)],
            "item_ids": [str(material_one_id), str(material_two_id)],
            f"item_qty_{material_one_id}": "1",
            f"item_unit_{material_one_id}": "adet",
            f"item_qty_{material_two_id}": "2",
            f"item_unit_{material_two_id}": "adet",
            "note": "Toplu teslim testi",
        },
        follow_redirects=True,
    )

    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Zimmet kaydı oluşturuldu." in html

    with app.app_context():
        record = AssignmentRecord.query.order_by(AssignmentRecord.id.desc()).first()
        assert record is not None
        assert record.delivered_by_name == "Nöbetçi Amir"
        assert len(record.items) == 2


def test_assignment_creation_uses_material_airport_when_recipient_is_global(client, app):
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        airport_a = HavalimaniFactory(ad="Çanakkale Havalimanı", kodu="CKL")
        airport_b = HavalimaniFactory(ad="Trabzon Havalimanı", kodu="TZX")
        owner = KullaniciFactory(rol="sistem_sorumlusu", is_deleted=False, kullanici_adi="owner-global@sarx.com", havalimani=airport_a)
        recipient_global = KullaniciFactory(
            rol="personel",
            is_deleted=False,
            tam_ad="Global Personel",
            kullanici_adi="global@sarx.com",
            havalimani=None,
        )
        box = KutuFactory(kodu="K-TZX-1", havalimani=airport_b)
        material = MalzemeFactory(ad="Saha Işığı", seri_no="TZX-LIGHT-01", stok_miktari=2, kutu=box, havalimani=airport_b)
        db.session.add_all([airport_a, airport_b, owner, recipient_global, box, material])
        db.session.commit()
        owner_id = owner.id
        airport_a_id = airport_a.id
        airport_b_id = airport_b.id
        recipient_id = recipient_global.id
        material_id = material.id

    _login(client, owner_id)
    response = client.post(
        "/zimmetler",
        data={
            "assignment_date": "2026-03-20",
            "airport_id": airport_a_id,
            "delivered_by_name": "Nöbetçi Amir",
            "recipient_ids": [str(recipient_id)],
            "item_ids": [str(material_id)],
            f"item_qty_{material_id}": "1",
            f"item_unit_{material_id}": "adet",
        },
        follow_redirects=True,
    )
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Zimmet kaydı oluşturuldu." in html
    assert "Zimmet Detayı" in html

    with app.app_context():
        record = AssignmentRecord.query.order_by(AssignmentRecord.id.desc()).first()
        assert record is not None
        assert record.airport_id == airport_b_id
        assert any(recipient.user_id == recipient_id for recipient in record.recipients)
        assert any(item.material_id == material_id for item in record.items)


def test_dashboard_meter_and_consumable_queries_are_batched(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Amasya Merzifon Havalimanı", kodu="MZH")
        owner = KullaniciFactory(rol="sistem_sorumlusu", is_deleted=False, kullanici_adi="owner-dashboard-batch@sarx.com", havalimani=airport)
        template = EquipmentTemplateFactory(name="Pompa Ünitesi", category="Mekanik")
        asset = InventoryAssetFactory(equipment_template=template, airport=airport, status="aktif")
        db.session.add_all([airport, owner, template, asset])
        db.session.flush()

        for idx in range(6):
            meter = MeterDefinition(
                name=f"Saat Sayacı {idx + 1}",
                meter_type="hours",
                unit="h",
                asset_id=asset.id,
                equipment_template_id=template.id,
                is_active=True,
            )
            db.session.add(meter)
            db.session.flush()
            db.session.add(
                MaintenanceTriggerRule(
                    name=f"Sayaç Kuralı {idx + 1}",
                    trigger_type="meter",
                    asset_id=asset.id,
                    meter_definition_id=meter.id,
                    threshold_value=100,
                    warning_lead_value=10,
                    is_active=True,
                )
            )
            db.session.add(
                AssetMeterReading(
                    asset_id=asset.id,
                    meter_definition_id=meter.id,
                    reading_value=95 + idx,
                    recorded_by_id=owner.id,
                )
            )

        for idx in range(6):
            consumable = ConsumableItem(
                code=f"SRF-{idx + 1:03d}",
                title=f"Sarf {idx + 1}",
                category="Sarf",
                unit="adet",
                min_stock_level=5,
                critical_level=2,
                is_active=True,
            )
            db.session.add(consumable)
            db.session.flush()
            db.session.add(
                ConsumableStockMovement(
                    consumable_id=consumable.id,
                    airport_id=airport.id,
                    movement_type="in",
                    quantity=10,
                    performed_by_id=owner.id,
                )
            )
            db.session.add(
                ConsumableStockMovement(
                    consumable_id=consumable.id,
                    airport_id=airport.id,
                    movement_type="out",
                    quantity=4,
                    performed_by_id=owner.id,
                )
            )

        db.session.commit()
        owner_id = owner.id
        engine = db.engine

    _login(client, owner_id)

    query_counters = {
        "asset_meter_reading_selects": 0,
        "consumable_stock_movement_selects": 0,
    }

    def _count_dashboard_queries(_conn, _cursor, statement, _parameters, _context, _executemany):
        normalized = str(statement or "").strip().lower()
        if not normalized.startswith("select"):
            return
        if " from asset_meter_reading" in normalized:
            query_counters["asset_meter_reading_selects"] += 1
        if " from consumable_stock_movement" in normalized:
            query_counters["consumable_stock_movement_selects"] += 1

    event.listen(engine, "before_cursor_execute", _count_dashboard_queries)
    try:
        response = client.get("/dashboard")
    finally:
        event.remove(engine, "before_cursor_execute", _count_dashboard_queries)

    assert response.status_code == 200
    assert query_counters["asset_meter_reading_selects"] <= 6
    assert query_counters["consumable_stock_movement_selects"] <= 4


def test_assignment_creation_stays_visible_when_platform_demo_scope_is_active(client, app):
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        from models import DemoSeedRecord, SiteAyarlari

        airport = HavalimaniFactory(ad="Ankara Esenboğa Havalimanı", kodu="ESB")
        owner = KullaniciFactory(rol="sistem_sorumlusu", is_deleted=False, kullanici_adi="owner-demo-zimmet@sarx.com")
        recipient = KullaniciFactory(rol="personel", is_deleted=False, tam_ad="Demo Alıcı", havalimani=airport)
        box = KutuFactory(kodu="K-ESB-DEMO", havalimani=airport)
        material = MalzemeFactory(ad="Demo Zimmet Cihazı", seri_no="DM-001", stok_miktari=1, kutu=box, havalimani=airport)
        db.session.add_all([airport, owner, recipient, box, material])
        db.session.flush()

        settings = SiteAyarlari.query.first() or SiteAyarlari()
        settings.iletisim_notu = json.dumps(
            {
                "platform_demo_state": {
                    "active": True,
                    "action": "test",
                    "updated_at": "01.04.2026 00:00",
                }
            },
            ensure_ascii=False,
        )
        db.session.add(settings)
        db.session.flush()

        db.session.add_all(
            [
                DemoSeedRecord(seed_tag="demo_seed", model_name="Havalimani", record_id=airport.id, record_label=airport.kodu),
                DemoSeedRecord(seed_tag="demo_seed", model_name="Kullanici", record_id=owner.id, record_label=owner.kullanici_adi),
                DemoSeedRecord(seed_tag="demo_seed", model_name="Kullanici", record_id=recipient.id, record_label=recipient.kullanici_adi),
                DemoSeedRecord(seed_tag="demo_seed", model_name="Kutu", record_id=box.id, record_label=box.kodu),
                DemoSeedRecord(seed_tag="demo_seed", model_name="Malzeme", record_id=material.id, record_label=material.seri_no),
            ]
        )
        db.session.commit()

        owner_id = owner.id
        recipient_id = recipient.id
        airport_id = airport.id
        material_id = material.id

    _login(client, owner_id)
    response = client.post(
        "/zimmetler",
        data={
            "assignment_date": "2026-03-20",
            "airport_id": airport_id,
            "delivered_by_name": "Demo Teslim Yetkilisi",
            "recipient_ids": [str(recipient_id)],
            "item_ids": [str(material_id)],
            f"item_qty_{material_id}": "1",
            f"item_unit_{material_id}": "adet",
        },
        follow_redirects=True,
    )
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Zimmet kaydı oluşturuldu." in html
    assert "Zimmet Detayı" in html

    with app.app_context():
        record = AssignmentRecord.query.order_by(AssignmentRecord.id.desc()).first()
        assert record is not None
        seed_row = DemoSeedRecord.query.filter_by(
            seed_tag="demo_seed",
            model_name="AssignmentRecord",
            record_id=record.id,
        ).first()
        assert seed_row is not None


def test_platform_demo_scope_controls_zimmet_create_detail_pdf_visibility(client, app):
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        from models import DemoSeedRecord, SiteAyarlari

        airport = HavalimaniFactory(ad="Demo Scope Havalimanı", kodu="DSH")
        owner = KullaniciFactory(rol="sistem_sorumlusu", is_deleted=False, kullanici_adi="owner-demo-scope@sarx.com")
        recipient = KullaniciFactory(rol="personel", is_deleted=False, tam_ad="Demo Scope Alıcı", havalimani=airport)
        box = KutuFactory(kodu="K-DSH-1", havalimani=airport)
        material = MalzemeFactory(ad="Demo Scope Cihazı", seri_no="DSH-001", stok_miktari=3, kutu=box, havalimani=airport)
        db.session.add_all([airport, owner, recipient, box, material])
        db.session.flush()

        assignment_in_demo = _build_assignment(
            assignment_no="ZMT-DEMO-001",
            airport=airport,
            delivered_by=owner,
            recipient=recipient,
            material=material,
        )
        assignment_outside_demo = _build_assignment(
            assignment_no="ZMT-DEMO-002",
            airport=airport,
            delivered_by=owner,
            recipient=recipient,
            material=material,
        )

        settings = SiteAyarlari.query.first() or SiteAyarlari()
        settings.iletisim_notu = json.dumps(
            {
                "platform_demo_state": {
                    "active": True,
                    "action": "test",
                    "updated_at": "01.04.2026 00:00",
                }
            },
            ensure_ascii=False,
        )
        db.session.add(settings)
        db.session.flush()

        db.session.add_all(
            [
                DemoSeedRecord(seed_tag="demo_seed", model_name="Havalimani", record_id=airport.id, record_label=airport.kodu),
                DemoSeedRecord(seed_tag="demo_seed", model_name="Kullanici", record_id=owner.id, record_label=owner.kullanici_adi),
                DemoSeedRecord(seed_tag="demo_seed", model_name="Kullanici", record_id=recipient.id, record_label=recipient.kullanici_adi),
                DemoSeedRecord(seed_tag="demo_seed", model_name="Kutu", record_id=box.id, record_label=box.kodu),
                DemoSeedRecord(seed_tag="demo_seed", model_name="Malzeme", record_id=material.id, record_label=material.seri_no),
                DemoSeedRecord(
                    seed_tag="demo_seed",
                    model_name="AssignmentRecord",
                    record_id=assignment_in_demo.id,
                    record_label=assignment_in_demo.assignment_no,
                ),
            ]
        )
        db.session.commit()

        owner_id = owner.id
        airport_id = airport.id
        recipient_id = recipient.id
        material_id = material.id
        visible_assignment_id = assignment_in_demo.id
        hidden_assignment_id = assignment_outside_demo.id

    _login(client, owner_id)
    list_response = client.get("/zimmetler")
    list_html = list_response.data.decode("utf-8")
    assert list_response.status_code == 200
    assert "ZMT-DEMO-001" in list_html
    assert "ZMT-DEMO-002" not in list_html

    detail_visible = client.get(f"/zimmetler/{visible_assignment_id}")
    assert detail_visible.status_code == 200
    assert "ZMT-DEMO-001" in detail_visible.data.decode("utf-8")

    detail_hidden = client.get(f"/zimmetler/{hidden_assignment_id}", follow_redirects=True)
    assert detail_hidden.status_code == 200
    assert "Zimmet kaydı bulunamadı veya erişim izniniz yok." in detail_hidden.data.decode("utf-8")

    pdf_visible = client.get(f"/zimmetler/{visible_assignment_id}/pdf")
    assert pdf_visible.status_code == 200
    assert "ZMT-DEMO-001" in _extract_pdf_text(pdf_visible.data)

    pdf_hidden = client.get(f"/zimmetler/{hidden_assignment_id}/pdf", follow_redirects=True)
    assert pdf_hidden.status_code == 200
    assert "PDF oluşturulacak zimmet kaydı bulunamadı." in pdf_hidden.data.decode("utf-8")

    create_response = client.post(
        "/zimmetler",
        data={
            "assignment_date": "2026-04-01",
            "airport_id": airport_id,
            "delivered_by_name": "Demo Scope Yetkilisi",
            "recipient_ids": [str(recipient_id)],
            "item_ids": [str(material_id)],
            f"item_qty_{material_id}": "1",
            f"item_unit_{material_id}": "adet",
        },
        follow_redirects=True,
    )
    create_html = create_response.data.decode("utf-8")
    assert create_response.status_code == 200
    assert "Zimmet kaydı oluşturuldu." in create_html

    with app.app_context():
        created = AssignmentRecord.query.order_by(AssignmentRecord.id.desc()).first()
        assert created is not None
        created_seed = DemoSeedRecord.query.filter_by(
            seed_tag="demo_seed",
            model_name="AssignmentRecord",
            record_id=created.id,
        ).first()
        assert created_seed is not None

    list_with_demo_sim = client.get("/zimmetler?demo_sim=1")
    list_with_demo_sim_html = list_with_demo_sim.data.decode("utf-8")
    assert list_with_demo_sim.status_code == 200
    assert "ZMT-DEMO-001" in list_with_demo_sim_html
    assert "ZMT-DEMO-002" not in list_with_demo_sim_html


def test_same_assignment_pdf_data_stays_same_with_platform_demo_on_off_and_demo_sim(client, app):
    with app.app_context():
        from models import DemoSeedRecord, SiteAyarlari

        airport = HavalimaniFactory(ad="Demo PDF Havalimanı", kodu="DPH")
        box = KutuFactory(kodu="K-DPH-1", havalimani=airport)
        owner = KullaniciFactory(rol="sistem_sorumlusu", is_deleted=False, tam_ad="Demo PDF Owner", kullanici_adi="owner-demo-pdf@sarx.com")
        recipient = KullaniciFactory(rol="personel", is_deleted=False, tam_ad="Demo PDF Recipient", havalimani=airport)
        equipment_template = EquipmentTemplateFactory(name="Demo Gaz Cihazı", brand="Dräger", model_code="X-am 2500")
        material = MalzemeFactory(ad="Demo PDF Ekipmanı", seri_no="DPH-001", stok_miktari=2, kutu=box, havalimani=airport)
        db.session.add_all([airport, box, owner, recipient, equipment_template, material])
        db.session.flush()
        asset = InventoryAssetFactory(
            equipment_template=equipment_template,
            airport=airport,
            legacy_material=material,
            serial_no="DPH-001",
            asset_tag=None,
        )
        db.session.add(asset)
        db.session.flush()

        assignment = _build_assignment(
            assignment_no="ZMT-DEMO-PDF-001",
            airport=airport,
            delivered_by=owner,
            recipient=recipient,
            material=material,
        )
        assignment.items[0].asset_id = asset.id
        assignment.note = "Demo açık/kapalı PDF içerik karşılaştırması."

        settings = SiteAyarlari.query.first() or SiteAyarlari()
        settings.iletisim_notu = json.dumps(
            {
                "platform_demo_state": {
                    "active": True,
                    "action": "test",
                    "updated_at": "01.04.2026 00:00",
                }
            },
            ensure_ascii=False,
        )
        db.session.add(settings)
        db.session.flush()

        db.session.add_all(
            [
                DemoSeedRecord(seed_tag="demo_seed", model_name="Havalimani", record_id=airport.id, record_label=airport.kodu),
                DemoSeedRecord(seed_tag="demo_seed", model_name="Kullanici", record_id=owner.id, record_label=owner.kullanici_adi),
                DemoSeedRecord(seed_tag="demo_seed", model_name="Kullanici", record_id=recipient.id, record_label=recipient.kullanici_adi),
                DemoSeedRecord(seed_tag="demo_seed", model_name="Kutu", record_id=box.id, record_label=box.kodu),
                DemoSeedRecord(seed_tag="demo_seed", model_name="Malzeme", record_id=material.id, record_label=material.seri_no),
                DemoSeedRecord(
                    seed_tag="demo_seed",
                    model_name="AssignmentRecord",
                    record_id=assignment.id,
                    record_label=assignment.assignment_no,
                ),
            ]
        )
        db.session.commit()
        owner_id = owner.id
        assignment_id = assignment.id

    _login(client, owner_id)

    pdf_demo_on = client.get(f"/zimmetler/{assignment_id}/pdf")
    assert pdf_demo_on.status_code == 200
    text_demo_on = _extract_pdf_text(pdf_demo_on.data)

    pdf_demo_on_sim = client.get(f"/zimmetler/{assignment_id}/pdf?demo_sim=1")
    assert pdf_demo_on_sim.status_code == 200
    text_demo_on_sim = _extract_pdf_text(pdf_demo_on_sim.data)

    with app.app_context():
        from models import SiteAyarlari

        settings = SiteAyarlari.query.first()
        raw_meta = {}
        if settings and settings.iletisim_notu:
            raw_meta = json.loads(settings.iletisim_notu)
        raw_state = raw_meta.get("platform_demo_state") if isinstance(raw_meta.get("platform_demo_state"), dict) else {}
        raw_state["active"] = False
        raw_state["action"] = "test"
        raw_meta["platform_demo_state"] = raw_state
        settings.iletisim_notu = json.dumps(raw_meta, ensure_ascii=False)
        db.session.add(settings)
        db.session.commit()

    pdf_demo_off = client.get(f"/zimmetler/{assignment_id}/pdf")
    assert pdf_demo_off.status_code == 200
    text_demo_off = _extract_pdf_text(pdf_demo_off.data)
    text_demo_on_norm = " ".join(text_demo_on.split())
    text_demo_on_sim_norm = " ".join(text_demo_on_sim.split())
    text_demo_off_norm = " ".join(text_demo_off.split())

    for expected in [
        "ZMT-DEMO-PDF-001",
        "Demo PDF Havalimanı",
        "Demo PDF Ekipmanı",
        "Dräger X-am 2500",
        "Demo açık/kapalı PDF içerik karşılaştırması.",
        "Zimmetlenen Malzeme Listesi",
        "Açıklama ve Sorumluluk Beyanı",
        "İmza Alanları",
    ]:
        assert expected in text_demo_on_norm
        assert expected in text_demo_on_sim_norm
        assert expected in text_demo_off_norm

    assert text_demo_on_norm == text_demo_on_sim_norm
    assert text_demo_on_norm == text_demo_off_norm


def test_zimmet_detail_formats_integer_like_quantities_without_trailing_decimal(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Isparta Havalimanı", kodu="ISE")
        box = KutuFactory(kodu="K-ISE-1", havalimani=airport)
        owner = KullaniciFactory(rol="sistem_sorumlusu", is_deleted=False, kullanici_adi="owner-qty@sarx.com", havalimani=airport)
        recipient = KullaniciFactory(rol="personel", is_deleted=False, tam_ad="Miktar Test", havalimani=airport)
        material = MalzemeFactory(ad="Miktar Test Ekipmanı", seri_no="QTY-001", stok_miktari=2, kutu=box, havalimani=airport)
        db.session.add_all([airport, box, owner, recipient, material])
        db.session.flush()
        assignment = _build_assignment(
            assignment_no="ZMT-QTY-001",
            airport=airport,
            delivered_by=owner,
            recipient=recipient,
            material=material,
        )
        item = assignment.items[0]
        item.quantity = 1.0
        item.returned_quantity = 1.0
        item.returned_by_id = owner.id
        db.session.commit()
        owner_id = owner.id
        assignment_id = assignment.id

    _login(client, owner_id)
    response = client.get(f"/zimmetler/{assignment_id}")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "1 adet" in html
    assert "0 adet" in html
    assert "1 adet iade" in html
    assert "1.0 adet" not in html
    assert "0.0 adet" not in html


def test_team_lead_can_delete_assignment(client, app):
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        airport = HavalimaniFactory(ad="Kars Havalimanı", kodu="KSY")
        owner = KullaniciFactory(rol="sistem_sorumlusu", is_deleted=False, kullanici_adi="owner-delete@sarx.com", havalimani=airport)
        team_lead = KullaniciFactory(rol="ekip_sorumlusu", is_deleted=False, kullanici_adi="lead-delete@sarx.com", havalimani=airport)
        personnel = KullaniciFactory(rol="personel", is_deleted=False, kullanici_adi="person-delete@sarx.com", havalimani=airport)
        box = KutuFactory(kodu="K-KSY-1", havalimani=airport)
        material = MalzemeFactory(ad="Silme Test Ekipmanı", seri_no="DEL-001", stok_miktari=1, kutu=box, havalimani=airport)
        db.session.add_all([airport, owner, team_lead, personnel, box, material])
        db.session.flush()
        assignment = _build_assignment(
            assignment_no="ZMT-DEL-001",
            airport=airport,
            delivered_by=owner,
            recipient=personnel,
            material=material,
        )
        db.session.commit()
        assignment_id = assignment.id
        team_lead_id = team_lead.id

    _login(client, team_lead_id)
    list_response = client.get("/zimmetler")
    list_html = list_response.data.decode("utf-8")
    assert list_response.status_code == 200
    assert f"/zimmetler/{assignment_id}/sil" in list_html

    detail_response = client.get(f"/zimmetler/{assignment_id}")
    detail_html = detail_response.data.decode("utf-8")
    assert detail_response.status_code == 200
    assert "Zimmeti Sil" in detail_html

    _login(client, team_lead_id)
    delete_response = client.post(f"/zimmetler/{assignment_id}/sil", follow_redirects=True)
    delete_html = delete_response.data.decode("utf-8")
    assert delete_response.status_code == 200
    assert "Zimmet kaydı silindi ve arşive taşındı." in delete_html

    with app.app_context():
        from models import AssignmentRecord

        deleted_record = db.session.get(AssignmentRecord, assignment_id)
        assert deleted_record is not None
        assert deleted_record.is_deleted is True


def test_admin_can_delete_assignment_and_legacy_routes_redirect(client, app):
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        airport = HavalimaniFactory(ad="Bursa Havalimanı", kodu="BTZ")
        owner = KullaniciFactory(rol="sistem_sorumlusu", is_deleted=False, kullanici_adi="owner-admin-delete@sarx.com", havalimani=airport)
        admin = KullaniciFactory(rol="sistem_sorumlusu", is_deleted=False, kullanici_adi="admin-delete@sarx.com", havalimani=airport)
        recipient = KullaniciFactory(rol="personel", is_deleted=False, tam_ad="Admin Silme Test", havalimani=airport)
        box = KutuFactory(kodu="K-BTZ-1", havalimani=airport)
        material = MalzemeFactory(ad="Admin Silme Ekipmanı", seri_no="ADM-001", stok_miktari=1, kutu=box, havalimani=airport)
        db.session.add_all([airport, owner, admin, recipient, box, material])
        db.session.flush()
        assignment = _build_assignment(
            assignment_no="ZMT-ADM-001",
            airport=airport,
            delivered_by=owner,
            recipient=recipient,
            material=material,
        )
        db.session.commit()
        assignment_id = assignment.id
        admin_id = admin.id

    _login(client, admin_id)
    legacy_detail = client.get(f"/zimmet/{assignment_id}", follow_redirects=False)
    assert legacy_detail.status_code == 302
    assert legacy_detail.headers["Location"].endswith(f"/zimmetler/{assignment_id}")

    legacy_pdf = client.get(f"/zimmet/{assignment_id}/pdf", follow_redirects=False)
    assert legacy_pdf.status_code == 302
    assert legacy_pdf.headers["Location"].endswith(f"/zimmetler/{assignment_id}/pdf")

    delete_response = client.post(f"/zimmetler/{assignment_id}/sil", follow_redirects=True)
    assert delete_response.status_code == 200
    assert "Zimmet kaydı silindi ve arşive taşındı." in delete_response.data.decode("utf-8")


def test_zimmet_pdf_renders_turkish_text_and_core_fields(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="İzmir Çiğli Havalimanı", kodu="IGL")
        box = KutuFactory(kodu="K-IGL-1", havalimani=airport)
        owner = KullaniciFactory(rol="sistem_sorumlusu", is_deleted=False, tam_ad="Çağrı Göğüş", kullanici_adi="owner-pdf@sarx.com")
        recipient = KullaniciFactory(
            rol="personel",
            is_deleted=False,
            tam_ad="Şule Işık",
            kullanici_adi="sule@sarx.com",
            havalimani=airport,
        )
        equipment_template = EquipmentTemplateFactory(
            name="Gaz Ölçüm Cihazı",
            brand="Dräger",
            model_code="X-am 2500",
        )
        material = MalzemeFactory(ad="Göğüs Ölçer", seri_no="CIG-ŞĞ-01", stok_miktari=2, kutu=box, havalimani=airport)
        db.session.add_all([airport, box, owner, recipient, equipment_template, material])
        db.session.flush()
        asset = InventoryAssetFactory(
            equipment_template=equipment_template,
            airport=airport,
            legacy_material=material,
            serial_no="CIG-ŞĞ-01",
            asset_tag=None,
        )
        db.session.add(asset)
        db.session.flush()
        assignment = _build_assignment(
            assignment_no="ZMT-TR-001",
            airport=airport,
            delivered_by=owner,
            recipient=recipient,
            material=material,
        )
        assignment.items[0].asset_id = asset.id
        assignment.note = "Çıkış öncesi ölçüm ve şarj kontrolü yapılmıştır."
        db.session.commit()
        owner_id = owner.id
        assignment_id = assignment.id

    _login(client, owner_id)
    response = client.get(f"/zimmetler/{assignment_id}/pdf")

    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    assert b"/Image" in response.data

    reader = PdfReader(io.BytesIO(response.data))
    page_texts = [(page.extract_text() or "") for page in reader.pages]
    text = "\n".join(page_texts)
    text_single_line = " ".join(text.split())
    template_text = Path("templates/zimmet_pdf.html").read_text(encoding="utf-8")
    assert len(page_texts) == 1
    assert "ARFF Arama Kurtarma Timi Envanter Yönetim Sistemi" in text
    assert "Zimmet Teslim Formu" in text or "Zimmet Teslim Formu" in template_text
    assert "Birim" in text or "meta-label\">Birim" in template_text
    assert "Belge No" in text or "meta-label\">Belge No" in template_text
    assert "Tarih" in text or "meta-label\">Tarih" in template_text
    assert "ZMT-TR-001" in text
    assert "İzmir Çiğli Havalimanı" in text_single_line
    assert "Çağrı Göğüş" in text
    assert "Şule Işık" in text
    assert "Göğüs Ölçer" in text
    assert "Dräger X-am 2500" in text
    assert "Demirba" in text
    assert "Çıkış öncesi ölçüm ve şarj kontrolü yapılmıştır." in text


def test_zimmet_pdf_single_item_keeps_explanation_and_signatures_on_first_page(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        box = KutuFactory(kodu="K-ERZ-1", havalimani=airport)
        owner = KullaniciFactory(rol="sistem_sorumlusu", is_deleted=False, tam_ad="Mehmet Cinocevi", kullanici_adi="owner-one-page@sarx.com")
        recipient = KullaniciFactory(rol="personel", is_deleted=False, tam_ad="Derya Kara", havalimani=airport)
        equipment_template = EquipmentTemplateFactory(name="Akülü Projektör", brand="Motorola", model_code="MDL-015")
        material = MalzemeFactory(ad="Akülü Projektör", seri_no="ERZ-SN-0010", stok_miktari=2, kutu=box, havalimani=airport)
        db.session.add_all([airport, box, owner, recipient, equipment_template, material])
        db.session.flush()
        asset = InventoryAssetFactory(
            equipment_template=equipment_template,
            airport=airport,
            legacy_material=material,
            serial_no="ERZ-SN-0010",
            asset_tag="ERZ-ASSET-0010",
        )
        db.session.add(asset)
        db.session.flush()
        assignment = _build_assignment(
            assignment_no="ZMT-ONE-PAGE-001",
            airport=airport,
            delivered_by=owner,
            recipient=recipient,
            material=material,
        )
        assignment.items[0].asset_id = asset.id
        assignment.note = (
            "Yukarıda bilgileri yer alan ekipmanları eksiksiz şekilde teslim aldım. "
            "Ekipmanları yalnızca görev kapsamında kullanacağımı, kullanım süresince koruyacağımı, "
            "zimmet kaydında belirtilen şartlara uyacağımı ve talep edilmesi halinde eksiksiz şekilde "
            "iade edeceğimi kabul ederim."
        )
        db.session.commit()
        owner_id = owner.id
        assignment_id = assignment.id

    _login(client, owner_id)
    response = client.get(f"/zimmetler/{assignment_id}/pdf")

    assert response.status_code == 200
    reader = PdfReader(io.BytesIO(response.data))
    page_texts = [(page.extract_text() or "") for page in reader.pages]
    assert len(page_texts) == 1
    first_page = page_texts[0]
    assert "Açıklama ve Sorumluluk Beyanı" in first_page
    assert "İmza Alanları" in first_page
    assert "Teslim Alan" in first_page
    assert "Teslim Eden" in first_page


def test_zimmet_pdf_two_page_flow_repeats_header_footer_and_keeps_closing_blocks_on_last_page(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Ankara Esenboğa Havalimanı", kodu="ESB")
        box = KutuFactory(kodu="K-ESB-1", havalimani=airport)
        owner = KullaniciFactory(rol="sistem_sorumlusu", is_deleted=False, tam_ad="Teslim Eden", kullanici_adi="owner-pdf-pages@sarx.com")
        recipient = KullaniciFactory(rol="personel", is_deleted=False, tam_ad="Teslim Alan", havalimani=airport)
        db.session.add_all([airport, box, owner, recipient])
        db.session.flush()
        assignment = AssignmentRecordFactory(
            assignment_no="ZMT-PAGE-001",
            assignment_date=date(2026, 3, 21),
            airport=airport,
            delivered_by=owner,
            created_by=owner,
            status="active",
            note="İçerik taşarsa imza bölümü yeni sayfada, tek blok halinde kalmalıdır.",
        )
        db.session.add(assignment)
        db.session.flush()
        db.session.add(AssignmentRecipient(assignment_id=assignment.id, user_id=recipient.id))
        for index in range(36):
            material = MalzemeFactory(
                ad=f"Koruyucu Donanım {index + 1}",
                seri_no=f"ESB-{index + 1:03d}",
                stok_miktari=2,
                kutu=box,
                havalimani=airport,
            )
            db.session.add(material)
            db.session.flush()
            db.session.add(
                AssignmentItem(
                    assignment_id=assignment.id,
                    material_id=material.id,
                    item_name=material.ad,
                    quantity=1,
                    unit="adet",
                    note="Rutin zimmet",
                )
            )
        db.session.commit()
        owner_id = owner.id
        assignment_id = assignment.id

    _login(client, owner_id)
    response = client.get(f"/zimmetler/{assignment_id}/pdf")

    assert response.status_code == 200
    reader = PdfReader(io.BytesIO(response.data))
    page_texts = [(page.extract_text() or "") for page in reader.pages]

    assert len(page_texts) >= 2
    assert all("Bu belge sistem kaydından üretilmiştir." in text for text in page_texts)
    assert "Zimmetlenen Malzeme Listesi" in page_texts[0]
    assert all("Zimmetlenen Malzeme Listesi" not in text for text in page_texts[1:])
    for text in page_texts:
        if "Koruyucu Donanım" in text:
            assert "Demirba" in text
            assert "Varl" in text
    assert all("Açıklama ve Sorumluluk Beyanı" not in text for text in page_texts[:-1])
    assert all("İmza Alanları" not in text for text in page_texts[:-1])
    assert any("Toplam" in text for text in page_texts)
    assert "Açıklama ve Sorumluluk Beyanı" in page_texts[-1]
    assert "Teslim Alan" in page_texts[-1]


def test_zimmet_pdf_template_keeps_a4_frame_layout_and_print_safe_units():
    template_text = Path("templates/zimmet_pdf.html").read_text(encoding="utf-8")

    assert "@frame page_header" not in template_text
    assert "@frame page_content" not in template_text
    assert "@frame page_footer" in template_text
    assert ".header-shell" in template_text
    assert ".header-grid" in template_text
    assert ".title-main" in template_text
    assert ".sheet" in template_text
    assert "repeat=\"1\"" in template_text
    assert "1</td>" in template_text
    assert "Zimmetlenen Malzeme Listesi" in template_text
    assert "meta-label\">Birim" in template_text
    assert ".logo-shell" in template_text
    assert ".meta-card" in template_text
    assert ".text-box" in template_text
    assert ".sign-box" in template_text
    assert ".code-wrap" in template_text
    assert "word-break: break-all;" in template_text
    assert "overflow-wrap: anywhere;" in template_text
    assert "margin-bottom: 1pt;" in template_text
    assert ".sign-line-wrap" in template_text
    assert "height: 41pt;" in template_text
    assert "background: #ffffff;" in template_text
    assert "min-height: 132pt;" in template_text
    assert "border-bottom: 2pt solid #0f2d4a;" in template_text
    assert ".top-band-cell" in template_text
    assert "height: 8pt;" in template_text
    assert "width: 27mm;" in template_text
    assert "height: 27mm;" in template_text
    assert "display: flex" not in template_text
    assert "display:grid" not in template_text
    assert "display: grid" not in template_text
    assert "var(--" not in template_text
    assert "box-shadow" not in template_text
    assert "Belge ve Teslim Bilgileri" not in template_text


def test_zimmet_pdf_logo_uri_uses_repo_logo_first_and_is_not_downloads_dependent(app):
    with app.app_context():
        from routes.inventory import _assignment_pdf_logo_uri

        logo_uri = _assignment_pdf_logo_uri()
        assert logo_uri.startswith("/") or logo_uri == ""

        preferred_candidates = [
            (Path(app.root_path) / "static" / "img" / "arfflogo.png").resolve(),
            (Path(app.root_path) / "static" / "img" / "logo_guncell.png").resolve(),
            (Path(app.root_path) / "static" / "img" / "logo_guncel.png").resolve(),
        ]
        expected = next((str(path) for path in preferred_candidates if path.exists()), "")
        if expected:
            assert logo_uri == expected
            assert "Downloads" not in logo_uri

        if logo_uri:
            resolved_path = Path(logo_uri)
            assert resolved_path.exists()


def test_zimmet_pdf_three_page_flow_keeps_header_footer_and_last_page_sections(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="İstanbul Havalimanı", kodu="IST")
        box = KutuFactory(kodu="K-IST-1", havalimani=airport)
        owner = KullaniciFactory(rol="sistem_sorumlusu", is_deleted=False, tam_ad="Teslim Yetkilisi", kullanici_adi="owner-pdf-3page@sarx.com")
        recipient = KullaniciFactory(rol="personel", is_deleted=False, tam_ad="Ekip Personeli", havalimani=airport)
        db.session.add_all([airport, box, owner, recipient])
        db.session.flush()

        assignment = AssignmentRecordFactory(
            assignment_no="ZMT-PAGE-003",
            assignment_date=date(2026, 3, 22),
            airport=airport,
            delivered_by=owner,
            created_by=owner,
            status="active",
            note="Tablo uzadığında kapanış blokları son sayfada tek parça kalmalıdır.",
        )
        db.session.add(assignment)
        db.session.flush()
        db.session.add(AssignmentRecipient(assignment_id=assignment.id, user_id=recipient.id))
        for index in range(64):
            material = MalzemeFactory(
                ad=f"Yangın Ekipmanı {index + 1}",
                seri_no=f"IST-{index + 1:03d}",
                stok_miktari=3,
                kutu=box,
                havalimani=airport,
            )
            db.session.add(material)
            db.session.flush()
            db.session.add(
                AssignmentItem(
                    assignment_id=assignment.id,
                    material_id=material.id,
                    item_name=material.ad,
                    quantity=1,
                    unit="adet",
                    note="Planlı zimmet",
                )
            )
        db.session.commit()
        owner_id = owner.id
        assignment_id = assignment.id

    _login(client, owner_id)
    response = client.get(f"/zimmetler/{assignment_id}/pdf")

    assert response.status_code == 200
    reader = PdfReader(io.BytesIO(response.data))
    page_texts = [(page.extract_text() or "") for page in reader.pages]

    assert len(page_texts) >= 3
    assert all("Bu belge sistem kaydından üretilmiştir." in text for text in page_texts)
    assert "Zimmetlenen Malzeme Listesi" in page_texts[0]
    assert all("Zimmetlenen Malzeme Listesi" not in text for text in page_texts[1:])
    for text in page_texts:
        if "Yangın Ekipmanı" in text:
            assert "Demirba" in text
            assert "Varl" in text
    assert all("Açıklama ve Sorumluluk Beyanı" not in text for text in page_texts[:-1])
    assert all("İmza Alanları" not in text for text in page_texts[:-1])
    assert any("Toplam" in text for text in page_texts)
    assert "Açıklama ve Sorumluluk Beyanı" in page_texts[-1]
    assert "İmza Alanları" in page_texts[-1]


def test_assignment_create_detail_pdf_flow_stays_working(client, app):
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        airport = HavalimaniFactory(ad="Rize Artvin Havalimanı", kodu="RZV")
        owner = KullaniciFactory(rol="sistem_sorumlusu", is_deleted=False, tam_ad="Akış Sahibi", havalimani=airport)
        recipient = KullaniciFactory(rol="personel", is_deleted=False, tam_ad="Akış Alıcısı", havalimani=airport)
        box = KutuFactory(kodu="K-RZV-1", havalimani=airport)
        material = MalzemeFactory(ad="Akış Test Cihazı", seri_no="AKS-001", stok_miktari=2, kutu=box, havalimani=airport)
        db.session.add_all([airport, owner, recipient, box, material])
        db.session.commit()
        owner_id = owner.id
        recipient_id = recipient.id
        airport_id = airport.id
        material_id = material.id

    _login(client, owner_id)
    create_response = client.post(
        "/zimmetler",
        data={
            "assignment_date": "2026-04-01",
            "airport_id": airport_id,
            "delivered_by_name": "Akış Test Yetkilisi",
            "recipient_ids": [str(recipient_id)],
            "item_ids": [str(material_id)],
            f"item_qty_{material_id}": "1",
            f"item_unit_{material_id}": "adet",
            "note": "Create-detail-pdf akış doğrulama notu.",
        },
        follow_redirects=True,
    )
    create_html = create_response.data.decode("utf-8")
    assert create_response.status_code == 200
    assert "Zimmet kaydı oluşturuldu." in create_html
    assert "Zimmet Detayı" in create_html

    with app.app_context():
        assignment = AssignmentRecord.query.order_by(AssignmentRecord.id.desc()).first()
        assert assignment is not None
        assignment_id = assignment.id
        assignment_no = assignment.assignment_no

    detail_response = client.get(f"/zimmetler/{assignment_id}")
    detail_html = detail_response.data.decode("utf-8")
    assert detail_response.status_code == 200
    assert assignment_no in detail_html
    assert "PDF İndir" in detail_html

    pdf_response = client.get(f"/zimmetler/{assignment_id}/pdf")
    assert pdf_response.status_code == 200
    assert pdf_response.mimetype == "application/pdf"


def test_signed_assignment_document_upload_flow_stays_working(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Antalya Havalimanı", kodu="AYT")
        box = KutuFactory(kodu="K-AYT-1", havalimani=airport)
        owner = KullaniciFactory(rol="sistem_sorumlusu", is_deleted=False, kullanici_adi="owner-upload@sarx.com")
        recipient = KullaniciFactory(rol="personel", is_deleted=False, tam_ad="Belge Alan", havalimani=airport)
        material = MalzemeFactory(ad="Termal Kamera", seri_no="TRM-01", stok_miktari=1, kutu=box, havalimani=airport)
        db.session.add_all([airport, box, owner, recipient, material])
        db.session.flush()
        assignment = _build_assignment(
            assignment_no="ZMT-UP-001",
            airport=airport,
            delivered_by=owner,
            recipient=recipient,
            material=material,
        )
        db.session.commit()
        owner_id = owner.id
        assignment_id = assignment.id

    _login(client, owner_id)
    with patch("routes.inventory.get_storage_adapter") as mocked_storage:
        mocked_storage.return_value.save_upload.return_value = SimpleNamespace(
            storage_key="AYT/zimmet/Belge_Alan/kkd_belge_alan_zimmet_20260320010101.pdf",
            public_url="https://example.com/uploads/AYT/zimmet/Belge_Alan/kkd_belge_alan_zimmet_20260320010101.pdf",
        )
        response = client.post(
            f"/zimmetler/{assignment_id}/signed-document",
            data={
                "signed_document": (io.BytesIO(b"%PDF-1.4 test belge"), "Şule Işık.pdf"),
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )

    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "İmzalı zimmet belgesi yüklendi." in html

    upload_call = mocked_storage.return_value.save_upload.call_args.kwargs
    assert upload_call["folder"] == "AYT/zimmet/Belge_Alan"
    assert upload_call["filename"].startswith("kkd_belge_alan_zimmet_")
    assert upload_call["filename"].endswith(".pdf")

    with app.app_context():
        from models import AssignmentRecord

        stored = db.session.get(AssignmentRecord, assignment_id)
        assert stored.signed_document_key == "AYT/zimmet/Belge_Alan/kkd_belge_alan_zimmet_20260320010101.pdf"
        assert stored.signed_document_url == "https://example.com/uploads/AYT/zimmet/Belge_Alan/kkd_belge_alan_zimmet_20260320010101.pdf"
        assert stored.signed_document_name == "Şule Işık.pdf"


def test_signed_assignment_document_upload_rejects_invalid_signature(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Dalaman Havalimanı", kodu="DLM")
        box = KutuFactory(kodu="K-DLM-1", havalimani=airport)
        owner = KullaniciFactory(rol="sistem_sorumlusu", is_deleted=False, kullanici_adi="owner-invalid-upload@sarx.com")
        recipient = KullaniciFactory(rol="personel", is_deleted=False, tam_ad="Belge Alan", havalimani=airport)
        material = MalzemeFactory(ad="Kurtarma Halatı", seri_no="HLT-404", stok_miktari=1, kutu=box, havalimani=airport)
        db.session.add_all([airport, box, owner, recipient, material])
        db.session.flush()
        assignment = _build_assignment(
            assignment_no="ZMT-UP-404",
            airport=airport,
            delivered_by=owner,
            recipient=recipient,
            material=material,
        )
        db.session.commit()
        owner_id = owner.id
        assignment_id = assignment.id

    _login(client, owner_id)
    response = client.post(
        f"/zimmetler/{assignment_id}/signed-document",
        data={
            "signed_document": (io.BytesIO(b"not-a-real-pdf"), "zimmet-imzali.pdf", "application/pdf"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Dosya türü desteklenmiyor." in html

    with app.app_context():
        from models import AssignmentRecord

        stored = db.session.get(AssignmentRecord, assignment_id)
        assert stored.signed_document_key in (None, "")


def test_signed_assignment_document_upload_rejects_non_pdf_files(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Gazipaşa Havalimanı", kodu="GZP")
        box = KutuFactory(kodu="K-GZP-1", havalimani=airport)
        owner = KullaniciFactory(rol="sistem_sorumlusu", is_deleted=False, kullanici_adi="owner-image-upload@sarx.com")
        recipient = KullaniciFactory(rol="personel", is_deleted=False, tam_ad="PDF Zorunlu", havalimani=airport)
        material = MalzemeFactory(ad="Koruyucu Maske", seri_no="MSK-220", stok_miktari=1, kutu=box, havalimani=airport)
        db.session.add_all([airport, box, owner, recipient, material])
        db.session.flush()
        assignment = _build_assignment(
            assignment_no="ZMT-UP-IMG",
            airport=airport,
            delivered_by=owner,
            recipient=recipient,
            material=material,
        )
        db.session.commit()
        owner_id = owner.id
        assignment_id = assignment.id

    _login(client, owner_id)
    response = client.post(
        f"/zimmetler/{assignment_id}/signed-document",
        data={
            "signed_document": (io.BytesIO(b"\x89PNG\r\n\x1a\nfake"), "zimmet.png", "image/png"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Dosya uzantısı desteklenmiyor." in html
