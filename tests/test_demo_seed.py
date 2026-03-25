import re
from datetime import date

from demo_data import AIRPORT_PERSONNEL_COUNT, AIRPORTS, DEMO_SEED_TAG, clear_demo_data, seed_demo_data
from extensions import db, table_exists
from sqlalchemy import text
from models import (
    AssignmentItem,
    AssignmentRecipient,
    AssignmentRecord,
    AssetSparePartLink,
    DemoSeedRecord,
    EquipmentTemplate,
    Havalimani,
    InventoryAsset,
    Kutu,
    Kullanici,
    MaintenancePlan,
    Malzeme,
    SparePart,
    WorkOrder,
    WorkOrderPartUsage,
)
from tests.factories import KullaniciFactory


def _login(client, user_id):
    with client.session_transaction() as session:
        session.clear()
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_seed_demo_data_creates_expected_records(app):
    with app.app_context():
        summary = seed_demo_data(reset=True)

        assert summary["havalimani"] == 3
        assert summary["kullanici"] == (len(AIRPORTS) * AIRPORT_PERSONNEL_COUNT) + 2
        assert Havalimani.query.count() == 3
        assert Kullanici.query.count() == (len(AIRPORTS) * AIRPORT_PERSONNEL_COUNT) + 2
        assert InventoryAsset.query.count() > 0
        assert Kutu.query.count() > 0
        assert MaintenancePlan.query.count() > 0
        assert WorkOrder.query.count() > 0
        assert SparePart.query.count() >= 20
        assert {airport.kodu for airport in Havalimani.query.order_by(Havalimani.kodu.asc()).all()} == {"EDO", "ERZ", "KCO"}
        for airport in Havalimani.query.all():
            assert Kullanici.query.filter_by(havalimani_id=airport.id, is_deleted=False).count() >= AIRPORT_PERSONNEL_COUNT
            assert Kutu.query.filter_by(havalimani_id=airport.id, is_deleted=False).count() >= 5
        for box in Kutu.query.all():
            assert re.match(rf"^{box.havalimani.kodu}-SAR-\d{{2}}$", box.kodu)
            assert box.marka is not None and box.marka.strip() != ""
            assert not (box.konum or "").strip()

        sample_asset = InventoryAsset.query.first()
        assert sample_asset is not None
        assert sample_asset.airport is not None
        assert sample_asset.legacy_material is not None
        assert sample_asset.legacy_material.kutu is not None
        assert sample_asset.asset_code.startswith("ARFF-SAR-")
        assert sample_asset.equipment_template is not None
        assert (sample_asset.equipment_template.brand or "").strip() != ""
        assert (sample_asset.equipment_template.model_code or "").strip() != ""
        assert sample_asset.legacy_material.ad.startswith(sample_asset.equipment_template.name)

        today = date.today()
        critical_plans = MaintenancePlan.query.filter(MaintenancePlan.next_due_date < today).count()
        upcoming_plans = MaintenancePlan.query.filter(MaintenancePlan.next_due_date >= today).count()
        assert critical_plans > 0
        assert upcoming_plans > 0

        if table_exists("assignment_record"):
            assert AssignmentRecord.query.count() > 0
            assert AssignmentRecipient.query.count() > 0
            assert AssignmentItem.query.count() > 0
        if table_exists("asset_spare_part_link"):
            assert AssetSparePartLink.query.count() > 0
        if table_exists("work_order_part_usage"):
            assert WorkOrderPartUsage.query.count() > 0

        assert DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG).count() > 0


def test_clear_demo_data_only_removes_demo_records(app):
    with app.app_context():
        real_airport = Havalimani(ad="Gerçek Havalimanı", kodu="REAL")
        db.session.add(real_airport)
        db.session.flush()

        real_user = Kullanici(
            kullanici_adi="real.user@sarx.local",
            tam_ad="Gerçek Kullanıcı",
            rol="personel",
            havalimani_id=real_airport.id,
        )
        real_user.sifre_set("real-password")
        db.session.add(real_user)
        db.session.commit()

        seed_demo_data(reset=True)
        result = clear_demo_data()

        assert result["deleted"] > 0
        assert Havalimani.query.filter_by(kodu="REAL").first() is not None
        assert Kullanici.query.filter_by(kullanici_adi="real.user@sarx.local").first() is not None
        assert DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG).count() == 0
        assert Havalimani.query.count() == 1
        assert Kullanici.query.count() == 1


