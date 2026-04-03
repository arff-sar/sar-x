from extensions import db
from models import AssetSparePartLink, SparePart
from tests.factories import (
    EquipmentTemplateFactory,
    HavalimaniFactory,
    InventoryAssetFactory,
    KullaniciFactory,
    SparePartFactory,
    SparePartStockFactory,
)


def _login(client, user):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


def test_manager_can_create_spare_part_from_asset_detail(client, app):
    airport = HavalimaniFactory(kodu="ADA")
    manager = KullaniciFactory(rol="yetkili", havalimani=airport)
    template = EquipmentTemplateFactory(name="Termal Kamera")
    asset = InventoryAssetFactory(equipment_template=template, airport=airport)
    db.session.add_all([airport, manager, template, asset])
    db.session.commit()
    _login(client, manager)

    response = client.post(
        f"/asset/{asset.id}/detay",
        data={
            "action": "spare_create_linked",
            "part_code": "FILTRE-01",
            "title": "Hidrolik Filtre",
            "category": "Hidrolik",
            "unit": "adet",
            "min_stock_level": 2,
            "critical_level": 1,
            "quantity_required": 1,
            "quantity_on_hand": 5,
            "quantity_reserved": 0,
            "reorder_point": 2,
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    html = response.data.decode("utf-8")
    assert "Yeni yedek parça oluşturuldu ve envantere bağlandı" in html

    created_part = SparePart.query.filter_by(part_code="FILTRE-01").first()
    assert created_part is not None
    link = AssetSparePartLink.query.filter_by(asset_id=asset.id, spare_part_id=created_part.id, is_deleted=False).first()
    assert link is not None


def test_legacy_spare_parts_page_redirects_to_inventory(client, app):
    airport = HavalimaniFactory(kodu="LTK")
    manager = KullaniciFactory(rol="yetkili", havalimani=airport)
    db.session.add_all([airport, manager])
    db.session.commit()
    _login(client, manager)

    response = client.get("/yedek-parcalar", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/envanter")

    redirected = client.get("/yedek-parcalar", follow_redirects=True)
    assert redirected.status_code == 200
    assert "Yedek parça yönetimi artık malzeme/ekipman detayı içinden yürütülüyor." in redirected.data.decode("utf-8")


def test_legacy_spare_part_detail_redirects_to_linked_asset(client, app):
    airport = HavalimaniFactory(kodu="ESB")
    manager = KullaniciFactory(rol="yetkili", havalimani=airport)
    template = EquipmentTemplateFactory(name="Kompresör")
    asset = InventoryAssetFactory(equipment_template=template, airport=airport)
    part = SparePartFactory(part_code="LINK-01", title="Bağlı Parça")
    db.session.add_all([airport, manager, template, asset, part])
    db.session.commit()

    link = AssetSparePartLink(asset_id=asset.id, spare_part_id=part.id, quantity_required=1, is_active=True)
    db.session.add(link)
    db.session.commit()
    _login(client, manager)

    response = client.get(f"/yedek-parcalar/{part.id}", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/asset/{asset.id}/detay")


def test_asset_detail_contains_spare_part_manage_and_add_sections(client, app):
    airport = HavalimaniFactory(kodu="GZT")
    manager = KullaniciFactory(rol="yetkili", havalimani=airport)
    template = EquipmentTemplateFactory(name="Termal Kamera")
    asset = InventoryAssetFactory(equipment_template=template, airport=airport)
    db.session.add_all([airport, manager, template, asset])
    db.session.commit()
    _login(client, manager)

    response = client.get(f"/asset/{asset.id}/detay")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Yedek Parçaları Yönet" in html
    assert "Yedek Parça Ekle" in html


def test_low_stock_endpoint_returns_critical_stock(client, app):
    airport = HavalimaniFactory(kodu="BJV")
    owner = KullaniciFactory(rol="sistem_sorumlusu")
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
