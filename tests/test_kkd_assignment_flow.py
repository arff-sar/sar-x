import io
import re
from pathlib import Path

from extensions import db
from models import AssignmentRecord, PPEAssignmentItem, PPEAssignmentRecord, PPERecord
from routes.inventory import _ppe_assignment_display_name
from tests.factories import HavalimaniFactory, KullaniciFactory


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


def _assert_all_personnel_accordions_closed_in_rendered_html(html):
    tags = re.findall(r'<details class="ppe-user-accordion"[^>]*>', html)
    assert tags
    assert all(" open" not in tag and "open=" not in tag for tag in tags)


def _assert_all_personnel_accordion_bodies_hidden_in_rendered_html(html):
    tags = re.findall(r'<div class="ppe-user-body"[^>]*>', html)
    assert tags
    assert all("hidden" in tag for tag in tags)


def _assert_all_create_accordions_closed_in_rendered_html(html):
    tags = re.findall(r'<details class="ppe-create-item"[^>]*>', html)
    assert tags
    assert all(" open" not in tag and "open=" not in tag for tag in tags)


def test_kkd_page_shows_separate_add_and_assignment_accordions(client, app):
    with app.app_context():
        airport = HavalimaniFactory(kodu="AYT", ad="Antalya Havalimanı")
        owner = KullaniciFactory(rol="sistem_sorumlusu", havalimani=airport, is_deleted=False, kullanici_adi="kkd-ux-owner@sarx.com")
        recipient = KullaniciFactory(rol="personel", havalimani=airport, is_deleted=False, tam_ad="KKD Personeli")
        db.session.add_all([airport, owner, recipient])
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    response = client.get("/kkd")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Yeni KKD Ekle" in html
    assert "Yeni KKD Tahsisi" in html
    assert "PDF Rapor" in html
    _assert_all_create_accordions_closed_in_rendered_html(html)


def test_kkd_page_redirects_without_503_when_schema_link_column_missing(client, app, monkeypatch):
    with app.app_context():
        airport = HavalimaniFactory(kodu="TZX", ad="Test Havalimanı")
        owner = KullaniciFactory(rol="sistem_sorumlusu", havalimani=airport, is_deleted=False, kullanici_adi="kkd-drift-owner@sarx.com")
        db.session.add_all([airport, owner])
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    monkeypatch.setattr("routes.inventory.column_exists", lambda table_name, column_name: not (table_name == "ppe_record" and column_name == "ppe_assignment_id"))
    response = client.get("/kkd", follow_redirects=False)

    assert response.status_code == 302
    assert "/envanter" in (response.headers.get("Location") or "")


def test_kkd_page_personnel_flow_renders_accordion_structure(client, app):
    with app.app_context():
        airport = HavalimaniFactory(kodu="SAW", ad="Sabiha Gökçen")
        owner = KullaniciFactory(rol="sistem_sorumlusu", havalimani=airport, is_deleted=False, kullanici_adi="kkd-accordion-owner@sarx.com")
        staff = KullaniciFactory(rol="personel", havalimani=airport, is_deleted=False, tam_ad="Akış Personeli")
        db.session.add_all([airport, owner, staff])
        db.session.flush()
        db.session.add(
            PPERecord(
                user_id=staff.id,
                airport_id=airport.id,
                category="Baş ve Yüz Koruması",
                subcategory="Baret",
                item_name="Akordiyon Test Bareti",
                quantity=1,
                status="aktif",
                physical_condition="iyi",
                is_active=True,
                created_by_id=owner.id,
            )
        )
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    response = client.get("/kkd")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert '<details class="ppe-user-accordion"' in html
    assert "toggleUserAccordion" in html
    assert 'data-user-id="' in html


