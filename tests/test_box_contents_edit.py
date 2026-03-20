from extensions import db
from models import InventoryAsset, Kutu, Malzeme
from tests.factories import EquipmentTemplateFactory, HavalimaniFactory, InventoryAssetFactory, KutuFactory, KullaniciFactory, MalzemeFactory


def _login(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_box_contents_can_be_added_moved_and_removed(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Kars Havalimanı", kodu="KSY")
        user = KullaniciFactory(rol="depo_sorumlusu", havalimani=airport, is_deleted=False)
        box_one = KutuFactory(kodu="KSY-KUTU-01", havalimani=airport)
        box_two = KutuFactory(kodu="KSY-KUTU-02", havalimani=airport)
        material = MalzemeFactory(ad="Telsiz", kutu=box_one, havalimani=airport, stok_miktari=1, is_deleted=False)
        spare_material = MalzemeFactory(ad="Projektor", kutu=box_two, havalimani=airport, stok_miktari=2, is_deleted=False)
        template = EquipmentTemplateFactory(name="Telsiz")
        asset = InventoryAssetFactory(equipment_template=template, airport=airport, status="aktif", depot_location=box_one.kodu)
        db.session.add_all([airport, user, box_one, box_two, material, spare_material, template, asset])
        db.session.flush()
        asset.legacy_material_id = material.id
        db.session.commit()
        user_id = user.id
        box_one_code = box_one.kodu
        box_two_id = box_two.id
        material_id = material.id
        spare_material_id = spare_material.id
        asset_id = asset.id

    _login(client, user_id)
    add_response = client.post(
        f"/kutu/{box_one_code}/malzeme-ekle",
        data={"material_id": str(spare_material_id)},
        follow_redirects=True,
    )
    assert add_response.status_code == 200

    move_response = client.post(
        f"/kutu/{box_one_code}/icerik-guncelle/{material_id}",
        data={"target_kutu_id": str(box_two_id), "stok_miktari": "3"},
        follow_redirects=True,
    )
    assert move_response.status_code == 200

    remove_response = client.post(
        "/kutu/KSY-KUTU-02/malzeme-cikar/{}".format(material_id),
        data={},
        follow_redirects=True,
    )
    assert remove_response.status_code == 200

    with app.app_context():
        moved_material = db.session.get(Malzeme, material_id)
        added_material = db.session.get(Malzeme, spare_material_id)
        fallback_box = Kutu.query.filter_by(kodu="KSY-ATANMADI", is_deleted=False).first()
        assert added_material.kutu.kodu == box_one_code
        assert moved_material.stok_miktari == 3
        assert fallback_box is not None
        assert moved_material.kutu_id == fallback_box.id
        asset = db.session.get(InventoryAsset, asset_id)
        assert asset.depot_location == fallback_box.kodu
