import re
from datetime import date

import demo_data
import homepage_demo
import pytest
from demo_data import AIRPORT_PERSONNEL_COUNT, AIRPORTS, DEMO_SEED_TAG, clear_demo_data, seed_demo_data
from extensions import db, table_exists
from sqlalchemy import text
from models import (
    AssetOperationalState,
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
    MaintenanceInstruction,
    MaintenancePlan,
    Malzeme,
    PPERecord,
    PPERecordEvent,
    PPEAssignmentRecord,
    PPEAssignmentItem,
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


def _downgrade_calibration_record_table_to_legacy_schema():
    db.session.execute(text("PRAGMA foreign_keys=OFF"))
    db.session.execute(
        text(
            """
            CREATE TABLE calibration_record_legacy (
                id INTEGER NOT NULL PRIMARY KEY,
                asset_id INTEGER NOT NULL,
                work_order_id INTEGER,
                calibration_schedule_id INTEGER,
                calibration_date DATE NOT NULL,
                next_calibration_date DATE,
                calibrated_by_id INTEGER,
                provider VARCHAR(150),
                certificate_no VARCHAR(120),
                certificate_file VARCHAR(500),
                result_status VARCHAR(30),
                note TEXT,
                created_at DATETIME,
                updated_at DATETIME,
                is_deleted BOOLEAN,
                deleted_at DATETIME
            )
            """
        )
    )
    db.session.execute(
        text(
            """
            INSERT INTO calibration_record_legacy (
                id,
                asset_id,
                work_order_id,
                calibration_schedule_id,
                calibration_date,
                next_calibration_date,
                calibrated_by_id,
                provider,
                certificate_no,
                certificate_file,
                result_status,
                note,
                created_at,
                updated_at,
                is_deleted,
                deleted_at
            )
            SELECT
                id,
                asset_id,
                work_order_id,
                calibration_schedule_id,
                calibration_date,
                next_calibration_date,
                calibrated_by_id,
                provider,
                certificate_no,
                certificate_file,
                result_status,
                note,
                created_at,
                updated_at,
                is_deleted,
                deleted_at
            FROM calibration_record
            """
        )
    )
    db.session.execute(text("DROP TABLE calibration_record"))
    db.session.execute(text("ALTER TABLE calibration_record_legacy RENAME TO calibration_record"))
    db.session.execute(text("CREATE INDEX ix_calibration_record_asset_id ON calibration_record(asset_id)"))
    db.session.execute(text("CREATE INDEX ix_calibration_record_calibrated_by_id ON calibration_record(calibrated_by_id)"))
    db.session.execute(text("CREATE INDEX ix_calibration_record_calibration_date ON calibration_record(calibration_date)"))
    db.session.execute(
        text("CREATE INDEX ix_calibration_record_calibration_schedule_id ON calibration_record(calibration_schedule_id)")
    )
    db.session.execute(text("CREATE INDEX ix_calibration_record_certificate_no ON calibration_record(certificate_no)"))
    db.session.execute(text("CREATE INDEX ix_calibration_record_is_deleted ON calibration_record(is_deleted)"))
    db.session.execute(text("CREATE INDEX ix_calibration_record_next_calibration_date ON calibration_record(next_calibration_date)"))
    db.session.execute(text("CREATE INDEX ix_calibration_record_result_status ON calibration_record(result_status)"))
    db.session.execute(text("CREATE INDEX ix_calibration_record_work_order_id ON calibration_record(work_order_id)"))
    db.session.execute(text("PRAGMA foreign_keys=ON"))
    db.session.commit()


def _downgrade_islem_log_table_to_legacy_schema():
    db.session.execute(text("PRAGMA foreign_keys=OFF"))
    db.session.execute(
        text(
            """
            CREATE TABLE islem_log_legacy (
                id INTEGER NOT NULL PRIMARY KEY,
                kullanici_id INTEGER,
                havalimani_id INTEGER,
                islem_tipi VARCHAR(50) NOT NULL,
                detay TEXT,
                error_code VARCHAR(32),
                title VARCHAR(180),
                user_message VARCHAR(255),
                owner_message TEXT,
                module VARCHAR(24),
                severity VARCHAR(20),
                exception_type VARCHAR(120),
                exception_message TEXT,
                traceback_summary TEXT,
                route VARCHAR(255),
                method VARCHAR(12),
                request_id VARCHAR(64),
                user_email VARCHAR(150),
                resolved BOOLEAN,
                resolution_note TEXT,
                ip_adresi VARCHAR(45),
                user_agent VARCHAR(200),
                ip_address VARCHAR(45),
                zaman DATETIME
            )
            """
        )
    )
    db.session.execute(
        text(
            """
            INSERT INTO islem_log_legacy (
                id,
                kullanici_id,
                havalimani_id,
                islem_tipi,
                detay,
                error_code,
                title,
                user_message,
                owner_message,
                module,
                severity,
                exception_type,
                exception_message,
                traceback_summary,
                route,
                method,
                request_id,
                user_email,
                resolved,
                resolution_note,
                ip_adresi,
                user_agent,
                ip_address,
                zaman
            )
            SELECT
                id,
                kullanici_id,
                havalimani_id,
                islem_tipi,
                detay,
                error_code,
                title,
                user_message,
                owner_message,
                module,
                severity,
                exception_type,
                exception_message,
                traceback_summary,
                route,
                method,
                request_id,
                user_email,
                resolved,
                resolution_note,
                ip_adresi,
                user_agent,
                ip_address,
                zaman
            FROM islem_log
            """
        )
    )
    db.session.execute(text("DROP TABLE islem_log"))
    db.session.execute(text("ALTER TABLE islem_log_legacy RENAME TO islem_log"))
    db.session.execute(text("PRAGMA foreign_keys=ON"))
    db.session.commit()


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
        assert AssetOperationalState.query.count() > 0
        assert MaintenanceInstruction.query.count() > 0
        assert PPERecord.query.count() > 0
        assert PPERecordEvent.query.count() > 0
        if table_exists("ppe_assignment_record"):
            assert PPEAssignmentRecord.query.count() > 0
        if table_exists("ppe_assignment_item"):
            assert PPEAssignmentItem.query.count() > 0
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
        assert sample_asset.operational_state is not None
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


def test_clear_demo_data_fails_with_clear_message_when_ppe_assignment_link_column_missing(app, monkeypatch):
    with app.app_context():
        original_column_exists = demo_data.column_exists

        def _fake_column_exists(table_name, column_name):
            if table_name == "ppe_record" and column_name == "ppe_assignment_id":
                return False
            return original_column_exists(table_name, column_name)

        monkeypatch.setattr(demo_data, "column_exists", _fake_column_exists)

        try:
            clear_demo_data()
            assert False, "clear_demo_data should fail when ppe_record.ppe_assignment_id is missing"
        except RuntimeError as exc:
            assert "flask db upgrade" in str(exc)


def test_clear_demo_data_removes_seeded_ppe_assignment_records(app):
    with app.app_context():
        seed_demo_data(reset=True)
        if not table_exists("ppe_assignment_record"):
            return

        assert PPEAssignmentRecord.query.count() > 0
        if table_exists("ppe_assignment_item"):
            assert PPEAssignmentItem.query.count() > 0

        result = clear_demo_data()

        assert result["deleted"] > 0
        assert PPEAssignmentRecord.query.count() == 0
        if table_exists("ppe_assignment_item"):
            assert PPEAssignmentItem.query.count() == 0


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


def test_clear_demo_data_detaches_non_seed_templates_from_demo_forms(app):
    with app.app_context():
        seed_demo_data(reset=True)

        demo_form_row = DemoSeedRecord.query.filter_by(
            seed_tag=DEMO_SEED_TAG,
            model_name="MaintenanceFormTemplate",
        ).first()
        assert demo_form_row is not None

        external_template = EquipmentTemplate(
            name="Gerçek Şablon - Demo Forma Bağlı",
            category="Harici",
            default_maintenance_form_id=demo_form_row.record_id,
            is_active=True,
        )
        db.session.add(external_template)
        db.session.commit()
        external_template_id = external_template.id

        result = clear_demo_data()
        assert result["deleted"] > 0

        persisted_template = EquipmentTemplate.query.filter_by(id=external_template_id).first()
        assert persisted_template is not None
        assert persisted_template.default_maintenance_form_id is None
        assert DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG).count() == 0