def test_kkd_personnel_flow_defaults_closed_without_selected_user(client, app):
    with app.app_context():
        airport = HavalimaniFactory(kodu="HTY", ad="Hatay")
        owner = KullaniciFactory(rol="sistem_sorumlusu", havalimani=airport, is_deleted=False, kullanici_adi="kkd-default-closed-owner@sarx.com")
        staff = KullaniciFactory(rol="personel", havalimani=airport, is_deleted=False, tam_ad="Kapalı Varsayılan Personel")
        db.session.add_all([airport, owner, staff])
        db.session.flush()
        db.session.add(
            PPERecord(
                user_id=staff.id,
                airport_id=airport.id,
                category="Baş ve Yüz Koruması",
                subcategory="Baret",
                item_name="Kapalı Varsayılan Baret",
                quantity=1,
                status="aktif",
                physical_condition="iyi",
                is_active=True,
                created_by_id=owner.id,
            )
        )
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    response = client.get("/kkd")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "data-selected-user-id=" not in html
    assert '<details class="ppe-user-accordion" data-user-id="' in html
    _assert_all_personnel_accordions_closed_in_rendered_html(html)
    _assert_all_personnel_accordion_bodies_hidden_in_rendered_html(html)


def test_kkd_personnel_flow_defaults_closed_with_selected_user(client, app):
    with app.app_context():
        airport = HavalimaniFactory(kodu="ESB", ad="Esenboğa")
        owner = KullaniciFactory(rol="sistem_sorumlusu", havalimani=airport, is_deleted=False, kullanici_adi="kkd-selected-closed-owner@sarx.com")
        staff = KullaniciFactory(rol="personel", havalimani=airport, is_deleted=False, tam_ad="Seçili Kapalı Personel")
        db.session.add_all([airport, owner, staff])
        db.session.flush()
        db.session.add(
            PPERecord(
                user_id=staff.id,
                airport_id=airport.id,
                category="Baş ve Yüz Koruması",
                subcategory="Baret",
                item_name="Seçili Personel Bareti",
                quantity=1,
                status="aktif",
                physical_condition="iyi",
                is_active=True,
                created_by_id=owner.id,
            )
        )
        db.session.commit()
        owner_id = owner.id
        staff_id = staff.id

    _login(client, owner_id)
    response = client.get(f"/kkd?user_id={staff_id}")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "data-selected-user-id=" not in html
    assert '<details class="ppe-user-accordion" data-user-id="' in html
    _assert_all_personnel_accordions_closed_in_rendered_html(html)
    _assert_all_personnel_accordion_bodies_hidden_in_rendered_html(html)


def test_kkd_personnel_flow_js_init_forces_closed_state(client, app):
    with app.app_context():
        airport = HavalimaniFactory(kodu="GZT", ad="Gaziantep")
        owner = KullaniciFactory(rol="sistem_sorumlusu", havalimani=airport, is_deleted=False, kullanici_adi="kkd-js-init-owner@sarx.com")
        staff = KullaniciFactory(rol="personel", havalimani=airport, is_deleted=False, tam_ad="JS Init Personeli")
        db.session.add_all([airport, owner, staff])
        db.session.flush()
        db.session.add(
            PPERecord(
                user_id=staff.id,
                airport_id=airport.id,
                category="Baş ve Yüz Koruması",
                subcategory="Baret",
                item_name="JS Init Baret",
                quantity=1,
                status="aktif",
                physical_condition="iyi",
                is_active=True,
                created_by_id=owner.id,
            )
        )
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    response = client.get("/kkd")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "item.removeAttribute('open');" in html
    assert "item.open = false;" in html
    assert "body.style.display = shouldOpen ? 'grid' : 'none';" in html
    assert "window.addEventListener('pageshow', initUserAccordions);" in html


def test_kkd_personnel_flow_css_hides_closed_accordion_body(client, app):
    with app.app_context():
        airport = HavalimaniFactory(kodu="VAN", ad="Van")
        owner = KullaniciFactory(rol="sistem_sorumlusu", havalimani=airport, is_deleted=False, kullanici_adi="kkd-css-closed-owner@sarx.com")
        staff = KullaniciFactory(rol="personel", havalimani=airport, is_deleted=False, tam_ad="CSS Kapalı Personel")
        db.session.add_all([airport, owner, staff])
        db.session.flush()
        db.session.add(
            PPERecord(
                user_id=staff.id,
                airport_id=airport.id,
                category="Baş ve Yüz Koruması",
                subcategory="Baret",
                item_name="CSS Kapalı Baret",
                quantity=1,
                status="aktif",
                physical_condition="iyi",
                is_active=True,
                created_by_id=owner.id,
            )
        )
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    response = client.get("/kkd")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert ".ppe-user-accordion > .ppe-user-body { display:none; }" in html
    assert ".ppe-user-accordion[open] > .ppe-user-body { display:grid; }" in html


