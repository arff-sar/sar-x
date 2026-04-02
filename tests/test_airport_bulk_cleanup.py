from extensions import db
from models import (
    EquipmentTemplate,
    Havalimani,
    InventoryAsset,
    Kutu,
    Malzeme,
    PPEAssignmentRecord,
    PPERecord,
    WorkOrder,
)
from tests.factories import KullaniciFactory


def _login(client, user_id):
    with client.session_transaction() as session:
        session.clear()
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def _create_airport_scope(owner, airport, suffix):
    box = Kutu(kodu=f"{airport.kodu}-BOX-{suffix}", havalimani_id=airport.id)
    db.session.add(box)
    db.session.flush()

    material = Malzeme(
        ad=f"Malzeme-{suffix}",
        seri_no=f"MAT-{suffix}",
        kutu_id=box.id,
        havalimani_id=airport.id,
        is_deleted=False,
    )
    db.session.add(material)
    db.session.flush()

    template = EquipmentTemplate(
        name=f"Template-{suffix}",
        category="Genel",
        is_active=True,
    )
    db.session.add(template)
    db.session.flush()

    asset = InventoryAsset(
        equipment_template_id=template.id,
        havalimani_id=airport.id,
        legacy_material_id=material.id,
        serial_no=f"ASSET-{suffix}",
        qr_code=f"ASSET-QR-{suffix}",
        status="aktif",
    )
    db.session.add(asset)
    db.session.flush()

    user = KullaniciFactory(
        rol="personel",
        kullanici_adi=f"personel-{suffix}@sarx.com",
        tam_ad=f"Personel {suffix}",
        havalimani_id=airport.id,
    )
    db.session.add(user)
    db.session.flush()

    work_order = WorkOrder(
        work_order_no=f"WO-{suffix}",
        asset_id=asset.id,
        description="Toplu silme test iş emri",
        created_user_id=owner.id,
        status="acik",
    )
    db.session.add(work_order)
    db.session.flush()

    ppe_record = PPERecord(
        user_id=user.id,
        airport_id=airport.id,
        item_name=f"KKD-{suffix}",
        quantity=1,
        status="aktif",
        created_by_id=owner.id,
    )
    db.session.add(ppe_record)
    db.session.flush()

    ppe_assignment = PPEAssignmentRecord(
        assignment_no=f"KKD-ZMT-{suffix}",
        delivered_by_id=owner.id,
        delivered_by_name=owner.tam_ad,
        recipient_user_id=user.id,
        airport_id=airport.id,
        status="active",
        created_by_id=owner.id,
    )
    db.session.add(ppe_assignment)
    db.session.flush()

    return {
        "material_id": material.id,
        "asset_id": asset.id,
        "user_id": user.id,
        "work_order_id": work_order.id,
        "ppe_record_id": ppe_record.id,
        "ppe_assignment_id": ppe_assignment.id,
    }


def test_bulk_cleanup_page_renders_for_owner(client, app):
    owner = KullaniciFactory(rol="sahip")
    db.session.add(owner)
    db.session.commit()

    _login(client, owner.id)
    response = client.get("/site-yonetimi/havalimani-toplu-silme")
    page = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Havalimanı Bazlı Toplu Silme" in page
    assert "Havalimanı Toplu Silme" in page


def test_bulk_cleanup_requires_owner_role(client, app):
    non_owner = KullaniciFactory(rol="admin")
    airport = Havalimani(ad="Test Airport", kodu="TST")
    db.session.add_all([non_owner, airport])
    db.session.commit()

    _login(client, non_owner.id)
    response = client.post(
        "/havalimani-toplu-silme",
        data={
            "airport_id": airport.id,
            "confirm_text": "SIL-TST",
            "confirm_password": "123456",
        },
        follow_redirects=False,
    )

    assert response.status_code == 403


def test_bulk_cleanup_rejects_wrong_password_and_keeps_records(client, app):
    owner = KullaniciFactory(rol="sahip")
    airport = Havalimani(ad="Istanbul", kodu="IST")
    db.session.add_all([owner, airport])
    db.session.flush()
    scoped = _create_airport_scope(owner, airport, "IST-1")
    db.session.commit()

    _login(client, owner.id)
    response = client.post(
        "/havalimani-toplu-silme",
        data={
            "airport_id": airport.id,
            "confirm_text": "SIL-IST",
            "confirm_password": "yanlis-sifre",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    db.session.expire_all()
    assert db.session.get(Malzeme, scoped["material_id"]).is_deleted is False
    assert db.session.get(WorkOrder, scoped["work_order_id"]).is_deleted is False
    assert db.session.get(PPERecord, scoped["ppe_record_id"]).is_deleted is False


def test_bulk_cleanup_soft_deletes_only_selected_airport_scope(client, app):
    target_airport = Havalimani(ad="Ankara Esenboga", kodu="ESB")
    other_airport = Havalimani(ad="Izmir Adnan Menderes", kodu="ADB")
    owner = KullaniciFactory(rol="sahip", havalimani=target_airport)
    db.session.add_all([target_airport, other_airport, owner])
    db.session.flush()

    target_scope = _create_airport_scope(owner, target_airport, "ESB-1")
    other_scope = _create_airport_scope(owner, other_airport, "ADB-1")
    db.session.commit()

    _login(client, owner.id)
    response = client.post(
        "/havalimani-toplu-silme",
        data={
            "airport_id": target_airport.id,
            "confirm_text": "SIL-ESB",
            "confirm_password": "123456",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302

    db.session.expire_all()

    assert db.session.get(Malzeme, target_scope["material_id"]).is_deleted is True
    assert db.session.get(InventoryAsset, target_scope["asset_id"]).is_deleted is True
    assert db.session.get(WorkOrder, target_scope["work_order_id"]).is_deleted is True
    assert db.session.get(PPERecord, target_scope["ppe_record_id"]).is_deleted is True
    assert db.session.get(PPEAssignmentRecord, target_scope["ppe_assignment_id"]).is_deleted is True

    assert db.session.get(Malzeme, other_scope["material_id"]).is_deleted is False
    assert db.session.get(InventoryAsset, other_scope["asset_id"]).is_deleted is False
    assert db.session.get(WorkOrder, other_scope["work_order_id"]).is_deleted is False
    assert db.session.get(PPERecord, other_scope["ppe_record_id"]).is_deleted is False
    assert db.session.get(PPEAssignmentRecord, other_scope["ppe_assignment_id"]).is_deleted is False

    # Sistem yöneticisi kendi hesabını silme kapsamı dışında kalmalı.
    assert db.session.get(type(owner), owner.id).is_deleted is False
