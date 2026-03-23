import io

from extensions import db
from models import TatbikatBelgesi
from tests.factories import HavalimaniFactory, KullaniciFactory


def _login(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


class _FakeDriveService:
    def __init__(self):
        self.deleted_ids = []
        self.exchanged_codes = []

    def upload_file(self, airport, upload, filename, mime_type):
        return {
            "drive_file_id": f"drive-{airport.id}",
            "drive_folder_id": f"folder-{airport.id}",
            "mime_type": mime_type,
            "file_size": 2048,
            "filename": filename,
        }

    def download_file(self, drive_file_id):
        return {
            "content": b"%PDF-1.4\nfake\n",
            "mime_type": "application/pdf",
            "filename": f"{drive_file_id}.pdf",
            "size": 12,
        }

    def delete_file(self, drive_file_id):
        self.deleted_ids.append(drive_file_id)
        return True

    def exchange_authorization_code(self, code):
        self.exchanged_codes.append(code)
        return {
            "access_token": "token",
            "refresh_token": "refresh-token",
        }


def test_tatbikat_listesi_scopes_documents_to_current_airport(client, app):
    with app.app_context():
        airport_a = HavalimaniFactory(ad="Erzurum", kodu="ERZ")
        airport_b = HavalimaniFactory(ad="Trabzon", kodu="TZX")
        manager = KullaniciFactory(rol="yetkili", havalimani=airport_a, is_deleted=False)
        uploader = KullaniciFactory(rol="sahip", havalimani=airport_a, is_deleted=False)
        db.session.add_all([airport_a, airport_b, manager, uploader])
        db.session.flush()
        db.session.add_all(
            [
                TatbikatBelgesi(
                    havalimani_id=airport_a.id,
                    yukleyen_kullanici_id=uploader.id,
                    baslik="ERZ Tatbikat Planı",
                    aciklama="Yerel kayıt",
                    dosya_adi="erz-plan.pdf",
                    drive_file_id="drive-erz",
                    drive_folder_id="folder-erz",
                    mime_type="application/pdf",
                    dosya_boyutu=1024,
                ),
                TatbikatBelgesi(
                    havalimani_id=airport_b.id,
                    yukleyen_kullanici_id=uploader.id,
                    baslik="TZX Tatbikat Planı",
                    aciklama="Diğer havalimanı",
                    dosya_adi="tzx-plan.pdf",
                    drive_file_id="drive-tzx",
                    drive_folder_id="folder-tzx",
                    mime_type="application/pdf",
                    dosya_boyutu=1024,
                ),
            ]
        )
        db.session.commit()
        manager_id = manager.id

    _login(client, manager_id)
    response = client.get("/tatbikatlar")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "ERZ Tatbikat Planı" in html
    assert "TZX Tatbikat Planı" not in html


def test_personnel_cannot_upload_tatbikat_document(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Ankara", kodu="ESB")
        user = KullaniciFactory(rol="personel", havalimani=airport, is_deleted=False)
        db.session.add_all([airport, user])
        db.session.commit()
        user_id = user.id
        airport_id = airport.id

    _login(client, user_id)
    response = client.post(
        "/tatbikatlar/yukle",
        data={
            "airport_id": airport_id,
            "title": "Yetkisiz Yükleme",
            "document": (io.BytesIO(b"%PDF-1.4\nfake\n"), "plan.pdf"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 403


def test_airport_manager_can_upload_tatbikat_document_with_drive_metadata(client, app, monkeypatch):
    fake_drive = _FakeDriveService()
    monkeypatch.setattr("routes.inventory.get_drill_drive_service", lambda: fake_drive)

    with app.app_context():
        airport = HavalimaniFactory(ad="İzmir", kodu="ADB")
        manager = KullaniciFactory(rol="yetkili", havalimani=airport, is_deleted=False)
        db.session.add_all([airport, manager])
        db.session.commit()
        manager_id = manager.id
        airport_id = airport.id

    _login(client, manager_id)
    response = client.post(
        "/tatbikatlar/yukle",
        data={
            "airport_id": airport_id,
            "title": "Yıllık Tatbikat",
            "description": "Google Drive üzerinde tutulur.",
            "document": (io.BytesIO(b"%PDF-1.4\nfake\n"), "tatbikat.pdf"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "Yıllık Tatbikat" in response.data.decode("utf-8")
    with app.app_context():
        record = TatbikatBelgesi.query.filter_by(baslik="Yıllık Tatbikat", is_deleted=False).first()
        assert record is not None
        assert record.drive_file_id == f"drive-{airport_id}"
        assert record.drive_folder_id == f"folder-{airport_id}"


def test_cross_airport_tatbikat_detail_returns_403(client, app):
    with app.app_context():
        airport_a = HavalimaniFactory(ad="Dalaman", kodu="DLM")
        airport_b = HavalimaniFactory(ad="Antalya", kodu="AYT")
        viewer = KullaniciFactory(rol="personel", havalimani=airport_a, is_deleted=False)
        uploader = KullaniciFactory(rol="sahip", havalimani=airport_b, is_deleted=False)
        db.session.add_all([airport_a, airport_b, viewer, uploader])
        db.session.flush()
        document = TatbikatBelgesi(
            havalimani_id=airport_b.id,
            yukleyen_kullanici_id=uploader.id,
            baslik="AYT Belgesi",
            dosya_adi="ayt.pdf",
            drive_file_id="drive-ayt",
            drive_folder_id="folder-ayt",
            mime_type="application/pdf",
            dosya_boyutu=512,
        )
        db.session.add(document)
        db.session.commit()
        viewer_id = viewer.id
        document_id = document.id

    _login(client, viewer_id)
    response = client.get(f"/tatbikatlar/{document_id}")
    assert response.status_code == 403


def test_owner_can_soft_delete_tatbikat_document(client, app, monkeypatch):
    fake_drive = _FakeDriveService()
    monkeypatch.setattr("routes.inventory.get_drill_drive_service", lambda: fake_drive)

    with app.app_context():
        airport = HavalimaniFactory(ad="Muğla", kodu="MGL")
        owner = KullaniciFactory(rol="sahip", havalimani=airport, is_deleted=False)
        uploader = KullaniciFactory(rol="yetkili", havalimani=airport, is_deleted=False)
        db.session.add_all([airport, owner, uploader])
        db.session.flush()
        document = TatbikatBelgesi(
            havalimani_id=airport.id,
            yukleyen_kullanici_id=uploader.id,
            baslik="Silinecek Belge",
            dosya_adi="silinecek.pdf",
            drive_file_id="drive-delete",
            drive_folder_id="folder-delete",
            mime_type="application/pdf",
            dosya_boyutu=1024,
        )
        db.session.add(document)
        db.session.commit()
        owner_id = owner.id
        document_id = document.id

    _login(client, owner_id)
    response = client.post(f"/tatbikatlar/{document_id}/sil", follow_redirects=True)
    assert response.status_code == 200
    assert "Tatbikat belgesi kaldırıldı." in response.data.decode("utf-8")
    with app.app_context():
        record = db.session.get(TatbikatBelgesi, document_id)
        assert record.is_deleted is True
        assert fake_drive.deleted_ids == ["drive-delete"]


def test_google_drive_oauth_callback_matches_expected_route_and_redirects_owner(client, app, monkeypatch):
    fake_drive = _FakeDriveService()
    monkeypatch.setattr("routes.inventory.get_drill_drive_service", lambda: fake_drive)

    with app.app_context():
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-drive-callback@sarx.com")
        db.session.add(owner)
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    response = client.get("/google-drive/oauth/callback?code=test-auth-code", follow_redirects=True)
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert fake_drive.exchanged_codes == ["test-auth-code"]
    assert "Google Drive yetkilendirmesi başarıyla alındı." in html
    assert "/site-yonetimi" in response.request.path


def test_google_drive_oauth_callback_handles_error_without_404(client, app):
    response = client.get("/google-drive/oauth/callback?error=access_denied", follow_redirects=False)

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
