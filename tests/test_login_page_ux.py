from extensions import db
from tests.factories import KullaniciFactory
from tests.test_auth import _extract_challenge_answer


def test_login_page_renders_updated_titles_and_footer_links(client):
    response = client.get("/login")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "ÖZEL ARFF ARAMA KURTARMA TİMİ" in html
    assert "ENVANTER YÖNETİM SİSTEMİ" in html
    assert "Bu sistem yalnızca mevcut arama kurtarma ekiplerinde görevli ARFF personelinin kullanımına açıktır." in html
    assert "arff.org.tr" in html
    assert "Mehmet CİNOÇEVİ tarafından geliştirilmiştir." in html
    assert "Anasayfaya Dön" not in html
    assert "html, body { overflow: hidden; }" in html


def test_login_page_renders_password_toggle_and_remember_me_layout(client):
    response = client.get("/login")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert 'id="passwordToggle"' in html
    assert 'aria-pressed="false"' in html
    assert 'class="remember-option"' in html
    assert 'name="remember_me"' in html
    assert 'maxlength="5"' in html
    assert "grid-template-columns: 148px 46px 132px;" in html
    assert "grid-template-columns: minmax(0, 1fr) 42px 124px;" in html
    assert 'Güvenlik nedeniyle "gov.tr" uzantılı e-posta adresleri kabul edilmemektedir.' in html
    assert "initGovTrEmailValidation" in html


def test_logout_flash_is_rendered_as_transient_login_toast(client, app):
    app.config["WTF_CSRF_ENABLED"] = False
    user = KullaniciFactory(kullanici_adi="logout-toast@sarx.com", is_deleted=False, rol="sahip")
    db.session.add(user)
    db.session.commit()

    answer = _extract_challenge_answer(client, app)
    login_response = client.post(
        "/login",
        data={
            "kullanici_adi": "logout-toast@sarx.com",
            "sifre": "123456",
            "security_verification": answer,
        },
        follow_redirects=True,
    )
    assert login_response.status_code == 200

    response = client.post("/logout", follow_redirects=True)
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert response.request.path == "/login"
    assert "Sistemden güvenli çıkış yapıldı." in html
    assert 'data-auto-dismiss="4200"' in html
    assert 'login-toast login-toast-success' in html
