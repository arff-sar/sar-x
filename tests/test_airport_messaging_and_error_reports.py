import re
from datetime import timedelta

from extensions import db
from models import AirportMessage, ErrorReport, IslemLog, IslemLogArchive, get_tr_now
from tests.factories import HavalimaniFactory, KullaniciFactory


def _login(client, user_id):
    with client.session_transaction() as session:
        session.clear()
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_personnel_only_sees_own_airport_messages_and_can_delete_own_message(client, app):
    with app.app_context():
        airport_one = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        airport_two = HavalimaniFactory(ad="Trabzon Havalimanı", kodu="TZX")
        user_one = KullaniciFactory(rol="personel", is_deleted=False, kullanici_adi="erz-msg@sarx.com", havalimani=airport_one)
        user_two = KullaniciFactory(rol="personel", is_deleted=False, kullanici_adi="tzx-msg@sarx.com", havalimani=airport_two)
        db.session.add_all([airport_one, airport_two, user_one, user_two])
        db.session.flush()
        own_message = AirportMessage(havalimani_id=airport_one.id, user_id=user_one.id, message_text="ERZ vardiya notu")
        other_message = AirportMessage(havalimani_id=airport_two.id, user_id=user_two.id, message_text="TZX vardiya notu")
        db.session.add_all([own_message, other_message])
        db.session.commit()
        user_one_id = user_one.id
        own_message_id = own_message.id
        other_message_id = other_message.id

    _login(client, user_one_id)
    listing = client.get("/api/mesajlar")
    payload = listing.get_json()

    assert listing.status_code == 200
    assert payload["status"] == "success"
    assert len(payload["messages"]) == 1
    assert payload["messages"][0]["text"] == "ERZ vardiya notu"

    create_response = client.post("/api/mesajlar", json={"message_text": "Yeni ERZ notu"})
    assert create_response.status_code == 200

    with app.app_context():
        assert AirportMessage.query.filter_by(user_id=user_one_id, message_text="Yeni ERZ notu").count() == 1

    delete_response = client.post(f"/api/mesajlar/{own_message_id}/sil")
    assert delete_response.status_code == 200

    forbidden_scope_response = client.post(f"/api/mesajlar/{other_message_id}/sil")
    assert forbidden_scope_response.status_code == 404


def test_owner_can_view_all_messages_team_lead_can_bulk_delete_only_own_airport(client, app):
    with app.app_context():
        airport_one = HavalimaniFactory(ad="Ankara Havalimanı", kodu="ESB")
        airport_two = HavalimaniFactory(ad="Adana Havalimanı", kodu="ADA")
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-msg@sarx.com")
        team_lead = KullaniciFactory(rol="yetkili", is_deleted=False, kullanici_adi="lead-msg@sarx.com", havalimani=airport_one)
        member_one = KullaniciFactory(rol="personel", is_deleted=False, kullanici_adi="member-one@sarx.com", havalimani=airport_one)
        member_two = KullaniciFactory(rol="personel", is_deleted=False, kullanici_adi="member-two@sarx.com", havalimani=airport_two)
        db.session.add_all([airport_one, airport_two, owner, team_lead, member_one, member_two])
        db.session.flush()
        db.session.add_all(
            [
                AirportMessage(havalimani_id=airport_one.id, user_id=member_one.id, message_text="ESB-1"),
                AirportMessage(havalimani_id=airport_one.id, user_id=member_one.id, message_text="ESB-2"),
                AirportMessage(havalimani_id=airport_two.id, user_id=member_two.id, message_text="ADA-1"),
            ]
        )
        db.session.commit()
        owner_id = owner.id
        team_lead_id = team_lead.id
        airport_one_id = airport_one.id

    _login(client, owner_id)
    owner_listing = client.get("/api/mesajlar")
    owner_payload = owner_listing.get_json()

    assert owner_listing.status_code == 200
    assert len(owner_payload["messages"]) == 3

    _login(client, team_lead_id)
    bulk_delete = client.post("/api/mesajlar/toplu-sil", json={"airport_id": airport_one_id})
    assert bulk_delete.status_code == 200
    assert bulk_delete.get_json()["deleted_count"] == 2

    with app.app_context():
        remaining = AirportMessage.query.order_by(AirportMessage.id.asc()).all()
        assert [row.message_text for row in remaining] == ["ADA-1"]


