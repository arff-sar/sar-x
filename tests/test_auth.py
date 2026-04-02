import pytest
from unittest.mock import patch
from tests.factories import KullaniciFactory
from extensions import db
from werkzeug.security import generate_password_hash
from flask import url_for, current_app
from itsdangerous import SignatureExpired, URLSafeTimedSerializer
from models import LoginVisualChallenge
from routes import auth as auth_module


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


def test_client_ip_ignores_forwarded_header_when_proxy_trust_disabled(app):
    app.config["TRUST_PROXY_HEADERS"] = False
    app.config["TRUSTED_PROXY_IPS"] = ("127.0.0.1",)
    with app.test_request_context(
        "/login",
        headers={"X-Forwarded-For": "8.8.8.8"},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    ):
        assert auth_module._client_ip() == "127.0.0.1"


def test_client_ip_uses_forwarded_header_for_trusted_proxy(app):
    app.config["TRUST_PROXY_HEADERS"] = True
    app.config["TRUSTED_PROXY_IPS"] = ("127.0.0.1",)
    with app.test_request_context(
        "/login",
        headers={"X-Forwarded-For": "8.8.8.8, 127.0.0.1"},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    ):
        assert auth_module._client_ip() == "8.8.8.8"


def test_client_ip_rejects_forwarded_header_for_untrusted_proxy(app):
    app.config["TRUST_PROXY_HEADERS"] = True
    app.config["TRUSTED_PROXY_IPS"] = ("10.0.0.1",)
    with app.test_request_context(
        "/login",
        headers={"X-Forwarded-For": "8.8.8.8"},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    ):
        assert auth_module._client_ip() == "127.0.0.1"

def test_login_page_loads(client):
    response = client.get('/login')
    assert response.status_code == 200
    assert "Giriş" in response.data.decode('utf-8')
    assert "GÜVENLİK DOĞRULAMASI" in response.data.decode('utf-8')


def test_login_page_defaults_remember_me_for_mobile_and_pwa_continuity(client):
    response = client.get('/login')
    html = response.data.decode('utf-8')

    assert response.status_code == 200
    assert 'name="remember_me"' in html
    assert 'name="remember_me" value="on" checked' in html

def test_login_success(client, app):
    app.config['WTF_CSRF_ENABLED'] = False 
    
    user = KullaniciFactory(kullanici_adi="admin@sarx.com", is_deleted=False, rol="ekip_uyesi")
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


def test_login_success_for_user_without_airport_does_not_crash_dashboard(client, app):
    app.config['WTF_CSRF_ENABLED'] = False

    user = KullaniciFactory(kullanici_adi="no-airport@sarx.com", is_deleted=False, rol="ekip_uyesi")
    user.sifre_hash = generate_password_hash('123456', method='pbkdf2:sha256')
    db.session.add(user)
    db.session.commit()

    answer = _extract_challenge_answer(client, app)
    response = client.post('/login', data={
        'kullanici_adi': 'no-airport@sarx.com',
        'sifre': '123456',
        'security_verification': answer,
    }, follow_redirects=True)

    html = response.data.decode('utf-8')
    assert response.status_code == 200
    assert response.request.path == '/dashboard'
    assert "Atanmamış Birim" in html


