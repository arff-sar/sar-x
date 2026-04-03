from extensions import db
from tests.factories import HavalimaniFactory, KullaniciFactory


def _login(client, user_or_id):
    user_id = getattr(user_or_id, "id", user_or_id)
    with client.session_transaction() as session:
        session.clear()
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_filter_action_rows_render_with_expected_alignment_hooks(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Ankara Esenboğa", kodu="ESB")
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="layout-owner@sarx.com", havalimani=airport)
        db.session.add_all([airport, owner])
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)

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


def test_filter_forms_keep_controls_and_action_buttons_on_same_visual_baseline(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="İzmir Adnan Menderes", kodu="ADB")
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="filter-baseline@sarx.com", havalimani=airport)
        db.session.add_all([airport, owner])
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    zimmet_html = client.get("/zimmetler").data.decode("utf-8")
    envanter_html = client.get("/envanter").data.decode("utf-8")

    assert ".assignment-filter-form .form-control," in zimmet_html
    assert ".assignment-filter-actions .btn," in zimmet_html
    assert ".inventory-filter-form .form-control," in envanter_html
    assert ".inventory-filter-actions .btn," in envanter_html
