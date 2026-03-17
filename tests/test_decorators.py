import pytest
from tests.factories import KullaniciFactory
from extensions import db

def test_roles_required_decorator(client, app):
    user = KullaniciFactory(rol="personel")
    db.session.commit()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True

    # Personel olarak admin sayfasına git
    response = client.get('/kullanicilar') 
    
    # ✅ DÜZELTME: Eğer dekoratörün yönlendirme yapıyorsa 302 beklemeliyiz
    # Veya yönlendirildiği yerin login/dashboard olduğunu doğrulamalıyız.
    assert response.status_code in [302, 403] 
    
    if response.status_code == 302:
        # Yetkisiz olduğu için bir yere fırlatıldı mı?
        assert response.location.endswith('/') or 'login' in response.location