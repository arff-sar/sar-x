from demo_data import seed_demo_data


def _login(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_manager_summary_shows_critical_metrics_and_demo_data(client, app):
    with app.app_context():
        seed_demo_data(reset=True)
        from models import Kullanici

        owner = Kullanici.query.filter_by(rol="sahip").first()
        user_id = owner.id

    _login(client, user_id)
    response = client.get("/reports/manager-summary")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Yönetici Özeti" in html
    assert "Kırmızı Alanlar" in html
    assert "Yaklaşan Riskler" in html
    assert "En Çok İş Emri Üreten Lokasyon" in html
    assert "Kapanmayan Kritik İşler" in html
    assert (
        "Erzurum Havalimanı" in html
        or "Balıkesir Koca Seyit Havalimanı" in html
        or "Kocaeli Cengiz Topel Havalimanı" in html
    )
