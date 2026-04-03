import json


def test_update_site_settings(client, app):
    # ✅ CSRF korumasını test ortamında kapatıyoruz ki POST işlemi engellenmesin
    app.config['WTF_CSRF_ENABLED'] = False 
    
    from extensions import db
    from models import SiteAyarlari
    from tests.factories import KullaniciFactory

    admin = KullaniciFactory(rol="sistem_sorumlusu")
    
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
        'footer_brand_kicker': 'ARFF SAR',
        'footer_brand_title': 'ARFF Özel Arama Kurtarma Timi',
        'footer_brand_description': 'Sahada birlikte güçlenen gönüllü tim.',
        'footer_contact_kicker': 'İletişim',
        'footer_contact_title': 'Bizimle iletişime geçin',
        'footer_contact_description': 'İş birliği ve duyuru paylaşımı için bize yazın.',
        'footer_contact_email': 'iletisim@example.org',
        'footer_copyright': '© 2026 ARFF SAR',
        'footer_bottom_slogan': 'Hazır koordinasyon',
    }, follow_redirects=True)

    assert response.status_code == 200
    
    # Veritabanını temizle ve güncel halini çek
    db.session.expire_all()
    guncel_ayar = SiteAyarlari.query.first()
    
    # Mutlu son!
    assert guncel_ayar.baslik == 'Yeni SAR-X Paneli'
    meta = json.loads(guncel_ayar.iletisim_notu)
    assert meta["public_logo_url"] == 'https://example.com/logo.png'
    assert meta["footer_brand_kicker"] == "ARFF SAR"
    assert meta["footer_brand_title"] == "ARFF Özel Arama Kurtarma Timi"
    assert meta["footer_brand_description"] == "Sahada birlikte güçlenen gönüllü tim."
    assert meta["footer_contact_kicker"] == "İletişim"
    assert meta["footer_contact_title"] == "Bizimle iletişime geçin"
    assert meta["footer_contact_description"] == 'İş birliği ve duyuru paylaşımı için bize yazın.'
    assert meta["footer_contact_email"] == "iletisim@example.org"
    assert meta["footer_copyright"] == "© 2026 ARFF SAR"
    assert meta["footer_bottom_slogan"] == "Hazır koordinasyon"
    assert meta["public_contact_note"] == 'İş birliği ve duyuru paylaşımı için bize yazın.'


def test_site_settings_page_renders_footer_content_inputs(client, app):
    app.config['WTF_CSRF_ENABLED'] = False

    from extensions import db
    from models import SiteAyarlari
    from tests.factories import KullaniciFactory

    owner = KullaniciFactory(rol="sistem_sorumlusu")
    settings = SiteAyarlari(
        baslik="SAR-X",
        iletisim_notu=json.dumps(
            {
                "footer_brand_kicker": "ARFF SAR",
                "footer_contact_email": "iletisim@test.org",
            },
            ensure_ascii=False,
        ),
    )
    db.session.add_all([owner, settings])
    db.session.commit()

    with client.session_transaction() as sess:
        sess['_user_id'] = str(owner.id)
        sess['_fresh'] = True

    response = client.get("/site-yonetimi?tab=genel")
    page = response.data.decode("utf-8")

    assert response.status_code == 200
    assert 'name="footer_brand_kicker"' in page
    assert 'name="footer_brand_title"' in page
    assert 'name="footer_brand_description"' in page
    assert 'name="footer_contact_kicker"' in page
    assert 'name="footer_contact_title"' in page
    assert 'name="footer_contact_description"' in page
    assert 'name="footer_contact_email"' in page
    assert 'name="footer_copyright"' in page
    assert 'name="footer_bottom_slogan"' in page


def test_site_settings_page_uses_footer_fallbacks_when_db_empty(client, app):
    app.config['WTF_CSRF_ENABLED'] = False

    from extensions import db
    from tests.factories import KullaniciFactory

    owner = KullaniciFactory(rol="sistem_sorumlusu")
    db.session.add(owner)
    db.session.commit()

    with client.session_transaction() as sess:
        sess['_user_id'] = str(owner.id)
        sess['_fresh'] = True

    response = client.get("/site-yonetimi?tab=genel")
    page = response.data.decode("utf-8")

    assert response.status_code == 200
    assert 'name="footer_brand_kicker"' in page
    assert 'value="ARFF SAR"' in page
    assert 'name="footer_brand_title"' in page
    assert 'value="ARFF Özel Arama Kurtarma Timi"' in page
    assert 'name="footer_contact_email"' in page
    assert 'value="iletisim@sarx.org"' in page
    assert 'name="footer_bottom_slogan"' in page
    assert 'Gönüllü tim ruhu, sade iletişim ve hazır koordinasyon' in page


def test_site_settings_backfills_public_menu_records_without_duplicates(client, app):
    app.config['WTF_CSRF_ENABLED'] = False

    from extensions import db
    from models import NavMenu
    from tests.factories import KullaniciFactory

    owner = KullaniciFactory(rol="sistem_sorumlusu")
    db.session.add(owner)
    db.session.commit()

    with client.session_transaction() as sess:
        sess['_user_id'] = str(owner.id)
        sess['_fresh'] = True

    first_response = client.get("/site-yonetimi?tab=icerik")
    first_page = first_response.data.decode("utf-8")

    assert first_response.status_code == 200
    assert "Menü kaydı yok." not in first_page
    assert "Anasayfa" in first_page
    assert "/hakkimizda/biz-kimiz" in first_page
    assert "/faaliyetlerimiz/tatbikatlar" in first_page

    first_count = NavMenu.query.count()
    assert first_count >= 6

    second_response = client.get("/site-yonetimi?tab=icerik")
    assert second_response.status_code == 200
    assert NavMenu.query.count() == first_count
