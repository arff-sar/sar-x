from extensions import db
from tests.factories import EquipmentTemplateFactory, HavalimaniFactory, InventoryAssetFactory, KullaniciFactory


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

        assert asset.asset_code == f"ARFF-SAR-{asset.id:04d}"


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
        template = EquipmentTemplateFactory(name="Termal Kamera", brand="FLIR", model_code="K65")
        asset = InventoryAssetFactory(airport=airport, equipment_template=template)
        user = KullaniciFactory(rol="sahip", havalimani=airport, is_deleted=False)
        db.session.add_all([airport, template, asset, user])
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
    assert "SAR-X ARFF ENVANTER YÖNETİM SİSTEMİ" in html
    assert "FLIR K65" in html


def test_legacy_six_digit_asset_code_still_resolves_qr_image(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        asset = InventoryAssetFactory(airport=airport)
        user = KullaniciFactory(rol="sahip", havalimani=airport, is_deleted=False)
        db.session.add_all([airport, asset, user])
        db.session.commit()
        user_id = user.id
        asset_id = asset.id

    _login(client, user_id)
    response = client.get(f"/api/qr-img/ARFF-SAR-{asset_id:06d}")
    assert response.status_code == 200
    assert response.mimetype == "image/png"
