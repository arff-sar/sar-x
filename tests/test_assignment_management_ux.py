import io
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from pypdf import PdfReader

from extensions import db
from models import AssignmentItem, AssignmentRecipient, AssignmentRecord
from tests.factories import (
    AssignmentRecordFactory,
    HavalimaniFactory,
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


def test_zimmet_filter_by_recipient_limits_assignments_and_updates_summary(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        box = KutuFactory(kodu="K-ERZ-1", havalimani=airport)
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-zimmet@sarx.com")
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
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-panel@sarx.com")
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
    assert "Bakım Sorumlusu" in html
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
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-checked@sarx.com")
        recipient = KullaniciFactory(
            rol="personel",
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
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-self@sarx.com")
        recipient = KullaniciFactory(
            rol="personel",
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
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-multi@sarx.com", havalimani=airport)
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


def test_zimmet_pdf_renders_turkish_text_and_core_fields(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="İzmir Çiğli Havalimanı", kodu="IGL")
        box = KutuFactory(kodu="K-IGL-1", havalimani=airport)
        owner = KullaniciFactory(rol="sahip", is_deleted=False, tam_ad="Çağrı Göğüş", kullanici_adi="owner-pdf@sarx.com")
        recipient = KullaniciFactory(
            rol="personel",
            is_deleted=False,
            tam_ad="Şule Işık",
            kullanici_adi="sule@sarx.com",
            havalimani=airport,
        )
        material = MalzemeFactory(ad="Göğüs Ölçer", seri_no="CIG-ŞĞ-01", stok_miktari=2, kutu=box, havalimani=airport)
        db.session.add_all([airport, box, owner, recipient, material])
        db.session.flush()
        assignment = _build_assignment(
            assignment_no="ZMT-TR-001",
            airport=airport,
            delivered_by=owner,
            recipient=recipient,
            material=material,
        )
        assignment.note = "Çıkış öncesi ölçüm ve şarj kontrolü yapılmıştır."
        db.session.commit()
        owner_id = owner.id
        assignment_id = assignment.id

    _login(client, owner_id)
    response = client.get(f"/zimmetler/{assignment_id}/pdf")

    assert response.status_code == 200
    assert response.mimetype == "application/pdf"

    reader = PdfReader(io.BytesIO(response.data))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)

    assert "Zimmet Formu" in text
    assert "ZMT-TR-001" in text
    assert "İzmir Çiğli Havalimanı" in text
    assert "Çağrı Göğüş" in text
    assert "Şule Işık" in text
    assert "Göğüs Ölçer" in text
    assert "Çıkış öncesi ölçüm ve şarj kontrolü yapılmıştır." in text


def test_signed_assignment_document_upload_flow_stays_working(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Antalya Havalimanı", kodu="AYT")
        box = KutuFactory(kodu="K-AYT-1", havalimani=airport)
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-upload@sarx.com")
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
            storage_key="assignments/zmt-up-001.pdf",
            public_url="https://example.com/uploads/assignments/zmt-up-001.pdf",
        )
        response = client.post(
            f"/zimmetler/{assignment_id}/signed-document",
            data={
                "signed_document": (io.BytesIO(b"%PDF-1.4 test belge"), "zimmet-imzali.pdf"),
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )

    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "İmzalı zimmet belgesi yüklendi." in html

    with app.app_context():
        from models import AssignmentRecord

        stored = db.session.get(AssignmentRecord, assignment_id)
        assert stored.signed_document_key == "assignments/zmt-up-001.pdf"
        assert stored.signed_document_url == "https://example.com/uploads/assignments/zmt-up-001.pdf"
        assert stored.signed_document_name == "zimmet-imzali.pdf"


def test_signed_assignment_document_upload_rejects_invalid_signature(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Dalaman Havalimanı", kodu="DLM")
        box = KutuFactory(kodu="K-DLM-1", havalimani=airport)
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-invalid-upload@sarx.com")
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
