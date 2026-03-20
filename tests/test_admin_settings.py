import json


def test_update_site_settings(client, app):
    # ✅ CSRF korumasını test ortamında kapatıyoruz ki POST işlemi engellenmesin
    app.config['WTF_CSRF_ENABLED'] = False 
    
    from extensions import db
    from models import SiteAyarlari
    from tests.factories import KullaniciFactory

    admin = KullaniciFactory(rol="sahip")
    
    # ✅ KRİTİK EKSİK BURADAYDI: Admini ve Ayarları DB'ye ekliyoruz
    db.session.add(admin) 
    db.session.add(SiteAyarlari(baslik="Eski Başlık", iletisim_notu="Eski Not"))
    db.session.commit() # Artık admin.id kesinlikle dolu (None değil)

    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin.id)
        sess['_fresh'] = True

    # Şimdi sisteme gerçekten 'sahip' yetkisiyle post atıyoruz
    response = client.post('/site-ayarlarini-guncelle', data={
        'baslik': 'Yeni SAR-X Paneli',
        'alt_metin': 'Gönüllü ekip vitrini',
        'logo_url': 'https://example.com/logo.png',
        'public_contact_note': 'İş birliği ve duyuru paylaşımı için bize yazın.'
    }, follow_redirects=True)

    assert response.status_code == 200
    
    # Veritabanını temizle ve güncel halini çek
    db.session.expire_all()
    guncel_ayar = SiteAyarlari.query.first()
    
    # Mutlu son!
    assert guncel_ayar.baslik == 'Yeni SAR-X Paneli'
    meta = json.loads(guncel_ayar.iletisim_notu)
    assert meta["public_logo_url"] == 'https://example.com/logo.png'
    assert meta["public_contact_note"] == 'İş birliği ve duyuru paylaşımı için bize yazın.'
