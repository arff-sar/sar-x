import pytest
import io
from tests.factories import (
    EquipmentTemplateFactory,
    InventoryAssetFactory,
    MalzemeFactory,
    KullaniciFactory,
    HavalimaniFactory,
    KutuFactory,
)
from extensions import db 
from datetime import date

from models import InventoryAsset, Malzeme # ✅ Sorgular için ekledik

# 1. YETKİ KONTROLÜ: Giriş yapmayan kullanıcı envanteri göremez
def test_envanter_access_required_login(client):
    response = client.get('/envanter')
    assert response.status_code == 302

# 2. SOFT DELETE KONTROLÜ: Silinmiş (Arşivlenmiş) malzemeler listede çıkmaz
def test_envanter_list_active_only(client, app):
    user = KullaniciFactory(rol="sahip")
    m1 = MalzemeFactory(ad="Aktif Ekipman", is_deleted=False)
    m2 = MalzemeFactory(ad="Arşivlenmiş Ekipman", is_deleted=True)
    
    db.session.add_all([user, m1, m2])
    db.session.commit()
    
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id) 
        sess['_fresh'] = True
    
    response = client.get('/envanter')
    data_str = response.data.decode('utf-8')
    
    assert response.status_code == 200
    assert "Aktif Ekipman" in data_str
    assert "Arşivlenmiş Ekipman" not in data_str
    assert 'href="/zimmetler" class="row-btn" style="padding:16px; border-radius:16px; justify-content:flex-start;"' not in data_str
    assert 'href="/kkd" class="row-btn" style="padding:16px; border-radius:16px; justify-content:flex-start;"' not in data_str

# 3. BİRİM FİLTRELEME: Personel sadece kendi havalimanındaki malzemeyi görür
def test_havalimani_isolation(client, app):
    h1 = HavalimaniFactory(kodu="ESB", ad="Ankara")
    h2 = HavalimaniFactory(kodu="SAW", ad="İstanbul")
    
    m1 = MalzemeFactory(ad="Ankara Cihazı", havalimani=h1)
    m2 = MalzemeFactory(ad="İstanbul Cihazı", havalimani=h2)
    
    user = KullaniciFactory(rol="personel", havalimani=h1)
    
    db.session.add_all([h1, h2, m1, m2, user])
    db.session.commit() 
    
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
    
    response = client.get('/envanter')
    data_str = response.data.decode('utf-8')
    
    assert response.status_code == 200
    assert "Ankara Cihazı" in data_str
    assert "İstanbul Cihazı" not in data_str

# 4. YAZMA YETKİSİ: Yetkili kullanıcı malzeme ekleyebilir (Kapsam Artırıcı)
def test_malzeme_ekle_success(client, app):
    app.config['WTF_CSRF_ENABLED'] = False
    user = KullaniciFactory(rol="sahip")
    h = HavalimaniFactory(kodu="IST")
    db.session.add_all([user, h])
    db.session.commit()

    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True

    response = client.post('/malzeme-ekle', data={
        'ad': 'Test Malzemesi',
        'seri_no': 'SN12345',
        'kutu_kodu': 'K-99',
        'stok': 10,
        'durum': 'Aktif',
        'havalimani_id': h.id
    }, follow_redirects=True)

    assert response.status_code == 200
    assert "Malzeme başarıyla eklendi" in response.data.decode('utf-8')
    # Veritabanına gerçekten yazılmış mı kontrol et
    assert Malzeme.query.filter_by(ad="Test Malzemesi").first() is not None

# 5. YETKİ KONTROLÜ: Düz personel malzeme ekleyemez
def test_personel_cannot_add_material(client, app):
    app.config['WTF_CSRF_ENABLED'] = False
    
    user = KullaniciFactory(rol="personel")
    db.session.add(user)
    db.session.commit() 
    
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        
    response = client.post('/malzeme-ekle', data={
        'ad': 'Yeni Hortum',
        'kutu_kodu': 'K-01'
    })
    
    assert response.status_code == 403

# 6. BAKIM KAYDI: Bakım kaydı başarıyla girilebilir (Kapsam Artırıcı)
def test_bakim_kaydet_success(client, app):
    app.config['WTF_CSRF_ENABLED'] = False
    user = KullaniciFactory(rol="sahip")
    m = MalzemeFactory(ad="Bakım Cihazı")
    db.session.add_all([user, m])
    db.session.commit()

    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True

    response = client.post(f'/bakim-kaydet/{m.id}', data={
        'not': 'Yıllık genel bakım yapıldı',
        'maliyet': '500.50'
    }, follow_redirects=True)

    assert response.status_code == 200
    assert "Bakım kaydı başarıyla işlendi" in response.data.decode('utf-8')