def test_clear_demo_data_recovers_legacy_calibration_record_schema(app):
    with app.app_context():
        seed_demo_data(reset=True)
        calibration_count = db.session.execute(text("SELECT COUNT(*) FROM calibration_record")).scalar() or 0
        assert calibration_count > 0

        _downgrade_calibration_record_table_to_legacy_schema()
        legacy_columns = [row[1] for row in db.session.execute(text("PRAGMA table_info(calibration_record)")).all()]
        assert "certificate_drive_file_id" not in legacy_columns
        assert "certificate_drive_folder_id" not in legacy_columns
        assert "certificate_mime_type" not in legacy_columns
        assert "certificate_size_bytes" not in legacy_columns

        result = clear_demo_data()

        assert result["deleted"] > 0
        columns_after = [row[1] for row in db.session.execute(text("PRAGMA table_info(calibration_record)")).all()]
        assert "certificate_drive_file_id" in columns_after
        assert "certificate_drive_folder_id" in columns_after
        assert "certificate_mime_type" in columns_after
        assert "certificate_size_bytes" in columns_after
        assert DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG).count() == 0


def test_clear_demo_data_recovers_legacy_islem_log_schema(app):
    with app.app_context():
        seed_demo_data(reset=True)
        log_count = db.session.execute(text("SELECT COUNT(*) FROM islem_log")).scalar() or 0
        assert log_count > 0

        _downgrade_islem_log_table_to_legacy_schema()
        legacy_columns = [row[1] for row in db.session.execute(text("PRAGMA table_info(islem_log)")).all()]
        assert "event_key" not in legacy_columns
        assert "target_model" not in legacy_columns
        assert "target_id" not in legacy_columns
        assert "outcome" not in legacy_columns

        result = clear_demo_data()

        assert result["deleted"] > 0
        columns_after = [row[1] for row in db.session.execute(text("PRAGMA table_info(islem_log)")).all()]
        assert "event_key" in columns_after
        assert "target_model" in columns_after
        assert "target_id" in columns_after
        assert "outcome" in columns_after
        assert DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG).count() == 0


