import re
from unittest.mock import patch

from extensions import db
from models import EmailChangeToken, PushDeviceSubscription, UserNotificationPreference
from tests.factories import KullaniciFactory


def _login(client, user_id):
    with client.session_transaction() as session:
        session.clear()
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def _extract_verification_path(email_html):
    match = re.search(r'href="([^"]*/ayarlar/email-dogrula/[^"/<>]+)"', email_html)
    assert match is not None
    url = match.group(1)
    return re.sub(r"^https?://[^/]+", "", url)


def test_settings_page_renders_for_authenticated_user(client, app):
    with app.app_context():
        user = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="settings-owner@sarx.com")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    response = client.get("/ayarlar")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "E-posta Güncelleme" in html
    assert "Şifre Değiştirme" in html
    assert "Beden Bilgileri" in html
    assert "Bildirimler" in html
    assert 'id="shoeSize"' in html
    assert 'name="ayakkabi_numarasi"' in html
    assert "<select" in html


def test_settings_page_shows_passkey_management_when_enabled(client, app):
    app.config["PASSKEY_ENABLED"] = True
    with app.app_context():
        user = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="settings-passkey-on@sarx.com")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    response = client.get("/ayarlar")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Biyometrik / Passkey" in html
    assert 'id="settingsPasskeyRegisterButton"' in html
    assert 'id="settingsPasskeyList"' in html
    assert 'id="passkeyRegisterButton"' not in html
    assert 'id="passkeyManageButton"' not in html


def test_settings_page_hides_passkey_management_when_disabled(client, app):
    app.config["PASSKEY_ENABLED"] = False
    with app.app_context():
        user = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="settings-passkey-off@sarx.com")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    response = client.get("/ayarlar")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Biyometrik / Passkey" not in html
    assert 'id="settingsPasskeyList"' not in html


def test_email_change_request_waits_for_verification_before_updating_email(client, app):
    with app.app_context():
        user = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="mail-change@sarx.com")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    with patch("routes.auth.mail_gonder", return_value=True) as mocked_mail:
        response = client.post(
            "/ayarlar/email-degisiklik-talep",
            data={"yeni_eposta": "new-mail@sarx.com", "mevcut_sifre_email": "123456"},
            follow_redirects=True,
        )

    assert response.status_code == 200
    assert mocked_mail.call_count == 1

    with app.app_context():
        user = db.session.get(type(user), user_id)
        assert user.kullanici_adi == "mail-change@sarx.com"
        token_row = EmailChangeToken.query.filter_by(user_id=user_id, consumed_at=None).first()
        assert token_row is not None
        assert token_row.new_email == "new-mail@sarx.com"


def test_email_change_verification_updates_email_and_token_is_single_use(client, app):
    with app.app_context():
        user = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="mail-verify@sarx.com")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    with patch("routes.auth.mail_gonder", return_value=True) as mocked_mail:
        request_response = client.post(
            "/ayarlar/email-degisiklik-talep",
            data={"yeni_eposta": "verified-mail@sarx.com", "mevcut_sifre_email": "123456"},
            follow_redirects=True,
        )
        assert request_response.status_code == 200
        verify_path = _extract_verification_path(mocked_mail.call_args.args[2])

        verify_response = client.get(verify_path, follow_redirects=True)
        assert verify_response.status_code == 200
        assert mocked_mail.call_count == 2

        replay_response = client.get(verify_path, follow_redirects=True)
        assert replay_response.status_code == 200

    with app.app_context():
        user = db.session.get(type(user), user_id)
        assert user.kullanici_adi == "verified-mail@sarx.com"
        token_rows = EmailChangeToken.query.filter_by(user_id=user_id).all()
        assert token_rows
        assert all(row.consumed_at is not None for row in token_rows)


def test_password_change_requires_current_password_and_sends_mail(client, app):
    with app.app_context():
        user = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="password-change@sarx.com")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    with patch("routes.auth.mail_gonder", return_value=True) as mocked_mail:
        response = client.post(
            "/ayarlar/sifre-degistir",
            data={
                "mevcut_sifre": "123456",
                "yeni_sifre": "YeniSifre@1",
                "yeni_sifre_tekrar": "YeniSifre@1",
            },
            follow_redirects=True,
        )

    assert response.status_code == 200
    assert mocked_mail.call_count == 1

    with app.app_context():
        user = db.session.get(type(user), user_id)
        assert user.sifre_kontrol("YeniSifre@1") is True
        assert user.sifre_kontrol("123456") is False


def test_notification_preferences_reject_invalid_role_keys(client, app):
    with app.app_context():
        user = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="notif-invalid@sarx.com")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    response = client.post(
        "/ayarlar/bildirim-tercihleri",
        data={
            "client_mode": "standalone",
            "device_id": "deviceid1234567890",
            "pref_work_orders": "on",
            "pref_unauthorized": "on",
        },
        follow_redirects=True,
    )
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Rolünüz için geçersiz bildirim tercihi gönderildi." in html

    with app.app_context():
        assert UserNotificationPreference.query.filter_by(user_id=user_id).count() == 0