# 7. RAPORLAMA: Excel ve PDF çıktıları (Kapsam Artırıcı)
def test_export_routes(client, app):
    user = KullaniciFactory(rol="sahip")
    m = MalzemeFactory()
    db.session.add_all([user, m])
    db.session.commit()

    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True

    # Excel Testi
    excel_res = client.get('/envanter/excel')
    assert excel_res.status_code == 200
    assert excel_res.mimetype == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

    # PDF Testi
    pdf_res = client.get('/envanter/pdf')
    assert pdf_res.status_code == 200
    assert pdf_res.mimetype == 'application/pdf'

# 8. B PLANI (MANUEL BULMA) KONTROLÜ
def test_kutu_bul_manual(client, app):
    app.config['WTF_CSRF_ENABLED'] = False
    
    h1 = HavalimaniFactory(kodu="ESB")
    kutu = KutuFactory(kodu="K-99", havalimani=h1)
    user = KullaniciFactory(rol="personel", havalimani=h1)
    
    db.session.add_all([h1, kutu, user])
    db.session.commit() 
    
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
    
    response = client.post('/kutu-bul', data={'kutu_kodu': 'K-99'}, follow_redirects=True)
    data_str = response.data.decode('utf-8')
    
    assert response.status_code == 200
    assert "K-99" in data_str

# 9. QR API: QR resim üretme rotası (Kapsam Artırıcı)
def test_qr_api_route(client, app):
    user = KullaniciFactory(rol="sahip")
    k = KutuFactory(kodu="QR-TEST")
    db.session.add_all([user, k])
    db.session.commit()

    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True

    response = client.get('/api/qr-img/QR-TEST')
    assert response.status_code == 200
    assert response.mimetype == 'image/png'