def test_clear_demo_data_deletes_demo_airport_boxes_without_nulling_fk(app):
    with app.app_context():
        seed_demo_data(reset=True)

        demo_airport_row = DemoSeedRecord.query.filter_by(
            seed_tag=DEMO_SEED_TAG,
            model_name="Havalimani",
        ).first()
        assert demo_airport_row is not None

        real_airport = Havalimani(ad="Kalıcı Havalimanı", kodu="RCL")
        db.session.add(real_airport)
        db.session.flush()

        real_box = Kutu(kodu="RCL-SAR-01", marka="Pelican", havalimani_id=real_airport.id)
        db.session.add(real_box)

        dependent_box = Kutu(
            kodu="DMO-EXT-01",
            marka="Zarges",
            havalimani_id=demo_airport_row.record_id,
        )
        db.session.add(dependent_box)
        db.session.commit()
        dependent_box_id = dependent_box.id
        real_box_id = real_box.id

        result = clear_demo_data()
        assert result["deleted"] > 0
        assert Kutu.query.filter_by(id=dependent_box_id).first() is None
        assert Kutu.query.filter_by(id=real_box_id).first() is not None
        assert Havalimani.query.filter_by(id=real_airport.id).first() is not None


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


def test_demo_clear_endpoint_requires_exact_confirm(client, app):
    with app.app_context():
        owner = KullaniciFactory(
            rol="sahip",
            is_deleted=False,
            tam_ad="Demo Owner Confirm",
            kullanici_adi="demo.owner.confirm@sarx.local",
        )
        db.session.add(owner)
        seed_demo_data(reset=True)
        expected_seed_rows = DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG).count()
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)

    response = client.post(
        "/demo-veri/temizle",
        data={"confirm_demo_clear": "DEMO-SL"},
        follow_redirects=True,
    )
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Demo veri temizliği için onay alanına DEMO-SIL yazmalısınız." in html
    with app.app_context():
        assert DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG).count() == expected_seed_rows


def test_demo_clear_endpoint_shows_partial_status_when_homepage_clear_fails(client, app, monkeypatch):
    with app.app_context():
        owner = KullaniciFactory(
            rol="sahip",
            is_deleted=False,
            tam_ad="Demo Owner Partial",
            kullanici_adi="demo.owner.partial@sarx.local",
        )
        db.session.add(owner)
        db.session.commit()
        owner_id = owner.id
        seed_demo_data(reset=True)

    def _raise_runtime_error():
        raise RuntimeError("Anasayfa demo temizleme kilidi acik degil.")

    monkeypatch.setattr(homepage_demo, "clear_homepage_demo_data", _raise_runtime_error)
    _login(client, owner_id)

    response = client.post(
        "/demo-veri/temizle",
        data={"confirm_demo_clear": "DEMO-SIL"},
        follow_redirects=True,
    )
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Demo temizliği kısmi tamamlandı:" in html
    assert "Anasayfa demo temizleme kilidi acik degil." in html
    assert "Demo verileri temizlendi." not in html
    with app.app_context():
        assert DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG).count() == 0


def test_clear_demo_data_reports_tracking_desync_without_false_success(app):
    with app.app_context():
        seed_demo_data(reset=True)
        assert DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG).count() > 0
        DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG).delete(synchronize_session=False)
        db.session.commit()
        remaining_airports = Havalimani.query.count()

        result = clear_demo_data()

        assert result["deleted"] == 0
        assert result["partial_success"] is True
        assert any("demo iz kayıtları bulunamadı" in warning.lower() for warning in result["warnings"])
        assert Havalimani.query.count() == remaining_airports


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


def test_seed_demo_data_is_blocked_in_production_env(app):
    app.config["DEMO_TOOLS_ENABLED"] = True
    app.config["ENV"] = "production"

    with app.app_context():
        with pytest.raises(RuntimeError, match="kapalı"):
            seed_demo_data(reset=True)


def test_demo_endpoints_are_blocked_in_production_even_if_flag_enabled(client, app):
    app.config["DEMO_TOOLS_ENABLED"] = True
    app.config["ENV"] = "production"

    with app.app_context():
        owner = KullaniciFactory(
            rol="sahip",
            is_deleted=False,
            tam_ad="Prod Demo Block Owner",
            kullanici_adi="prod.demo.block@sarx.local",
        )
        db.session.add(owner)
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)

    seed_response = client.post(
        "/demo-veri/olustur",
        data={"confirm_demo_seed": "DEMO", "demo_reset": "1"},
        follow_redirects=False,
    )
    clear_response = client.post(
        "/demo-veri/temizle",
        data={"confirm_demo_clear": "DEMO-SIL"},
        follow_redirects=False,
    )

    assert seed_response.status_code == 404
    assert clear_response.status_code == 404