def test_notification_preferences_save_and_subscription_revoke_flow(client, app):
    with app.app_context():
        user = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="notif-save@sarx.com")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    save_response = client.post(
        "/ayarlar/bildirim-tercihleri",
        data={
            "client_mode": "standalone",
            "client_platform": "standalone",
            "device_id": "deviceid1234567890",
            "device_notifications_enabled": "on",
            "pref_work_orders": "on",
        },
        follow_redirects=True,
    )
    assert save_response.status_code == 200

    with app.app_context():
        preferences = UserNotificationPreference.query.filter_by(user_id=user_id).all()
        pref_map = {item.preference_key: item.is_enabled for item in preferences}
        assert "work_orders" in pref_map
        assert pref_map["work_orders"] is True
        assert any(key in pref_map for key in ("assignments", "maintenance", "calibration"))

        subscription = PushDeviceSubscription.query.filter_by(user_id=user_id, device_id="deviceid1234567890").first()
        assert subscription is not None
        assert subscription.is_active is True
        assert subscription.notification_enabled is True

    revoke_response = client.post(
        "/ayarlar/bildirim-abonelik-kaldir",
        data={
            "client_mode": "standalone",
            "device_id": "deviceid1234567890",
        },
        follow_redirects=True,
    )
    assert revoke_response.status_code == 200

    with app.app_context():
        subscription = PushDeviceSubscription.query.filter_by(user_id=user_id, device_id="deviceid1234567890").first()
        assert subscription is not None
        assert subscription.is_active is False
        assert subscription.notification_enabled is False


def test_notification_preference_update_blocked_for_desktop_context(client, app):
    with app.app_context():
        user = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="notif-desktop@sarx.com")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    response = client.post(
        "/ayarlar/bildirim-tercihleri",
        data={
            "device_id": "deviceid1234567890",
            "pref_work_orders": "on",
        },
        follow_redirects=False,
    )

    assert response.status_code == 403


def test_demo_settings_email_simulation_shows_verify_link_without_real_mail(client, app):
    app.config["DEMO_TOOLS_ENABLED"] = True
    with app.app_context():
        user = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="demo-mail@sarx.com")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    toggle = client.get("/ayarlar?demo_sim=1", follow_redirects=True)
    assert toggle.status_code == 200

    with patch("routes.auth.mail_gonder", return_value=True) as mocked_mail:
        response = client.post(
            "/ayarlar/email-degisiklik-talep",
            data={"yeni_eposta": "demo-verify@sarx.com", "mevcut_sifre_email": "123456"},
            follow_redirects=True,
        )

    html = response.data.decode("utf-8")
    assert response.status_code == 200
    assert mocked_mail.call_count == 0
    assert "Demo mod: doğrulama bağlantısı Ayarlar ekranında gösterildi" in html
    assert "E-posta değişikliğini doğrula" in html
    assert "/ayarlar/email-dogrula/" in html


def test_demo_settings_password_change_simulates_mail_only_when_demo_enabled(client, app):
    app.config["DEMO_TOOLS_ENABLED"] = True
    with app.app_context():
        user = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="demo-password@sarx.com")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    client.get("/ayarlar?demo_sim=1", follow_redirects=True)
    with patch("routes.auth.mail_gonder", return_value=True) as mocked_mail:
        response = client.post(
            "/ayarlar/sifre-degistir",
            data={
                "mevcut_sifre": "123456",
                "yeni_sifre": "YeniDemoSifre@1",
                "yeni_sifre_tekrar": "YeniDemoSifre@1",
            },
            follow_redirects=True,
        )

    html = response.data.decode("utf-8")
    assert response.status_code == 200
    assert mocked_mail.call_count == 0
    assert "Demo mod: şifre değişikliği bilgilendirme e-postası simüle edildi." in html


def test_notification_preferences_allow_demo_simulation_for_desktop_when_enabled(client, app):
    app.config["DEMO_TOOLS_ENABLED"] = True
    with app.app_context():
        user = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="notif-demo@sarx.com")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    client.get("/ayarlar?demo_sim=1", follow_redirects=True)
    response = client.post(
        "/ayarlar/bildirim-tercihleri",
        data={
            "device_id": "deviceid1234567890",
            "pref_work_orders": "on",
            "device_notifications_enabled": "on",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    with app.app_context():
        preference = UserNotificationPreference.query.filter_by(user_id=user_id, preference_key="work_orders").first()
        assert preference is not None
        assert preference.is_enabled is True


def test_settings_demo_panel_hidden_when_demo_tools_disabled(client, app):
    app.config["DEMO_TOOLS_ENABLED"] = False
    with app.app_context():
        user = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="demo-disabled@sarx.com")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    response = client.get("/ayarlar?demo_sim=1")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Demo/Test Simülasyon" not in html
