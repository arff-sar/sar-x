from extensions import db
from tests.factories import HavalimaniFactory, KullaniciFactory, KutuFactory, MalzemeFactory


def _login(client, user_id):
    with client.session_transaction() as session:
        session.clear()
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_login_page_contains_mobile_friendly_captcha_and_actions_rules(client):
    response = client.get("/login")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert ".captcha-box { grid-template-columns: minmax(0, 1fr) 42px 124px; gap: 6px; }" in html
    assert ".captcha-input-shell { grid-column: 3; }" in html
    assert "@media (max-width: 460px)" in html
    assert ".captcha-input { font-size: 14.5px !important; letter-spacing: .04em; }" in html
    assert ".account-actions-row { gap: 8px; margin: 2px 0 8px; }" in html
    assert ".forgot-password-link { min-height: 40px; border-radius: 10px;" in html


def test_dashboard_page_contains_mobile_compaction_rules(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Samsun Havalimanı", kodu="SZF")
        user = KullaniciFactory(rol="sahip", havalimani=airport, is_deleted=False)
        db.session.add_all([airport, user])
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    response = client.get("/dashboard")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert 'class="dashboard-actions"' in html
    assert 'class="dashboard-sections"' in html
    assert "sarx.sidebar.open-group" in html
    assert "if (mobileSidebarMedia.matches)" in html
    assert ".quick-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));" in html
    assert "@media (max-width: 420px)" in html


def test_zimmet_page_contains_mobile_selection_rules(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Gaziantep Havalimanı", kodu="GZT")
        box = KutuFactory(kodu="K-GZT-1", havalimani=airport)
        owner = KullaniciFactory(rol="sahip", havalimani=airport, is_deleted=False, kullanici_adi="owner-mobile@sarx.com")
        recipient = KullaniciFactory(
            rol="personel",
            havalimani=airport,
            is_deleted=False,
            tam_ad="Mobil Personel",
            kullanici_adi="mobile-person@sarx.com",
        )
        material = MalzemeFactory(ad="Koruyucu Maske", seri_no="MASK-01", stok_miktari=5, kutu=box, havalimani=airport)
        db.session.add_all([airport, box, owner, recipient, material])
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    response = client.get("/zimmetler")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "@media (max-width: 680px)" in html
    assert ".choice-grid { max-height:none; overflow:visible; }" in html
    assert ".selection-remove-btn," in html
    assert ".assignment-submit-row .btn," in html


def test_public_shell_contains_mobile_nav_and_footer_guards(client):
    response = client.get("/")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "max-height: calc(100svh - 104px);" in html
    assert 'shell.querySelectorAll("a")' in html
    assert ".public-copy { flex-direction: column; align-items: flex-start; }" in html
