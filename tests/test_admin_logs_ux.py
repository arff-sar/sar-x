from extensions import db
from models import IslemLog
from tests.factories import HavalimaniFactory, KullaniciFactory


def _login(client, user_id):
    with client.session_transaction() as session:
        session.clear()
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_event_type_filter_is_selectable_and_really_filters_results(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-logs@sarx.com", havalimani=airport)
        db.session.add_all([airport, owner])
        db.session.flush()
        db.session.add_all(
            [
                IslemLog(
                    kullanici_id=owner.id,
                    islem_tipi="Giriş",
                    event_key="auth.login",
                    detay="Kullanıcı sisteme giriş yaptı.",
                    outcome="success",
                ),
                IslemLog(
                    kullanici_id=owner.id,
                    islem_tipi="Rapor",
                    event_key="reports.export.completed",
                    detay="PDF dışa aktarma tamamlandı.",
                    target_model="InventoryAsset",
                    target_id=15,
                    outcome="success",
                ),
            ]
        )
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    response = client.get("/islem-loglari?event_type=Rapor")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert 'name="event_type"' in html
    assert "Rapor ve Dışa Aktarma" in html
    assert "PDF dışa aktarma tamamlandı." in html
    assert "Kullanıcı sisteme giriş yaptı." not in html
    assert "1 kayıt" in html


def test_logs_screen_translates_outcomes_and_hides_technical_labels(client, app):
    with app.app_context():
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-logs-tr@sarx.com")
        db.session.add(owner)
        db.session.flush()
        db.session.add_all(
            [
                IslemLog(
                    kullanici_id=owner.id,
                    islem_tipi="Güvenlik",
                    event_key="auth.login",
                    detay="Başarılı giriş denemesi kaydedildi.",
                    outcome="success",
                ),
                IslemLog(
                    kullanici_id=owner.id,
                    islem_tipi="Yetki",
                    event_key="permission.matrix.update",
                    detay="Yetki matrisi güncellendi.",
                    target_model="Role",
                    target_id=3,
                    outcome="failed",
                ),
                IslemLog(
                    kullanici_id=None,
                    islem_tipi="Sistem",
                    detay="Eski yapıdan taşınan kayıt.",
                    outcome="legacy",
                ),
            ]
        )
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    response = client.get("/islem-loglari")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "İşlem Kayıtları" in html
    assert "Başarılı" in html
    assert "Başarısız" in html
    assert "Eski kayıt" in html
    assert "Event Key" not in html
    assert "Hedef Model" not in html
    assert "Success" not in html
    assert "Failed" not in html
    assert "LEGACY" not in html


def test_target_model_filter_and_empty_state_render_cleanly(client, app):
    with app.app_context():
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-logs-empty@sarx.com")
        db.session.add(owner)
        db.session.flush()
        db.session.add_all(
            [
                IslemLog(
                    kullanici_id=owner.id,
                    islem_tipi="Yetki",
                    event_key="role.assignment.change",
                    detay="Rol ataması güncellendi.",
                    target_model="Kullanici",
                    target_id=7,
                    outcome="success",
                ),
                IslemLog(
                    kullanici_id=owner.id,
                    islem_tipi="Rapor",
                    event_key="reports.export.failed",
                    detay="Dışa aktarma başarısız oldu.",
                    target_model="InventoryAsset",
                    target_id=11,
                    outcome="failed",
                ),
            ]
        )
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    filtered = client.get("/islem-loglari?target_model=Kullanici")
    filtered_html = filtered.data.decode("utf-8")

    assert filtered.status_code == 200
    assert "İlgili Kayıt Türü" in filtered_html
    assert "Kullanıcı" in filtered_html
    assert "Rol ataması güncellendi." in filtered_html
    assert "Dışa aktarma başarısız oldu." not in filtered_html

    empty = client.get("/islem-loglari?event_type=Yetki&outcome=failed")
    empty_html = empty.data.decode("utf-8")

    assert empty.status_code == 200
    assert "Kayıt bulunamadı" in empty_html
    assert "Seçili filtrelerle eşleşen işlem kaydı yok." in empty_html


def test_user_filter_renders_selected_user_without_crashing(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Samsun Havalimanı", kodu="SZF")
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-logs-user@sarx.com", havalimani=airport)
        other = KullaniciFactory(rol="personel", is_deleted=False, kullanici_adi="staff-logs-user@sarx.com", havalimani=airport)
        db.session.add_all([airport, owner, other])
        db.session.flush()
        db.session.add_all(
            [
                IslemLog(
                    kullanici_id=owner.id,
                    islem_tipi="Giriş",
                    detay="Sahip kullanıcısı sisteme giriş yaptı.",
                    outcome="success",
                ),
                IslemLog(
                    kullanici_id=other.id,
                    islem_tipi="Bakım",
                    detay="Personel bakım akışı başlattı.",
                    outcome="success",
                ),
            ]
        )
        db.session.commit()
        owner_id = owner.id
        other_id = other.id

    _login(client, owner_id)
    response = client.get(f"/islem-loglari?user_id={other_id}")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Personel bakım akışı başlattı." in html
    assert "Sahip kullanıcısı sisteme giriş yaptı." not in html
    assert "Kullanıcı: " in html
