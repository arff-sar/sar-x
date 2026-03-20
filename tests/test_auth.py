import pytest
from tests.factories import KullaniciFactory
from extensions import db
from werkzeug.security import generate_password_hash
from flask import url_for, current_app
from itsdangerous import URLSafeTimedSerializer
from models import LoginVisualChallenge


def _extract_challenge_answer(client, app):
    client.get("/login")
    with client.session_transaction() as session:
        token = session.get("login_visual_captcha_token")
    assert token
    with app.app_context():
        challenge = LoginVisualChallenge.query.filter_by(token=token, invalidated_at=None).first()
        if challenge:
            return challenge.code
        fallback_store = app.extensions.get("login_visual_challenge_store", {})
        fallback = fallback_store.get(token)
        assert fallback is not None
        return fallback["code"]

def test_login_page_loads(client):
    response = client.get('/login')
    assert response.status_code == 200
    assert "Giriş" in response.data.decode('utf-8')
    assert "GÜVENLİK DOĞRULAMASI" in response.data.decode('utf-8')

def test_login_success(client, app):
    app.config['WTF_CSRF_ENABLED'] = False 
    
    user = KullaniciFactory(kullanici_adi="admin@sarx.com", is_deleted=False, rol="sahip")
    user.sifre_hash = generate_password_hash('123456', method='pbkdf2:sha256') 
    db.session.add(user)
    db.session.commit() 
    answer = _extract_challenge_answer(client, app)
    response = client.post('/login', data={
        'kullanici_adi': 'admin@sarx.com',
        'sifre': '123456',
        'security_verification': answer,
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
    answer = _extract_challenge_answer(client, app)
    response = client.post('/login', data={
        'kullanici_adi': 'deleted@sarx.com',
        'sifre': '123456',
        'security_verification': answer,
    }, follow_redirects=True) 
    
    assert response.status_code == 200
    assert "Şifre veya Kullanıcı Adı yanlış" in response.data.decode('utf-8')

# --- YENİ EKLEMELER ---

def test_logout(client, app):
    """Sisteme giriş yapmış bir kullanıcının güvenli çıkış yapabilmesi"""
    app.config['WTF_CSRF_ENABLED'] = False
    user = KullaniciFactory(kullanici_adi="cikis@sarx.com", is_deleted=False)
    db.session.add(user)
    db.session.commit()

    # Önce giriş yapalım
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True

    response = client.post('/logout', follow_redirects=True)
    assert response.status_code == 200
    assert response.request.path == '/login'
    
    # ✅ DÜZELTME: "yaptı" yerine "yapıldı" olarak güncellendi
    data_str = response.data.decode('utf-8')
    assert "güvenli çıkış yapıldı" in data_str
    assert 'data-auto-dismiss="4200"' in data_str
    assert 'login-toast login-toast-success' in data_str


def test_logout_clears_remember_me_and_stays_on_login(client, app):
    app.config['WTF_CSRF_ENABLED'] = False
    user = KullaniciFactory(kullanici_adi="remember-logout@sarx.com", is_deleted=False, rol="sahip")
    user.sifre_hash = generate_password_hash('123456', method='pbkdf2:sha256')
    db.session.add(user)
    db.session.commit()

    answer = _extract_challenge_answer(client, app)
    login_response = client.post('/login', data={
        'kullanici_adi': 'remember-logout@sarx.com',
        'sifre': '123456',
        'security_verification': answer,
        'remember_me': 'on',
    }, follow_redirects=True)

    assert login_response.status_code == 200
    assert login_response.request.path == '/dashboard'

    logout_response = client.post('/logout', follow_redirects=True)
    html = logout_response.data.decode('utf-8')

    assert logout_response.status_code == 200
    assert logout_response.request.path == '/login'
    assert "güvenli çıkış yapıldı" in html
    assert 'data-auto-dismiss="4200"' in html


def test_logout_rejects_get_method(client, app):
    app.config['WTF_CSRF_ENABLED'] = False
    response = client.get('/logout', follow_redirects=False)
    assert response.status_code in [405, 302]

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
