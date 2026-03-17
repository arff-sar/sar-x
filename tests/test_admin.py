import pytest
from tests.factories import KullaniciFactory, HavalimaniFactory
from extensions import db

def test_admin_user_management(client, app):
    admin = KullaniciFactory(rol="sahip")
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
        'k_adi': 'personel@test.com',
        'rol': 'personel',
        'h_id': h.id,
        'sifre': '123456'
    }, follow_redirects=True) # ✅ Dashboard veya Liste yönlendirmesini takip et
    
    assert response.status_code == 200
    assert "Yeni Personel" in response.data.decode('utf-8')

def test_admin_havalimani_management(client, app):
    admin = KullaniciFactory(rol="sahip")
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