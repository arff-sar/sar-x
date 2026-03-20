from extensions import db
from tests.factories import HavalimaniFactory, KullaniciFactory, SparePartFactory, SparePartStockFactory


def _login(client, user):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


def test_manager_can_create_spare_part(client, app):
    airport = HavalimaniFactory(kodu="ADA")
    manager = KullaniciFactory(rol="yetkili", havalimani=airport)
    db.session.add_all([airport, manager])
    db.session.commit()
    _login(client, manager)

    response = client.post(
        "/yedek-parcalar/yeni",
        data={
            "part_code": "FILTRE-01",
            "title": "Hidrolik Filtre",
            "category": "Hidrolik",
            "unit": "adet",
            "min_stock_level": 2,
            "critical_level": 1,
            "is_active": "on",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Yedek parça kaydedildi" in response.data.decode("utf-8")


def test_low_stock_endpoint_returns_critical_stock(client, app):
    airport = HavalimaniFactory(kodu="BJV")
    owner = KullaniciFactory(rol="sahip")
    part = SparePartFactory(part_code="LOW-01", title="Düşük Stok Parça")
    stock = SparePartStockFactory(
        spare_part=part,
        airport_stock=airport,
        quantity_on_hand=1,
        quantity_reserved=0,
        reorder_point=3,
    )
    db.session.add_all([airport, owner, part, stock])
    db.session.commit()
    _login(client, owner)

    response = client.get("/api/parca/dusuk-stok")
    assert response.status_code == 200
    data = response.get_json()["veri"]
    assert any(row["part_code"] == "LOW-01" for row in data)

