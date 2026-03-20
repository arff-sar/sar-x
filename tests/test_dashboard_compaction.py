from extensions import db
from tests.factories import HavalimaniFactory, KullaniciFactory


def _login(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_dashboard_primary_and_secondary_kpis_are_compacted(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Kars Havalimanı", kodu="KSY")
        user = KullaniciFactory(rol="personel", havalimani=airport, is_deleted=False)
        db.session.add_all([airport, user])
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    response = client.get("/dashboard")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert html.count('data-kpi-tier="primary"') == 4
    assert html.count('data-kpi-tier="secondary"') == 5
    assert "Toplam Ekipman" in html
    assert "Arızalı Malzeme" in html
    assert "Geciken Bakım" in html
    assert "Açık İş Emri" in html
    assert "Düşük Stok Parça" in html
    assert "Sayaç Yaklaşan Bakım" in html
    assert "Otomatik İş Emri" in html
    assert "Alt Bileşen Arızası" in html
    assert "Kalibrasyon Gecikmesi" in html
    assert "Excel İndir" not in html
    assert "PDF Rapor" not in html