def test_login_redirects_to_internal_next_target(client, app):
    app.config['WTF_CSRF_ENABLED'] = False

    user = KullaniciFactory(kullanici_adi="next-ok@sarx.com", is_deleted=False, rol="sahip")
    user.sifre_hash = generate_password_hash('123456', method='pbkdf2:sha256')
    db.session.add(user)
    db.session.commit()

    answer = _extract_challenge_answer(client, app)
    response = client.post('/login', data={
        'kullanici_adi': 'next-ok@sarx.com',
        'sifre': '123456',
        'security_verification': answer,
        'next': '/envanter',
    }, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers.get('Location', '').endswith('/envanter')


def test_login_rejects_external_next_target(client, app):
    app.config['WTF_CSRF_ENABLED'] = False

    user = KullaniciFactory(kullanici_adi="next-block@sarx.com", is_deleted=False, rol="sahip")
    user.sifre_hash = generate_password_hash('123456', method='pbkdf2:sha256')
    db.session.add(user)
    db.session.commit()

    answer = _extract_challenge_answer(client, app)
    response = client.post('/login', data={
        'kullanici_adi': 'next-block@sarx.com',
        'sifre': '123456',
        'security_verification': answer,
        'next': 'https://evil.example/phish',
    }, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers.get('Location', '').endswith('/dashboard')


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
    user = KullaniciFactory(kullanici_adi="remember-logout@sarx.com", is_deleted=False, rol="ekip_uyesi")
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


def test_logout_invalidates_auth_state_and_expires_remember_cookie(client, app):
    app.config['WTF_CSRF_ENABLED'] = False
    user = KullaniciFactory(kullanici_adi="remember-expire@sarx.com", is_deleted=False, rol="ekip_uyesi")
    user.sifre_hash = generate_password_hash('123456', method='pbkdf2:sha256')
    db.session.add(user)
    db.session.commit()

    answer = _extract_challenge_answer(client, app)
    login_response = client.post('/login', data={
        'kullanici_adi': 'remember-expire@sarx.com',
        'sifre': '123456',
        'security_verification': answer,
        'remember_me': 'on',
    }, follow_redirects=False)

    assert login_response.status_code == 302
    assert any(
        'remember_token=' in item and 'SameSite=Lax' in item
        for item in login_response.headers.getlist('Set-Cookie')
    )

    logout_response = client.post('/logout', follow_redirects=False)
    set_cookie_headers = logout_response.headers.getlist('Set-Cookie')

    assert logout_response.status_code == 302
    assert any('remember_token=;' in item for item in set_cookie_headers)
    assert any('Expires=Thu, 01 Jan 1970 00:00:00 GMT' in item for item in set_cookie_headers)

    with client.session_transaction() as sess:
        assert '_user_id' not in sess
        assert 'temporary_role_override' not in sess

    blocked = client.get('/dashboard', follow_redirects=False)
    assert blocked.status_code == 302
    assert '/login' in blocked.headers.get('Location', '')


def test_logout_rejects_get_method(client, app):
    app.config['WTF_CSRF_ENABLED'] = False
    response = client.get('/logout', follow_redirects=False)
    assert response.status_code in [405, 302]


def test_authenticated_user_can_fetch_csrf_token_from_api(client, app):
    user = KullaniciFactory(kullanici_adi="csrf-api@sarx.com", is_deleted=False, rol="sahip")
    db.session.add(user)
    db.session.commit()

    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True

    response = client.get("/api/csrf-token")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["status"] == "success"
    assert isinstance(payload.get("csrf_token"), str)
    assert len(payload["csrf_token"]) > 10


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


def test_sifre_sifirla_talep_unknown_user_returns_generic_response_without_mail(client, app):
    app.config['WTF_CSRF_ENABLED'] = False

    with patch('routes.auth.mail_gonder', return_value=True) as mocked_mail:
        response = client.post(
            '/sifre-sifirla-talep',
            data={'kullanici_adi': 'olmayan@sarx.com'},
            follow_redirects=True,
        )

    assert response.status_code == 200
    assert mocked_mail.call_count == 0
    assert "e-posta adresinize gönderildi" in response.data.decode('utf-8')


def test_sifre_sifirla_talep_internal_error_does_not_return_500(client, app):
    app.config['WTF_CSRF_ENABLED'] = False
    user = KullaniciFactory(kullanici_adi="broken@sarx.com", is_deleted=False)
    db.session.add(user)
    db.session.commit()

    with patch('routes.auth.mail_gonder', side_effect=RuntimeError("smtp down")):
        response = client.post(
            '/sifre-sifirla-talep',
            data={'kullanici_adi': 'broken@sarx.com'},
            follow_redirects=True,
        )

    assert response.status_code == 200
    html = response.data.decode('utf-8')
    assert "SAR-X-MAIL-4101" in html
    assert "Şifre sıfırlama isteği şu an gönderilemedi." in html

def test_sifre_sifirla_talep_uses_public_reset_base_url(client, app):
    app.config.update({
        'WTF_CSRF_ENABLED': False,
        'PASSWORD_RESET_BASE_URL': 'https://portal.sarx.com',
    })
    user = KullaniciFactory(kullanici_adi="link@sarx.com", is_deleted=False)
    db.session.add(user)
    db.session.commit()

    with patch('routes.auth.mail_gonder', return_value=True) as mocked_mail:
        response = client.post(
            '/sifre-sifirla-talep',
            data={'kullanici_adi': 'link@sarx.com'},
            base_url='http://127.0.0.1:5000',
            follow_redirects=True,
        )

    assert response.status_code == 200
    assert mocked_mail.call_count == 1
    email_html = mocked_mail.call_args.args[2]
    assert "https://portal.sarx.com/sifre-yenile/" in email_html
    assert "http://127.0.0.1:5000/sifre-yenile/" not in email_html


def test_sifre_sifirla_talep_uses_local_request_host_when_reset_base_url_is_not_configured(client, app):
    app.config.update({
        'WTF_CSRF_ENABLED': False,
        'PASSWORD_RESET_BASE_URL': '',
        'PUBLIC_BASE_URL': '',
    })
    user = KullaniciFactory(kullanici_adi="proxy@sarx.com", is_deleted=False)
    db.session.add(user)
    db.session.commit()

    with patch('routes.auth.mail_gonder', return_value=True) as mocked_mail:
        response = client.post(
            '/sifre-sifirla-talep',
            data={'kullanici_adi': 'proxy@sarx.com'},
            base_url='http://127.0.0.1:5000',
            follow_redirects=True,
        )

    assert response.status_code == 200
    assert mocked_mail.call_count == 1
    email_html = mocked_mail.call_args.args[2]
    assert "http://127.0.0.1:5000/sifre-yenile/" in email_html


def test_sifre_sifirla_talep_rejects_forwarded_host_fallback_without_configured_base_url(client, app):
    app.config.update({
        'WTF_CSRF_ENABLED': False,
        'PASSWORD_RESET_BASE_URL': '',
        'PUBLIC_BASE_URL': '',
    })
    user = KullaniciFactory(kullanici_adi="proxy-blocked@sarx.com", is_deleted=False)
    db.session.add(user)
    db.session.commit()

    with patch('routes.auth.mail_gonder', return_value=True) as mocked_mail:
        response = client.post(
            '/sifre-sifirla-talep',
            data={'kullanici_adi': 'proxy-blocked@sarx.com'},
            base_url='http://internal.service.local',
            headers={
                'X-Forwarded-Proto': 'https',
                'X-Forwarded-Host': 'sarx.example.com',
            },
            follow_redirects=True,
        )

    assert response.status_code == 200
    assert mocked_mail.call_count == 0
    html = response.data.decode('utf-8')
    assert "SAR-X-MAIL-4101" in html
    assert "Şifre sıfırlama isteği şu an gönderilemedi." in html


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
    old_password = "EskiSifre1!"
    new_password = "YeniSifre1!"
    user = KullaniciFactory(kullanici_adi=email, is_deleted=False, rol="ekip_uyesi", password=old_password)
    db.session.add(user)
    db.session.commit()

    serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])
    token = serializer.dumps(email, salt='sifre-sifirlama-tuzu')

    response = client.post(f'/sifre-yenile/{token}', data={
        'yeni_sifre': new_password
    }, follow_redirects=True)

    assert response.status_code == 200
    assert "güncellendi" in response.data.decode('utf-8')

    db.session.expire_all()
    refreshed_user = db.session.get(type(user), user.id)
    assert refreshed_user.sifre_kontrol(new_password)
    assert not refreshed_user.sifre_kontrol(old_password)

    answer = _extract_challenge_answer(client, app)
    login_response = client.post('/login', data={
        'kullanici_adi': email,
        'sifre': new_password,
        'security_verification': answer,
    }, follow_redirects=True)

    assert login_response.status_code == 200
    assert login_response.request.path == '/dashboard'


