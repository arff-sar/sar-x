from extensions import db
from tests.factories import HavalimaniFactory, KullaniciFactory


def _login(client, user):
    with client.session_transaction() as session:
        session.clear()
        session["_user_id"] = str(user.id)
        session["_fresh"] = True


def test_filter_action_rows_render_with_expected_alignment_hooks(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Ankara Esenboğa", kodu="ESB")
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="layout-owner@sarx.com", havalimani=airport)
        db.session.add_all([airport, owner])
        db.session.commit()
        owner_id = owner.id

    _login(client, owner)

    expectations = {
        "/islem-loglari": ["logs-filter-actions-shell", "Temizle"],
        "/hata-kayitlari": ["error-log-actions-shell", "Temizle"],
        "/kutular": ["box-create-form", "Yeni Kutu Oluştur"],
        "/tatbikatlar": ["drill-filter-actions-shell", "Temizle"],
        "/zimmetler": ["assignment-filter-actions", "Temizle"],
        "/envanter": ["inventory-filter-actions", "Sıfırla"],
        "/kkd": ["ppe-filter-actions-shell", "Temizle"],
    }

    for path, markers in expectations.items():
        response = client.get(path)
        html = response.data.decode("utf-8")
        assert response.status_code == 200
        for marker in markers:
            assert marker in html
