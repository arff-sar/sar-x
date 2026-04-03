from extensions import db
from tests.factories import HavalimaniFactory, InventoryAssetFactory, KutuFactory, KullaniciFactory


def _login(client, user_id):
    with client.session_transaction() as session:
        session.clear()
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_inventory_and_box_bulk_qr_print_pages_render(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        user = KullaniciFactory(rol="depo_sorumlusu", havalimani=airport, is_deleted=False)
        asset_one = InventoryAssetFactory(airport=airport)
        asset_two = InventoryAssetFactory(airport=airport)
        box_one = KutuFactory(kodu="ERZ-BOX-01", havalimani=airport)
        box_two = KutuFactory(kodu="ERZ-BOX-02", havalimani=airport)
        db.session.add_all([airport, user, asset_one, asset_two, box_one, box_two])
        db.session.commit()
        user_id = user.id
        asset_ids = [asset_one.id, asset_two.id]
        box_ids = [box_one.id, box_two.id]

    _login(client, user_id)

    inventory_response = client.post(
        "/qr-uret/toplu/envanter",
        data={"asset_ids": [str(asset_ids[0]), str(asset_ids[1])]},
    )
    box_response = client.post(
        "/qr-uret/toplu/kutular",
        data={"box_ids": [str(box_ids[0]), str(box_ids[1])]},
    )

    assert inventory_response.status_code == 200
    assert "Toplu Envanter QR Yazdır" in inventory_response.data.decode("utf-8")
    assert box_response.status_code == 200
    assert "Toplu Kutu QR Yazdır" in box_response.data.decode("utf-8")


def test_bulk_qr_print_routes_enforce_page_limits(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Ankara Havalimanı", kodu="ESB")
        user = KullaniciFactory(rol="depo_sorumlusu", havalimani=airport, is_deleted=False)
        db.session.add_all([airport, user])
        db.session.commit()
        user_id = user.id

    _login(client, user_id)

    inventory_limit_response = client.post(
        "/qr-uret/toplu/envanter",
        data={"asset_ids": [str(index) for index in range(1, 20)]},
        follow_redirects=False,
    )
    box_limit_response = client.post(
        "/qr-uret/toplu/kutular",
        data={"box_ids": [str(index) for index in range(1, 12)]},
        follow_redirects=False,
    )

    assert inventory_limit_response.status_code == 302
    assert "/envanter" in inventory_limit_response.headers.get("Location", "")
    assert box_limit_response.status_code == 302
    assert "/kutular" in box_limit_response.headers.get("Location", "")