def test_kkd_linked_assignment_options_show_only_ppe_assignments(client, app):
    with app.app_context():
        airport = HavalimaniFactory(kodu="DLM", ad="Dalaman")
        owner = KullaniciFactory(rol="sistem_sorumlusu", havalimani=airport, is_deleted=False, kullanici_adi="kkd-link-owner@sarx.com")
        recipient = KullaniciFactory(rol="personel", havalimani=airport, is_deleted=False, tam_ad="Bağlantı Personeli")
        db.session.add_all([airport, owner, recipient])
        db.session.flush()

        classic_assignment = AssignmentRecord(
            assignment_no="ASG-CLASSIC-001",
            delivered_by_id=owner.id,
            delivered_by_name=owner.tam_ad,
            airport_id=airport.id,
            status="active",
            created_by_id=owner.id,
        )
        db.session.add(classic_assignment)

        ppe_assignment = PPEAssignmentRecord(
            assignment_no="KKD-LINK-001",
            delivered_by_id=owner.id,
            delivered_by_name=owner.tam_ad,
            recipient_user_id=recipient.id,
            airport_id=airport.id,
            status="active",
            created_by_id=owner.id,
        )
        db.session.add(ppe_assignment)
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    response = client.get("/kkd")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert 'name="ppe_assignment_id"' in html
    assert 'name="assignment_id"' not in html
    assert "KKD-LINK-001" in html
    assert "ASG-CLASSIC-001" not in html