def test_sifre_yenile_token_is_single_use_after_password_change(client, app):
    app.config['WTF_CSRF_ENABLED'] = False
    email = "single-use@sarx.com"
    user = KullaniciFactory(kullanici_adi=email, is_deleted=False, rol="sahip", password="EskiSifre1!")
    db.session.add(user)
    db.session.commit()

    with app.app_context():
        token = auth_module._build_password_reset_token(user)

    response = client.post(
        f'/sifre-yenile/{token}',
        data={'yeni_sifre': 'YeniSifre1!'},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Şifreniz başarıyla güncellendi" in response.data.decode('utf-8')

    reused = client.get(f'/sifre-yenile/{token}', follow_redirects=True)
    assert reused.status_code == 200
    reused_html = reused.data.decode('utf-8')
    assert "SAR-X-AUTH-1301" in reused_html
    assert "Şifre sıfırlama bağlantısı geçersiz veya süresi dolmuş." in reused_html

def test_sifre_yenile_invalid_token(client, app):
    """Geçersiz veya bozuk token ile erişim denemesi"""
    response = client.get('/sifre-yenile/bu-gecersiz-bir-tokendir', follow_redirects=True)
    html = response.data.decode('utf-8')
    assert "SAR-X-AUTH-1301" in html
    assert "Şifre sıfırlama bağlantısı geçersiz veya süresi dolmuş." in html


def test_sifre_yenile_expired_token(client, app):
    with patch('routes.auth._get_password_reset_serializer') as mocked_serializer_factory:
        mocked_serializer_factory.return_value.loads.side_effect = SignatureExpired('expired')
        response = client.get('/sifre-yenile/suresi-dolmus-token', follow_redirects=True)

    assert response.status_code == 200
    html = response.data.decode('utf-8')
    assert "SAR-X-AUTH-1301" in html
    assert "Şifre sıfırlama bağlantısı geçersiz veya süresi dolmuş." in html


def test_sifre_yenile_invalid_password_feedback_is_rendered(client, app):
    app.config['WTF_CSRF_ENABLED'] = False
    email = "uyari@sarx.com"
    old_password = "EskiSifre1!"
    user = KullaniciFactory(kullanici_adi=email, is_deleted=False, password=old_password)
    db.session.add(user)
    db.session.commit()

    serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])
    token = serializer.dumps(email, salt='sifre-sifirlama-tuzu')

    response = client.post(
        f'/sifre-yenile/{token}',
        data={'yeni_sifre': 'zayif123'},
        follow_redirects=True,
    )

    assert response.status_code == 200
    html = response.data.decode('utf-8')
    assert "Yeni şifre en az 8 karakter uzunluğunda olmalı" in html

    db.session.expire_all()
    refreshed_user = db.session.get(type(user), user.id)
    assert refreshed_user.sifre_kontrol(old_password)


def test_login_normalizes_email_lookup_for_legacy_mixed_case_records(client, app):
    app.config['WTF_CSRF_ENABLED'] = False

    user = KullaniciFactory(
        kullanici_adi="  MehmetCinocevi@Gmail.com ",
        is_deleted=False,
        rol="ekip_uyesi",
    )
    user.sifre_hash = generate_password_hash('123456', method='pbkdf2:sha256')
    db.session.add(user)
    db.session.commit()

    answer = _extract_challenge_answer(client, app)
    response = client.post('/login', data={
        'kullanici_adi': 'mehmetcinocevi@gmail.com',
        'sifre': '123456',
        'security_verification': answer,
    }, follow_redirects=True)

    assert response.status_code == 200
    assert response.request.path == '/dashboard'