def test_malzeme_ekle_accepts_canonical_keys(client, app):
    app.config['WTF_CSRF_ENABLED'] = False
    user = KullaniciFactory(rol="sahip")
    airport = HavalimaniFactory(kodu="AYT")
    box = KutuFactory(kodu="AYT-BOX-1", havalimani=airport)
    template = EquipmentTemplateFactory(name="Gaz Dedektörü", category="Elektronik")
    db.session.add_all([user, airport, box, template])
    db.session.commit()

    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True

    response = client.post(
        '/malzeme-ekle',
        data={
            'airport_id': airport.id,
            'box_id': box.id,
            'template_id': template.id,
            'category': 'Elektronik',
            'asset_name': 'Gaz Dedektörü',
            'serial_no': 'CANON-001',
            'unit_count': 3,
            'status': 'aktif',
            'maintenance_period_months': 4,
            'notes': 'canonical-contract',
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    asset = InventoryAsset.query.filter_by(serial_no="CANON-001").first()
    assert asset is not None
    assert asset.status == "aktif"
    assert asset.unit_count == 3
    assert asset.maintenance_period_months == 4


def test_asset_duzenle_accepts_canonical_status_and_notes(client, app):
    app.config['WTF_CSRF_ENABLED'] = False
    airport = HavalimaniFactory(kodu="RZE")
    manager = KullaniciFactory(rol="yetkili", havalimani=airport)
    template = EquipmentTemplateFactory(name="Kamera", category="Elektronik")
    asset = InventoryAssetFactory(equipment_template=template, airport=airport, status="aktif", serial_no="UPD-001", unit_count=1)
    db.session.add_all([airport, manager, template, asset])
    db.session.commit()

    with client.session_transaction() as sess:
        sess['_user_id'] = str(manager.id)
        sess['_fresh'] = True

    response = client.post(
        f"/asset-duzenle/{asset.id}",
        data={
            "status": "pasif",
            "unit_count": 2,
            "notes": "canonical-edit-note",
            "manual_url": "https://example.com/guide",
            "maintenance_period_months": 5,
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    refreshed = db.session.get(InventoryAsset, asset.id)
    assert refreshed.status == "pasif"
    assert refreshed.unit_count == 2
    assert refreshed.notes == "canonical-edit-note"


def test_asset_duzenle_accepts_legacy_keys(client, app):
    app.config['WTF_CSRF_ENABLED'] = False
    airport = HavalimaniFactory(kodu="ERZ")
    manager = KullaniciFactory(rol="yetkili", havalimani=airport)
    template = EquipmentTemplateFactory(name="Pompa", category="Mekanik")
    asset = InventoryAssetFactory(
        equipment_template=template,
        airport=airport,
        status="aktif",
        serial_no="LEG-UPD-001",
        unit_count=1,
    )
    db.session.add_all([airport, manager, template, asset])
    db.session.commit()

    with client.session_transaction() as sess:
        sess['_user_id'] = str(manager.id)
        sess['_fresh'] = True

    response = client.post(
        f"/asset-duzenle/{asset.id}",
        data={
            "durum": "arizali",
            "stok": 4,
            "notlar": "legacy-edit-note",
            "bakim": "2026-02-14",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    refreshed = db.session.get(InventoryAsset, asset.id)
    assert refreshed.status == "pasif"
    assert refreshed.unit_count == 4
    assert refreshed.notes == "legacy-edit-note"
    assert refreshed.last_maintenance_date == date(2026, 2, 14)


def test_quick_detail_accepts_legacy_and_canonical_note_keys(client, app):
    app.config['WTF_CSRF_ENABLED'] = False
    airport = HavalimaniFactory(kodu="ADA")
    manager = KullaniciFactory(rol="yetkili", havalimani=airport)
    template = EquipmentTemplateFactory(name="Projektör")
    asset = InventoryAssetFactory(equipment_template=template, airport=airport, status="aktif", notes="ilk")
    db.session.add_all([airport, manager, template, asset])
    db.session.commit()

    with client.session_transaction() as sess:
        sess['_user_id'] = str(manager.id)
        sess['_fresh'] = True

    first = client.post(
        f"/asset/{asset.id}/quick",
        data={"status": "aktif", "note": "legacy-note"},
        follow_redirects=True,
    )
    assert first.status_code == 200
    second = client.post(
        f"/asset/{asset.id}/quick",
        data={"status": "aktif", "notes": "canonical-note"},
        follow_redirects=True,
    )
    assert second.status_code == 200
    refreshed = db.session.get(InventoryAsset, asset.id)
    assert "legacy-note" in (refreshed.notes or "")
    assert "canonical-note" in (refreshed.notes or "")


def test_quick_detail_accepts_legacy_durum_key(client, app):
    app.config['WTF_CSRF_ENABLED'] = False
    airport = HavalimaniFactory(kodu="ASR")
    manager = KullaniciFactory(rol="yetkili", havalimani=airport)
    template = EquipmentTemplateFactory(name="Termal Kamera")
    asset = InventoryAssetFactory(equipment_template=template, airport=airport, status="aktif")
    db.session.add_all([airport, manager, template, asset])
    db.session.commit()

    with client.session_transaction() as sess:
        sess['_user_id'] = str(manager.id)
        sess['_fresh'] = True

    response = client.post(
        f"/asset/{asset.id}/quick",
        data={"durum": "pasif", "note": "legacy-status-key"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    refreshed = db.session.get(InventoryAsset, asset.id)
    assert refreshed.status == "pasif"


def test_quick_detail_merges_maintenance_date_aliases(client, app):
    app.config['WTF_CSRF_ENABLED'] = False
    airport = HavalimaniFactory(kodu="GZT")
    manager = KullaniciFactory(rol="yetkili", havalimani=airport)
    template = EquipmentTemplateFactory(name="Kompresor")
    asset = InventoryAssetFactory(equipment_template=template, airport=airport, status="aktif")
    db.session.add_all([airport, manager, template, asset])
    db.session.commit()

    with client.session_transaction() as sess:
        sess['_user_id'] = str(manager.id)
        sess['_fresh'] = True

    r1 = client.post(
        f"/asset/{asset.id}/quick",
        data={"status": "aktif", "bakim": "2026-01-01"},
        follow_redirects=True,
    )
    assert r1.status_code == 200
    assert db.session.get(InventoryAsset, asset.id).last_maintenance_date == date(2026, 1, 1)

    r2 = client.post(
        f"/asset/{asset.id}/quick",
        data={"status": "aktif", "son_bakim_tarihi": "2026-02-02"},
        follow_redirects=True,
    )
    assert r2.status_code == 200
    assert db.session.get(InventoryAsset, asset.id).last_maintenance_date == date(2026, 2, 2)

    r3 = client.post(
        f"/asset/{asset.id}/quick",
        data={"status": "aktif", "last_maintenance_date": "2026-03-03"},
        follow_redirects=True,
    )
    assert r3.status_code == 200
    assert db.session.get(InventoryAsset, asset.id).last_maintenance_date == date(2026, 3, 3)


def test_malzeme_ekle_accepts_legacy_kutu_id_resolution(client, app):
    app.config['WTF_CSRF_ENABLED'] = False
    user = KullaniciFactory(rol="sahip")
    airport = HavalimaniFactory(kodu="BJV")
    box = KutuFactory(kodu="BJV-BOX-7", havalimani=airport)
    template = EquipmentTemplateFactory(name="Hortum", category="Kurtarma")
    db.session.add_all([user, airport, box, template])
    db.session.commit()

    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True

    response = client.post(
        "/malzeme-ekle",
        data={
            "havalimani_id": airport.id,
            "kutu_id": box.id,
            "template_id": template.id,
            "kategori": "Kurtarma",
            "ad": "Legacy Kutu ID Asset",
            "seri_no": "LEG-KUTU-001",
            "stok": 2,
            "durum": "Aktif",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    created = InventoryAsset.query.filter_by(serial_no="LEG-KUTU-001").first()
    assert created is not None
    assert created.legacy_material is not None
    assert created.legacy_material.kutu_id == box.id
