import pytest
from tests.factories import KullaniciFactory, HavalimaniFactory
from extensions import db

def test_admin_user_management(client, app):
    admin = KullaniciFactory(rol="sistem_sorumlusu", kullanici_adi="owner-admin-test@sarx.com")
    db.session.add(admin)
    db.session.commit() # ✅ Commit şart
    
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin.id)
        sess['_fresh'] = True

    h = HavalimaniFactory(kodu="TEST-H")
    db.session.add(h)
    db.session.commit()
    
    response = client.post('/kullanici-ekle', data={
        'tam_ad': 'Yeni Personel',
        'k_adi': 'yeni-personel@test.com',
        'rol': 'ekip_uyesi',
        'h_id': h.id,
        'sifre': 'Test1234!'
    }, follow_redirects=True) # ✅ Dashboard veya Liste yönlendirmesini takip et
    
    assert response.status_code == 200
    with app.app_context():
        created = KullaniciFactory._meta.sqlalchemy_session.query(KullaniciFactory._meta.model).filter_by(kullanici_adi='yeni-personel@test.com').first()
        assert created is not None
        assert created.rol == "ekip_uyesi"

def test_admin_havalimani_management(client, app):
    admin = KullaniciFactory(rol="sistem_sorumlusu", kullanici_adi="owner-airport-test@sarx.com")
    db.session.add(admin)
    db.session.commit()
    
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin.id)
        sess['_fresh'] = True

    response = client.post('/havalimanlari', data={
        'islem': 'ekle',
        'ad': 'Yeni Test Limanı',
        'kodu': 'YTL'
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert "YTL" in response.data.decode('utf-8')
