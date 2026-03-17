import pytest
from tests.factories import KullaniciFactory
from extensions import db
from werkzeug.security import generate_password_hash
from flask import url_for, current_app
from itsdangerous import URLSafeTimedSerializer

def test_login_page_loads(client):
    response = client.get('/login')
    assert response.status_code == 200
    assert "Giriş" in response.data.decode('utf-8')

def test_login_success(client, app):
    app.config['WTF_CSRF_ENABLED'] = False 
    
    user = KullaniciFactory(kullanici_adi="admin@sarx.com", is_deleted=False, rol="sahip")
    user.sifre_hash = generate_password_hash('123456', method='pbkdf2:sha256') 
    db.session.add(user)
    db.session.commit() 
    
    response = client.post('/login', data={
        'kullanici_adi': 'admin@sarx.com',
        'sifre': '123456'
    }, follow_redirects=True) 
    
    assert response.status_code == 200
    assert "Şifre veya Kullanıcı Adı yanlış" not in response.data.decode('utf-8')
    assert response.request.path == '/dashboard'

def test_deleted_user_cannot_login(client, app):
    app.config['WTF_CSRF_ENABLED'] = False 
    
    user = KullaniciFactory(kullanici_adi="deleted@sarx.com", is_deleted=True)
    user.sifre_hash = generate_password_hash('123456', method='pbkdf2:sha256')
    db.session.add(user)
    db.session.commit()
    
    response = client.post('/login', data={
        'kullanici_adi': 'deleted@sarx.com',
        'sifre': '123456'
    }, follow_redirects=True) 
    
    assert response.status_code == 200
    assert "Şifre veya Kullanıcı Adı yanlış" in response.data.decode('utf-8')

# --- YENİ EKLEMELER ---

def test_logout(client, app):
    """Sisteme giriş yapmış bir kullanıcının güvenli çıkış yapabilmesi"""
    user = KullaniciFactory(kullanici_adi="cikis@sarx.com", is_deleted=False)
    db.session.add(user)
    db.session.commit()

    # Önce giriş yapalım
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True

    response = client.get('/logout', follow_redirects=True)
    assert response.status_code == 200
    assert response.request.path == '/login'
    
    # ✅ DÜZELTME: "yaptı" yerine "yapıldı" olarak güncellendi
    data_str = response.data.decode('utf-8')
    assert "güvenli çıkış yapıldı" in data_str

def test_sifre_sifirla_talep_success(client, app):
    """Geçerli bir e-posta için şifre sıfırlama talebi"""
    app.config['WTF_CSRF_ENABLED'] = False
    user = KullaniciFactory(kullanici_adi="talep@sarx.com", is_deleted=False)
    db.session.add(user)
    db.session.commit()

    response = client.post('/sifre-sifirla-talep', data={
        'kullanici_adi': 'talep@sarx.com'
    }, follow_redirects=True)

    assert response.status_code == 200
    assert "e-posta adresinize gönderildi" in response.data.decode('utf-8')

def test_sifre_yenile_page_loads(client, app):
    """Geçerli bir token ile şifre yenileme sayfasının açılması"""
    email = "yenileme@sarx.com"
    serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])
    token = serializer.dumps(email, salt='sifre-sifirlama-tuzu')

    response = client.get(f'/sifre-yenile/{token}')
    assert response.status_code == 200
    assert email in response.data.decode('utf-8')

def test_sifre_yenile_success(client, app):
    app.config['WTF_CSRF_ENABLED'] = False
    email = "basarili@sarx.com"
    user = KullaniciFactory(kullanici_adi=email, is_deleted=False)
    db.session.add(user)
    db.session.commit()

    from itsdangerous import URLSafeTimedSerializer
    serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])
    token = serializer.dumps(email, salt='sifre-sifirlama-tuzu')

    response = client.post(f'/sifre-yenile/{token}', data={
        'yeni_sifre': 'yeni_sifre_123'
    }, follow_redirects=True)

    assert response.status_code == 200
    # ✅ ÇÖZÜM: "Şifreniz başarıyla güncellendi" mesajını ara
    assert "güncellendi" in response.data.decode('utf-8')

def test_sifre_yenile_invalid_token(client, app):
    """Geçersiz veya bozuk token ile erişim denemesi"""
    response = client.get('/sifre-yenile/bu-gecersiz-bir-tokendir', follow_redirects=True)
    assert "Geçersiz veya bozuk" in response.data.decode('utf-8')