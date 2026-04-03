import pytest

from extensions import db
from models import AssetMeterReading, Kutu
from tests.factories import (
    EquipmentTemplateFactory,
    HavalimaniFactory,
    InventoryAssetFactory,
    KutuFactory,
    KullaniciFactory,
    MalzemeFactory,
)


def _login(client, user_id):
    with client.session_transaction() as session:
        session.clear()
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


@pytest.mark.parametrize(
    "role_key,can_see_remote",
    [
        ("sistem_sorumlusu", True),
        ("ekip_sorumlusu", False),
        ("ekip_uyesi", False),
        ("genel_mudurluk", False),
    ],
)
def test_four_roles_inventory_visibility_is_scoped(client, app, role_key, can_see_remote):
    with app.app_context():
        airport_one = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        airport_two = HavalimaniFactory(ad="Trabzon Havalimanı", kodu="TZX")
        box_one = KutuFactory(kodu="ERZ-SAR-001", havalimani=airport_one)
        box_two = KutuFactory(kodu="TZX-SAR-001", havalimani=airport_two)
        own_material = MalzemeFactory(ad="ERZ Scope Test", seri_no=f"ERZ-SCOPE-{role_key}", kutu=box_one, havalimani=airport_one)
        remote_material = MalzemeFactory(ad="TZX Scope Test", seri_no=f"TZX-SCOPE-{role_key}", kutu=box_two, havalimani=airport_two)
        user = KullaniciFactory(rol=role_key, havalimani=airport_one, is_deleted=False)
        db.session.add_all([airport_one, airport_two, box_one, box_two, own_material, remote_material, user])
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    response = client.get("/envanter")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "ERZ Scope Test" in html
    if can_see_remote:
        assert "TZX Scope Test" in html
    else:
        assert "TZX Scope Test" not in html


@pytest.mark.parametrize(
    "role_key,can_write_remote",
    [
        ("sistem_sorumlusu", True),
        ("ekip_sorumlusu", False),
        ("ekip_uyesi", False),
        ("genel_mudurluk", False),
    ],
)
def test_four_roles_meter_write_respects_airport_scope(client, app, role_key, can_write_remote):
    with app.app_context():
        airport_one = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        airport_two = HavalimaniFactory(ad="Trabzon Havalimanı", kodu="TZX")
        template = EquipmentTemplateFactory(name=f"Scope Meter Template {role_key}", category="Kurtarma")
        own_asset = InventoryAssetFactory(equipment_template=template, airport=airport_one, serial_no=f"ERZ-ASSET-{role_key}")
        remote_asset = InventoryAssetFactory(equipment_template=template, airport=airport_two, serial_no=f"TZX-ASSET-{role_key}")
        user = KullaniciFactory(rol=role_key, havalimani=airport_one, is_deleted=False)
        db.session.add_all([airport_one, airport_two, template, own_asset, remote_asset, user])
        db.session.commit()
        user_id = user.id
        own_asset_id = own_asset.id
        remote_asset_id = remote_asset.id

    _login(client, user_id)

    own_response = client.post(
        "/bakim/sayaclar",
        data={
            "asset_id": own_asset_id,
            "meter_name": "Çalışma Saati",
            "meter_type": "hours",
            "unit": "saat",
            "reading_value": "11",
            "note": "Own scope reading",
        },
        follow_redirects=False,
    )
    assert own_response.status_code == 302

    with app.app_context():
        own_reading_count = AssetMeterReading.query.filter_by(asset_id=own_asset_id, is_deleted=False).count()
        remote_reading_before = AssetMeterReading.query.filter_by(asset_id=remote_asset_id, is_deleted=False).count()
    assert own_reading_count == 1

    remote_response = client.post(
        "/bakim/sayaclar",
        data={
            "asset_id": remote_asset_id,
            "meter_name": "Çalışma Saati",
            "meter_type": "hours",
            "unit": "saat",
            "reading_value": "12",
            "note": "Remote scope reading",
        },
        follow_redirects=False,
    )
    assert remote_response.status_code == 302

    with app.app_context():
        remote_reading_after = AssetMeterReading.query.filter_by(asset_id=remote_asset_id, is_deleted=False).count()

    if can_write_remote:
        assert remote_reading_after == remote_reading_before + 1
    else:
        assert remote_reading_after == remote_reading_before


@pytest.mark.parametrize(
    "role_key,expected_status,expected_airport",
    [
        ("sistem_sorumlusu", 302, "remote"),
        ("ekip_sorumlusu", 302, "own"),
        ("ekip_uyesi", 403, "none"),
        ("genel_mudurluk", 403, "none"),
    ],
)
def test_four_roles_box_create_permissions_and_scope(client, app, role_key, expected_status, expected_airport):
    with app.app_context():
        airport_one = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        airport_two = HavalimaniFactory(ad="Trabzon Havalimanı", kodu="TZX")
        user = KullaniciFactory(rol=role_key, havalimani=airport_one, is_deleted=False)
        db.session.add_all([airport_one, airport_two, user])
        db.session.commit()
        user_id = user.id
        own_airport_id = airport_one.id
        remote_airport_id = airport_two.id
        own_box_before = Kutu.query.filter_by(havalimani_id=own_airport_id, is_deleted=False).count()
        remote_box_before = Kutu.query.filter_by(havalimani_id=remote_airport_id, is_deleted=False).count()

    _login(client, user_id)
    response = client.post(
        "/kutular/yeni",
        data={"havalimani_id": remote_airport_id, "marka": "Scope Test Marka"},
        follow_redirects=False,
    )
    assert response.status_code == expected_status

    with app.app_context():
        own_box_after = Kutu.query.filter_by(havalimani_id=own_airport_id, is_deleted=False).count()
        remote_box_after = Kutu.query.filter_by(havalimani_id=remote_airport_id, is_deleted=False).count()

    if expected_airport == "remote":
        assert remote_box_after == remote_box_before + 1
        assert own_box_after == own_box_before
    elif expected_airport == "own":
        assert own_box_after == own_box_before + 1
        assert remote_box_after == remote_box_before
    else:
        assert own_box_after == own_box_before
        assert remote_box_after == remote_box_before
