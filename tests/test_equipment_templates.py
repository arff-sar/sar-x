from extensions import db
from models import EquipmentTemplate, InventoryAsset
from tests.factories import HavalimaniFactory, KullaniciFactory


def _login(client, user):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


def test_admin_can_create_equipment_template(client, app):
    admin = KullaniciFactory(rol="sahip")
    db.session.add(admin)
    db.session.commit()
    _login(client, admin)

    response = client.post(
        "/bakim/ekipman-sablonlari",
        data={
            "name": "Termal Kamera",
            "category": "Elektronik",
            "maintenance_period_days": 90,
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    template = EquipmentTemplate.query.filter_by(name="Termal Kamera").first()
    assert template is not None
    assert template.category == "Elektronik"


def test_airport_manager_can_add_asset_from_central_template(client, app):
    airport = HavalimaniFactory(kodu="ESB")
    manager = KullaniciFactory(rol="yetkili", havalimani=airport)
    template = EquipmentTemplate(name="Gaz Ölçüm Cihazı", category="Sensör", maintenance_period_days=60, is_active=True)
    db.session.add_all([airport, manager, template])
    db.session.commit()
    _login(client, manager)

    response = client.post(
        f"/merkezi-sablondan-envantere-ekle/{template.id}",
        data={
            "kutu_kodu": "DEP-10",
            "seri_no": "ESB-0001",
            "stok": 1,
            "durum": "Aktif",
            "ad": "Gaz Ölçüm Cihazı",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    asset = InventoryAsset.query.filter_by(serial_no="ESB-0001").first()
    assert asset is not None
    assert asset.havalimani_id == airport.id
    assert asset.equipment_template_id == template.id


def test_same_template_can_be_used_by_two_airports_with_different_serial(client, app):
    h1 = HavalimaniFactory(kodu="ESB")
    h2 = HavalimaniFactory(kodu="SAW")
    owner = KullaniciFactory(rol="sahip")
    template = EquipmentTemplate(name="Basınç Regülatörü", category="Mekanik", maintenance_period_days=120, is_active=True)
    db.session.add_all([h1, h2, owner, template])
    db.session.commit()
    _login(client, owner)

    client.post(
        f"/merkezi-sablondan-envantere-ekle/{template.id}",
        data={
            "havalimani_id": h1.id,
            "kutu_kodu": "A-01",
            "seri_no": "ESB-SN-1",
            "ad": "Basınç Regülatörü",
        },
        follow_redirects=True,
    )
    client.post(
        f"/merkezi-sablondan-envantere-ekle/{template.id}",
        data={
            "havalimani_id": h2.id,
            "kutu_kodu": "B-01",
            "seri_no": "SAW-SN-1",
            "ad": "Basınç Regülatörü",
        },
        follow_redirects=True,
    )

    assets = InventoryAsset.query.filter_by(equipment_template_id=template.id).all()
    assert len(assets) == 2
    assert {asset.havalimani_id for asset in assets} == {h1.id, h2.id}
    assert {asset.serial_no for asset in assets} == {"ESB-SN-1", "SAW-SN-1"}
