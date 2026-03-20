from extensions import db
from tests.factories import HavalimaniFactory, InventoryAssetFactory, KullaniciFactory


def _login(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_asset_code_uses_standard_format(app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        asset = InventoryAssetFactory(airport=airport)
        db.session.add_all([airport, asset])
        db.session.commit()

        assert asset.asset_code == f"ARFF-SAR-{asset.id:06d}"


def test_same_asset_does_not_generate_duplicate_code(app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        asset = InventoryAssetFactory(airport=airport)
        db.session.add_all([airport, asset])
        db.session.commit()

        first_code = asset.asset_code
        second_code = asset.asset_code

        assert first_code == second_code


def test_qr_print_contains_asset_code_and_airport_name(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        asset = InventoryAssetFactory(airport=airport)
        user = KullaniciFactory(rol="personel", havalimani=airport, is_deleted=False)
        db.session.add_all([airport, asset, user])
        db.session.commit()
        user_id = user.id
        asset_id = asset.id
        asset_code = asset.asset_code

    _login(client, user_id)
    response = client.get(f"/qr-uret/asset/{asset_id}")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert asset_code in html
    assert "ERZURUM HAVALİMANI" in html