def test_expired_airport_messages_are_pruned_without_archive(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Samsun Havalimanı", kodu="SZF")
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-prune@sarx.com", havalimani=airport)
        db.session.add_all([airport, owner])
        db.session.flush()
        expired = AirportMessage(
            havalimani_id=airport.id,
            user_id=owner.id,
            message_text="Eski mesaj",
            created_at=get_tr_now().replace(tzinfo=None) - timedelta(days=8),
        )
        active = AirportMessage(havalimani_id=airport.id, user_id=owner.id, message_text="Güncel mesaj")
        db.session.add_all([expired, active])
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    response = client.get("/api/mesajlar")
    payload = response.get_json()

    assert response.status_code == 200
    assert [item["text"] for item in payload["messages"]] == ["Güncel mesaj"]

    with app.app_context():
        assert AirportMessage.query.filter_by(message_text="Eski mesaj").count() == 0
        assert IslemLogArchive.query.count() == 0


def test_error_report_is_created_manually_from_error_screen(client, app):
    app.config["WTF_CSRF_ENABLED"] = False

    def boom():
        raise RuntimeError("kabarcik")

    app.add_url_rule("/__manual-error", "manual_error", boom)

    with app.app_context():
        airport = HavalimaniFactory(ad="Balıkesir Havalimanı", kodu="BZI")
        reporter = KullaniciFactory(rol="personel", is_deleted=False, kullanici_adi="reporter@sarx.com", havalimani=airport)
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-reports@sarx.com", havalimani=airport)
        db.session.add_all([airport, reporter, owner])
        db.session.commit()
        reporter_id = reporter.id
        airport_id = airport.id

    _login(client, reporter_id)
    error_page = client.get("/__manual-error")
    error_html = error_page.data.decode("utf-8")

    assert error_page.status_code == 500
    assert "Sistem yöneticisine bildir" in error_html
    error_code = re.search(r'name="error_code" value="([^"]+)"', error_html).group(1)
    request_id = re.search(r'name="request_id" value="([^"]*)"', error_html).group(1)
    report_path = re.search(r'name="path" value="([^"]+)"', error_html).group(1)

    create_report = client.post(
        "/hata-bildir",
        data={"error_code": error_code, "path": report_path, "request_id": request_id},
        follow_redirects=True,
    )
    assert create_report.status_code == 200

    with app.app_context():
        assert ErrorReport.query.count() == 1
        for index in range(22):
            db.session.add(
                ErrorReport(
                    user_id=reporter_id,
                    havalimani_id=airport_id,
                    role_key="ekip_uyesi",
                    path=f"/error/{index}",
                    error_code="SAR-X-SYSTEM-5101",
                    request_id=f"REQ-{index}",
                    error_summary=f"Bildirim {index}",
                )
            )
        db.session.commit()
        assert ErrorReport.query.count() == 23


def test_error_report_cannot_be_created_without_error_screen_context(client, app):
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        airport = HavalimaniFactory(ad="Dalaman Havalimanı", kodu="DLM")
        reporter = KullaniciFactory(rol="personel", is_deleted=False, kullanici_adi="no-context@sarx.com", havalimani=airport)
        db.session.add_all([airport, reporter])
        db.session.commit()
        reporter_id = reporter.id

    _login(client, reporter_id)
    create_report = client.post(
        "/hata-bildir",
        data={"error_code": "SAR-X-SYSTEM-5101", "path": "/sahte-hata", "request_id": "req-forged"},
        follow_redirects=True,
    )

    assert create_report.status_code == 200

    with app.app_context():
        assert ErrorReport.query.count() == 0


def test_owner_can_archive_and_delete_audit_and_error_logs(client, app):
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        airport = HavalimaniFactory(ad="Erzincan Havalimanı", kodu="ERC")
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-archive@sarx.com", havalimani=airport)
        db.session.add_all([airport, owner])
        db.session.flush()
        audit_log_ids = []
        error_log_ids = []
        for index in range(2):
            audit_log = IslemLog(
                kullanici_id=owner.id,
                havalimani_id=airport.id,
                islem_tipi="Envanter",
                detay=f"Audit kayıt {index}",
                outcome="success",
            )
            error_log = IslemLog(
                kullanici_id=owner.id,
                havalimani_id=airport.id,
                islem_tipi="Sistem",
                detay=f"Error kayıt {index}",
                outcome="failed",
                error_code="SAR-X-SYSTEM-5101",
                title="Beklenmeyen Sunucu Hatası",
                user_message="İşlem tamamlanamadı.",
            )
            db.session.add_all([audit_log, error_log])
            db.session.flush()
            audit_log_ids.append(audit_log.id)
            error_log_ids.append(error_log.id)
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    audit_cleanup = client.post(
        "/islem-loglari/arsivle-temizle",
        data={"cleanup_confirmation": "ONAYLA"},
        follow_redirects=True,
    )
    assert audit_cleanup.status_code == 200

    error_cleanup = client.post(
        "/hata-kayitlari/arsivle-temizle",
        data={"cleanup_confirmation": "ONAYLA"},
        follow_redirects=True,
    )
    assert error_cleanup.status_code == 200

    with app.app_context():
        archived_audit = IslemLogArchive.query.filter_by(archive_scope="audit").all()
        archived_error = IslemLogArchive.query.filter_by(archive_scope="error").all()
        assert len(archived_audit) == 2
        assert len(archived_error) == 2
        assert IslemLog.query.filter(IslemLog.id.in_(audit_log_ids)).count() == 0
        assert IslemLog.query.filter(IslemLog.id.in_(error_log_ids)).count() == 0