def test_kkd_add_creates_pool_record_without_user_selection(client, app):
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        airport = HavalimaniFactory(kodu="ADB", ad="İzmir Havalimanı")
        owner = KullaniciFactory(rol="sistem_sorumlusu", havalimani=airport, is_deleted=False, kullanici_adi="kkd-pool-owner@sarx.com")
        db.session.add_all([airport, owner])
        db.session.commit()
        owner_id = owner.id
        airport_id = airport.id

    _login(client, owner_id)
    response = client.post(
        "/kkd",
        data={
            "airport_id": str(airport_id),
            "category": "Baş ve Yüz Koruması",
            "subcategory": "Baret",
            "item_name": "Pool Baret",
            "quantity": "3",
            "physical_condition": "iyi",
            "is_active": "1",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "KKD kaydı oluşturuldu." in response.data.decode("utf-8")
    with app.app_context():
        created = PPERecord.query.filter_by(item_name="Pool Baret").first()
        assert created is not None
        assert created.user_id is None
        assert created.airport_id == airport_id


def test_kkd_add_links_only_to_ppe_assignment_reference(client, app):
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        airport = HavalimaniFactory(kodu="BZI", ad="Balıkesir")
        owner = KullaniciFactory(rol="sistem_sorumlusu", havalimani=airport, is_deleted=False, kullanici_adi="kkd-link-form-owner@sarx.com")
        recipient = KullaniciFactory(rol="personel", havalimani=airport, is_deleted=False, tam_ad="Bağlı KKD Personeli")
        db.session.add_all([airport, owner, recipient])
        db.session.flush()

        db.session.add(
            AssignmentRecord(
                assignment_no="ASG-FORM-LEGACY-001",
                delivered_by_id=owner.id,
                delivered_by_name=owner.tam_ad,
                airport_id=airport.id,
                status="active",
                created_by_id=owner.id,
            )
        )

        ppe_assignment = PPEAssignmentRecord(
            assignment_no="KKD-FORM-LINK-001",
            delivered_by_id=owner.id,
            delivered_by_name=owner.tam_ad,
            recipient_user_id=recipient.id,
            airport_id=airport.id,
            status="active",
            created_by_id=owner.id,
        )
        db.session.add(ppe_assignment)
        db.session.commit()
        owner_id = owner.id
        airport_id = airport.id
        ppe_assignment_id = ppe_assignment.id

    _login(client, owner_id)
    response = client.post(
        "/kkd",
        data={
            "airport_id": str(airport_id),
            "category": "Baş ve Yüz Koruması",
            "subcategory": "Baret",
            "item_name": "Bağlı Form Bareti",
            "quantity": "1",
            "physical_condition": "iyi",
            "is_active": "1",
            "ppe_assignment_id": str(ppe_assignment_id),
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    with app.app_context():
        created = PPERecord.query.filter_by(item_name="Bağlı Form Bareti").first()
        assert created is not None
        assert created.ppe_assignment_id == ppe_assignment_id
        assert created.assignment_id is None


def test_kkd_assignment_create_requires_system_or_team_lead_role(client, app):
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        airport = HavalimaniFactory(kodu="ESB", ad="Esenboğa")
        unauthorized = KullaniciFactory(rol="admin", havalimani=airport, is_deleted=False, kullanici_adi="kkd-admin@sarx.com")
        recipient = KullaniciFactory(rol="personel", havalimani=airport, is_deleted=False, tam_ad="Teslim Alan")
        db.session.add_all([airport, unauthorized, recipient])
        db.session.flush()
        ppe_record = PPERecord(
            airport_id=airport.id,
            category="Baş ve Yüz Koruması",
            subcategory="Baret",
            item_name="Yetki Test Bareti",
            quantity=2,
            status="aktif",
            physical_condition="iyi",
            is_active=True,
            created_by_id=unauthorized.id,
        )
        db.session.add(ppe_record)
        db.session.commit()
        unauthorized_id = unauthorized.id
        recipient_id = recipient.id
        record_id = ppe_record.id

    _login(client, unauthorized_id)
    response = client.post(
        "/kkd/tahsis",
        data={
            "recipient_user_id": str(recipient_id),
            "delivered_by_name": "Yetkisiz Kullanıcı",
            "ppe_record_ids": [str(record_id)],
            f"ppe_qty_{record_id}": "1",
            f"ppe_unit_{record_id}": "adet",
        },
        follow_redirects=False,
    )

    assert response.status_code == 403


def test_kkd_assignment_create_flow_creates_record_and_item(client, app):
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        airport = HavalimaniFactory(kodu="ADA", ad="Adana")
        owner = KullaniciFactory(rol="sistem_sorumlusu", havalimani=airport, is_deleted=False, kullanici_adi="kkd-assign-owner@sarx.com")
        recipient = KullaniciFactory(rol="personel", havalimani=airport, is_deleted=False, tam_ad="Teslim Personeli")
        db.session.add_all([airport, owner, recipient])
        db.session.flush()
        ppe_record = PPERecord(
            airport_id=airport.id,
            category="Ayak Koruması",
            subcategory="Çizme",
            item_name="Tahsis Çizmesi",
            quantity=4,
            status="aktif",
            physical_condition="iyi",
            is_active=True,
            created_by_id=owner.id,
        )
        db.session.add(ppe_record)
        db.session.commit()
        owner_id = owner.id
        recipient_id = recipient.id
        record_id = ppe_record.id

    _login(client, owner_id)
    response = client.post(
        "/kkd/tahsis",
        data={
            "recipient_user_id": str(recipient_id),
            "delivered_by_name": "Nöbetçi Amir",
            "assignment_date": "2026-04-02",
            "note": "KKD tahsis akış testi",
            "ppe_record_ids": [str(record_id)],
            f"ppe_qty_{record_id}": "2",
            f"ppe_unit_{record_id}": "adet",
            f"ppe_note_{record_id}": "Kritik vardiya",
        },
        follow_redirects=True,
    )
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "KKD tahsisi oluşturuldu." in html
    assert "KKD teslim formu PDF olarak otomatik indiriliyor." in html
    with app.app_context():
        assignment = PPEAssignmentRecord.query.order_by(PPEAssignmentRecord.id.desc()).first()
        assert assignment is not None
        assert assignment.delivered_by_name == "Nöbetçi Amir"
        assert assignment.recipient_user_id == recipient_id
        item = PPEAssignmentItem.query.filter_by(assignment_id=assignment.id).first()
        assert item is not None
        assert item.item_name == "Tahsis Çizmesi"
        assert float(item.quantity) == 2.0


def test_kkd_assignment_pdf_and_uppercase_turkish_render(client, app):
    with app.app_context():
        airport = HavalimaniFactory(kodu="GZT", ad="Gaziantep")
        owner = KullaniciFactory(rol="sistem_sorumlusu", havalimani=airport, is_deleted=False, kullanici_adi="kkd-pdf-owner@sarx.com")
        recipient = KullaniciFactory(rol="personel", havalimani=airport, is_deleted=False, tam_ad="Çağrı Işık")
        db.session.add_all([airport, owner, recipient])
        db.session.flush()
        assignment = PPEAssignmentRecord(
            assignment_no="KKD-TEST-001",
            delivered_by_id=owner.id,
            delivered_by_name="Şule Işık",
            recipient_user_id=recipient.id,
            airport_id=airport.id,
            status="active",
            created_by_id=owner.id,
        )
        db.session.add(assignment)
        db.session.flush()
        db.session.add(
            PPEAssignmentItem(
                assignment_id=assignment.id,
                item_name="Koruyucu Çizme",
                category="Ayak Koruması",
                subcategory="Çizme",
                quantity=1,
                unit="adet",
            )
        )
        db.session.commit()
        owner_id = owner.id
        assignment_id = assignment.id

    _login(client, owner_id)
    response = client.get(f"/kkd/tahsisler/{assignment_id}/pdf")

    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    assert _ppe_assignment_display_name("Çağrı Işık") == "ÇAĞRI IŞIK"
    template_text = Path("templates/kkd_tahsis_pdf.html").read_text(encoding="utf-8")
    assert "KİŞİSEL KORUYUCU DONANIM TESLİM FORMU" in template_text
    assert "AssignmentPdfSans" in template_text


def test_kkd_report_pdf_uses_corporate_template_and_font_face(client, app):
    with app.app_context():
        airport = HavalimaniFactory(kodu="BJV", ad="Bodrum")
        owner = KullaniciFactory(rol="sistem_sorumlusu", havalimani=airport, is_deleted=False, kullanici_adi="kkd-report-owner@sarx.com")
        recipient = KullaniciFactory(rol="personel", havalimani=airport, is_deleted=False, tam_ad="Rapor Personeli")
        db.session.add_all([airport, owner, recipient])
        db.session.flush()
        db.session.add(
            PPERecord(
                user_id=recipient.id,
                airport_id=airport.id,
                category="Baş ve Yüz Koruması",
                subcategory="Baret",
                item_name="Kurumsal Baret",
                quantity=1,
                status="aktif",
                physical_condition="iyi",
                is_active=True,
                created_by_id=owner.id,
            )
        )
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    response = client.get("/kkd/export/pdf")

    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    template_text = Path("templates/kkd_report_pdf.html").read_text(encoding="utf-8")
    assert "SAR-X ARFF OPERASYON TAKİP SİSTEMİ" in template_text
    assert "KKD TAHSİS RAPORU" in template_text
    assert "@font-face" in template_text
    assert "AssignmentPdfSans" in template_text


def test_kkd_assignment_signed_document_upload_stores_drive_and_local_metadata(client, app, monkeypatch):
    app.config["WTF_CSRF_ENABLED"] = False

    class FakeDriveService:
        def ensure_airport_folder(self, _airport):
            return "airport-folder-1"

        def _find_folder(self, name, parent_folder_id):
            if name == "KKD" and parent_folder_id == "airport-folder-1":
                return "kkd-folder-1"
            return None

        def _create_folder(self, _name, _parent_folder_id):
            return "kkd-folder-1"

        def upload_file_to_folder(self, folder_id, upload, filename, mime_type):
            assert folder_id == "kkd-folder-1"
            assert mime_type == "application/pdf"
            assert filename.startswith("kkd_")
            return {
                "drive_file_id": "drive-file-1",
                "drive_folder_id": folder_id,
                "filename": filename,
                "mime_type": mime_type,
                "file_size": len(upload.read() or b""),
            }

    with app.app_context():
        airport = HavalimaniFactory(kodu="AYT", ad="Antalya")
        owner = KullaniciFactory(rol="sistem_sorumlusu", havalimani=airport, is_deleted=False, kullanici_adi="kkd-upload-owner@sarx.com")
        recipient = KullaniciFactory(rol="personel", havalimani=airport, is_deleted=False, tam_ad="Belge Alan")
        db.session.add_all([airport, owner, recipient])
        db.session.flush()
        assignment = PPEAssignmentRecord(
            assignment_no="KKD-TEST-UPLOAD-1",
            delivered_by_id=owner.id,
            delivered_by_name="Teslim Eden",
            recipient_user_id=recipient.id,
            airport_id=airport.id,
            status="active",
            created_by_id=owner.id,
        )
        db.session.add(assignment)
        db.session.commit()
        owner_id = owner.id
        assignment_id = assignment.id

    monkeypatch.setattr("routes.inventory.get_drill_drive_service", lambda: FakeDriveService())

    _login(client, owner_id)
    response = client.post(
        f"/kkd/tahsisler/{assignment_id}/signed-document",
        data={"signed_document": (io.BytesIO(b"%PDF-1.4 kkd"), "kkd-imzali.pdf", "application/pdf")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "İmzalı KKD teslim belgesi yüklendi." in html
    with app.app_context():
        stored = db.session.get(PPEAssignmentRecord, assignment_id)
        assert stored is not None
        assert stored.signed_document_key is not None
        assert "/KKD/" in stored.signed_document_key
        assert stored.signed_document_drive_file_id == "drive-file-1"
        assert stored.signed_document_drive_folder_id == "kkd-folder-1"


def test_kkd_recent_assignment_list_shows_return_and_delete_actions(client, app):
    with app.app_context():
        airport = HavalimaniFactory(kodu="MZH", ad="Amasya")
        owner = KullaniciFactory(rol="sistem_sorumlusu", havalimani=airport, is_deleted=False, kullanici_adi="kkd-actions-owner@sarx.com")
        recipient = KullaniciFactory(rol="personel", havalimani=airport, is_deleted=False, tam_ad="Aksiyon Personeli")
        db.session.add_all([airport, owner, recipient])
        db.session.flush()

        active_assignment = PPEAssignmentRecord(
            assignment_no="KKD-ACT-001",
            delivered_by_id=owner.id,
            delivered_by_name=owner.tam_ad,
            recipient_user_id=recipient.id,
            airport_id=airport.id,
            status="active",
            created_by_id=owner.id,
        )
        returned_assignment = PPEAssignmentRecord(
            assignment_no="KKD-RET-001",
            delivered_by_id=owner.id,
            delivered_by_name=owner.tam_ad,
            recipient_user_id=recipient.id,
            airport_id=airport.id,
            status="returned",
            created_by_id=owner.id,
            returned_by_id=owner.id,
        )
        db.session.add_all([active_assignment, returned_assignment])
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    response = client.get("/kkd")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "KKD-ACT-001" in html
    assert "KKD-RET-001" in html
    assert "İade Al" in html
    assert "Sil" in html


def test_kkd_assignment_return_flow_marks_record_returned_and_restores_available_quantity(client, app):
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        airport = HavalimaniFactory(kodu="IST", ad="İstanbul")
        owner = KullaniciFactory(rol="sistem_sorumlusu", havalimani=airport, is_deleted=False, kullanici_adi="kkd-return-owner@sarx.com")
        recipient = KullaniciFactory(rol="personel", havalimani=airport, is_deleted=False, tam_ad="İade Personeli")
        db.session.add_all([airport, owner, recipient])
        db.session.flush()

        ppe_record = PPERecord(
            airport_id=airport.id,
            category="Baş ve Yüz Koruması",
            subcategory="Baret",
            item_name="İade Test Bareti",
            quantity=1,
            status="aktif",
            physical_condition="iyi",
            is_active=True,
            created_by_id=owner.id,
        )
        db.session.add(ppe_record)
        db.session.flush()

        assignment = PPEAssignmentRecord(
            assignment_no="KKD-RETURN-001",
            delivered_by_id=owner.id,
            delivered_by_name=owner.tam_ad,
            recipient_user_id=recipient.id,
            airport_id=airport.id,
            status="active",
            created_by_id=owner.id,
        )
        db.session.add(assignment)
        db.session.flush()
        db.session.add(
            PPEAssignmentItem(
                assignment_id=assignment.id,
                ppe_record_id=ppe_record.id,
                item_name=ppe_record.item_name,
                category=ppe_record.category,
                subcategory=ppe_record.subcategory,
                quantity=1,
                unit="adet",
            )
        )
        db.session.commit()
        owner_id = owner.id
        assignment_id = assignment.id
        record_id = ppe_record.id

    _login(client, owner_id)
    before_html = client.get("/kkd").data.decode("utf-8")
    assert f'name="ppe_record_ids" value="{record_id}"' not in before_html

    response = client.post(
        f"/kkd/tahsisler/{assignment_id}/iade",
        data={"return_note": "Vardiya sonrası tam iade"},
        follow_redirects=True,
    )
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "KKD tahsisi iade edildi." in html
    assert "İade Edildi" in html
    with app.app_context():
        assignment = db.session.get(PPEAssignmentRecord, assignment_id)
        assert assignment is not None
        assert assignment.status == "returned"
        assert assignment.returned_at is not None
        assert assignment.returned_by_id == owner_id
        assert assignment.returned_note == "Vardiya sonrası tam iade"

    after_html = client.get("/kkd").data.decode("utf-8")
    assert f'name="ppe_record_ids" value="{record_id}"' in after_html


def test_kkd_assignment_return_requires_system_or_team_lead_role(client, app):
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        airport = HavalimaniFactory(kodu="KYA", ad="Konya")
        owner = KullaniciFactory(rol="sistem_sorumlusu", havalimani=airport, is_deleted=False, kullanici_adi="kkd-return-owner-role@sarx.com")
        unauthorized = KullaniciFactory(rol="admin", havalimani=airport, is_deleted=False, kullanici_adi="kkd-return-admin@sarx.com")
        recipient = KullaniciFactory(rol="personel", havalimani=airport, is_deleted=False, tam_ad="Yetki İade")
        db.session.add_all([airport, owner, unauthorized, recipient])
        db.session.flush()
        assignment = PPEAssignmentRecord(
            assignment_no="KKD-RETURN-ROLE-001",
            delivered_by_id=owner.id,
            delivered_by_name=owner.tam_ad,
            recipient_user_id=recipient.id,
            airport_id=airport.id,
            status="active",
            created_by_id=owner.id,
        )
        db.session.add(assignment)
        db.session.commit()
        unauthorized_id = unauthorized.id
        assignment_id = assignment.id

    _login(client, unauthorized_id)
    response = client.post(
        f"/kkd/tahsisler/{assignment_id}/iade",
        data={"return_note": "Yetkisiz iade denemesi"},
        follow_redirects=False,
    )

    assert response.status_code == 403


def test_kkd_assignment_delete_flow_archives_non_active_assignment(client, app):
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        airport = HavalimaniFactory(kodu="AYT", ad="Antalya")
        owner = KullaniciFactory(rol="sistem_sorumlusu", havalimani=airport, is_deleted=False, kullanici_adi="kkd-delete-owner@sarx.com")
        recipient = KullaniciFactory(rol="personel", havalimani=airport, is_deleted=False, tam_ad="Silme Personeli")
        db.session.add_all([airport, owner, recipient])
        db.session.flush()
        assignment = PPEAssignmentRecord(
            assignment_no="KKD-DELETE-001",
            delivered_by_id=owner.id,
            delivered_by_name=owner.tam_ad,
            recipient_user_id=recipient.id,
            airport_id=airport.id,
            status="returned",
            created_by_id=owner.id,
            returned_by_id=owner.id,
            returned_note="Silme öncesi iade edildi",
        )
        db.session.add(assignment)
        db.session.commit()
        owner_id = owner.id
        assignment_id = assignment.id

    _login(client, owner_id)
    response = client.post(f"/kkd/tahsisler/{assignment_id}/sil", follow_redirects=True)
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "KKD tahsis kaydı silindi ve arşive taşındı." in html
    with app.app_context():
        stored = db.session.get(PPEAssignmentRecord, assignment_id)
        assert stored is not None
        assert stored.is_deleted is True

    detail_response = client.get(f"/kkd/tahsisler/{assignment_id}", follow_redirects=True)
    detail_html = detail_response.data.decode("utf-8")
    assert detail_response.status_code == 200
    assert "KKD tahsis kaydı bulunamadı veya erişim izniniz yok." in detail_html

    list_html = client.get("/kkd").data.decode("utf-8")
    assert "KKD-DELETE-001" not in list_html


def test_kkd_assignment_delete_rejects_active_assignment(client, app):
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        airport = HavalimaniFactory(kodu="ADA", ad="Adana")
        owner = KullaniciFactory(rol="sistem_sorumlusu", havalimani=airport, is_deleted=False, kullanici_adi="kkd-delete-active-owner@sarx.com")
        recipient = KullaniciFactory(rol="personel", havalimani=airport, is_deleted=False, tam_ad="Aktif Silme Personeli")
        db.session.add_all([airport, owner, recipient])
        db.session.flush()
        assignment = PPEAssignmentRecord(
            assignment_no="KKD-DELETE-ACTIVE-001",
            delivered_by_id=owner.id,
            delivered_by_name=owner.tam_ad,
            recipient_user_id=recipient.id,
            airport_id=airport.id,
            status="active",
            created_by_id=owner.id,
        )
        db.session.add(assignment)
        db.session.commit()
        owner_id = owner.id
        assignment_id = assignment.id

    _login(client, owner_id)
    response = client.post(f"/kkd/tahsisler/{assignment_id}/sil", follow_redirects=True)
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Aktif KKD tahsisi silinemez. Önce iade işlemi yapın." in html
    with app.app_context():
        stored = db.session.get(PPEAssignmentRecord, assignment_id)
        assert stored is not None
        assert stored.is_deleted is False


def test_kkd_assignment_delete_requires_system_or_team_lead_role(client, app):
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        airport = HavalimaniFactory(kodu="ESB", ad="Esenboğa")
        owner = KullaniciFactory(rol="sistem_sorumlusu", havalimani=airport, is_deleted=False, kullanici_adi="kkd-delete-owner-role@sarx.com")
        unauthorized = KullaniciFactory(rol="admin", havalimani=airport, is_deleted=False, kullanici_adi="kkd-delete-admin@sarx.com")
        recipient = KullaniciFactory(rol="personel", havalimani=airport, is_deleted=False, tam_ad="Yetki Silme")
        db.session.add_all([airport, owner, unauthorized, recipient])
        db.session.flush()
        assignment = PPEAssignmentRecord(
            assignment_no="KKD-DELETE-ROLE-001",
            delivered_by_id=owner.id,
            delivered_by_name=owner.tam_ad,
            recipient_user_id=recipient.id,
            airport_id=airport.id,
            status="returned",
            created_by_id=owner.id,
        )
        db.session.add(assignment)
        db.session.commit()
        unauthorized_id = unauthorized.id
        assignment_id = assignment.id

    _login(client, unauthorized_id)
    response = client.post(f"/kkd/tahsisler/{assignment_id}/sil", follow_redirects=False)

    assert response.status_code == 403