def test_clear_demo_data_handles_assets_linked_to_demo_templates(app):
    with app.app_context():
        db.session.execute(text("PRAGMA foreign_keys=ON"))

        with app.test_request_context("/admin/demo-veri/olustur"):
            seed_summary = seed_demo_data(reset=True)
        assert seed_summary["ekipman_sablonu"] > 0

        demo_template = EquipmentTemplate.query.first()
        assert demo_template is not None

        real_airport = Havalimani(ad="Gerçek Bağlantı Havalimanı", kodu="RBA")
        db.session.add(real_airport)
        db.session.flush()

        real_box = Kutu(kodu="RBA-BOX-01", havalimani_id=real_airport.id)
        db.session.add(real_box)
        db.session.flush()

        real_material = Malzeme(
            ad="Gerçek Bağlantı Malzemesi",
            seri_no="REAL-LINK-001",
            kutu_id=real_box.id,
            havalimani_id=real_airport.id,
        )
        db.session.add(real_material)
        db.session.flush()

        dependent_asset = InventoryAsset(
            equipment_template_id=demo_template.id,
            havalimani_id=real_airport.id,
            legacy_material_id=real_material.id,
            serial_no="REAL-ASSET-001",
            qr_code="REAL-ASSET-QR-001",
            status="aktif",
        )
        db.session.add(dependent_asset)
        db.session.commit()
        dependent_asset_id = dependent_asset.id

        with app.test_request_context("/admin/demo-veri/temizle"):
            result = clear_demo_data()
        assert result["deleted"] > 0
        assert InventoryAsset.query.filter_by(id=dependent_asset_id).first() is None
        assert DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG).count() == 0


def test_demo_clear_endpoint_succeeds_with_dependent_assets(client, app):
    with app.app_context():
        owner = KullaniciFactory(
            rol="sahip",
            is_deleted=False,
            tam_ad="Demo Owner",
            kullanici_adi="demo.owner@sarx.local",
        )
        db.session.add(owner)
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)

    seed_response = client.post(
        "/demo-veri/olustur",
        data={"confirm_demo_seed": "DEMO", "demo_reset": "1"},
        follow_redirects=True,
    )
    assert seed_response.status_code == 200
    assert "Demo verileri hazırlandı." in seed_response.data.decode("utf-8")

    with app.app_context():
        demo_template = EquipmentTemplate.query.first()
        assert demo_template is not None
        airport = Havalimani(ad="Gerçek Endpoint Havalimanı", kodu="REB")
        db.session.add(airport)
        db.session.flush()
        box = Kutu(kodu="REB-BOX-01", havalimani_id=airport.id)
        db.session.add(box)
        db.session.flush()
        material = Malzeme(
            ad="Gerçek Endpoint Malzeme",
            seri_no="REAL-ENDPOINT-001",
            kutu_id=box.id,
            havalimani_id=airport.id,
        )
        db.session.add(material)
        db.session.flush()
        dependent_asset = InventoryAsset(
            equipment_template_id=demo_template.id,
            havalimani_id=airport.id,
            legacy_material_id=material.id,
            serial_no="REAL-ENDPOINT-ASSET-001",
            qr_code="REAL-ENDPOINT-ASSET-QR-001",
            status="aktif",
        )
        db.session.add(dependent_asset)
        db.session.commit()
        dependent_asset_id = dependent_asset.id

    clear_response = client.post(
        "/demo-veri/temizle",
        data={"confirm_demo_clear": "DEMO-SIL"},
        follow_redirects=True,
    )
    clear_html = clear_response.data.decode("utf-8")
    assert clear_response.status_code == 200
    assert "Demo verileri temizlendi." in clear_html
    assert "Demo veri temizliği sırasında bir hata oluştu. İşlem geri alındı." not in clear_html

    with app.app_context():
        assert InventoryAsset.query.filter_by(id=dependent_asset_id).first() is None


def test_clear_demo_data_handles_assignment_recipients_for_demo_users(app):
    with app.app_context():
        seed_demo_data(reset=True)

        demo_user = DemoSeedRecord.query.filter_by(
            seed_tag=DEMO_SEED_TAG,
            model_name="Kullanici",
        ).first()
        assert demo_user is not None

        demo_kullanici = db.session.get(Kullanici, demo_user.record_id)
        assert demo_kullanici is not None

        assignment = AssignmentRecord(assignment_no="DM-ASSIGN-001", status="active")
        db.session.add(assignment)
        db.session.flush()

        recipient = AssignmentRecipient(assignment_id=assignment.id, user_id=demo_kullanici.id)
        db.session.add(recipient)
        db.session.commit()
        recipient_id = recipient.id

        result = clear_demo_data()
        assert result["deleted"] > 0
        assert AssignmentRecipient.query.filter_by(id=recipient_id).first() is None


def test_seed_and_clear_chain_is_stable_for_multiple_cycles(app):
    with app.app_context():
        first_seed = seed_demo_data(reset=True)
        first_clear = clear_demo_data()
        second_seed = seed_demo_data(reset=False)
        second_clear = clear_demo_data()

        assert first_seed["asset"] > 0
        assert second_seed["asset"] > 0
        assert first_clear["deleted"] > 0
        assert second_clear["deleted"] > 0
        assert DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG).count() == 0
