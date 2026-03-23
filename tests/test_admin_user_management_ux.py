from decorators import update_user_permission_overrides
from extensions import db
from tests.factories import HavalimaniFactory, KullaniciFactory


def _login(client, user_id):
    with client.session_transaction() as session:
        session.clear()
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def _extract_select_markup(html, element_id):
    start = html.index(f'<select id="{element_id}"')
    end = html.index("</select>", start)
    return html[start:end]


def test_selected_user_loads_current_role_and_permission_overrides(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-ux@sarx.com")
        staff = KullaniciFactory(
            rol="bakim_sorumlusu",
            is_deleted=False,
            tam_ad="Bakım Uzmanı",
            kullanici_adi="maint-ux@sarx.com",
            havalimani=airport,
        )
        db.session.add_all([airport, owner, staff])
        db.session.flush()
        update_user_permission_overrides(staff.id, ["inventory.export"], ["logs.view"])
        db.session.commit()
        owner_id = owner.id
        staff_id = staff.id

    _login(client, owner_id)
    response = client.get(f"/kullanicilar?user_id={staff_id}")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert f'data-selected-user-id="{staff_id}"' in html
    assert 'value="bakim_sorumlusu" selected' in html
    assert 'name="allow_permissions" value="inventory.export" checked' in html
    assert 'name="deny_permissions" value="logs.view" checked' in html


def test_user_management_renders_success_toast_after_create(client, app):
    with app.app_context():
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-toast@sarx.com")
        db.session.add(owner)
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    response = client.post(
        "/kullanici-ekle",
        data={
            "tam_ad": "Toast Kullanıcısı",
            "k_adi": "toast-user@sarx.com",
            "sifre": "GucluTest@123",
            "rol": "readonly",
            "h_id": "",
        },
        follow_redirects=True,
    )
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert 'class="toast-stack"' in html
    assert 'flash-msg flash-success' in html
    assert "TOAST KULLANICISI personeli sisteme eklendi." in html
    assert "Beklenmedik Bir Hata" not in html
    assert "Sistem bağlantı hatası oluştu." not in html


def test_user_management_renders_error_toast_for_invalid_selection(client, app):
    with app.app_context():
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-danger@sarx.com")
        db.session.add(owner)
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    response = client.get("/kullanicilar?user_id=999999")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert 'flash-msg flash-danger' in html
    assert "Yetkiniz olmayan kayıt görüntülenemedi." in html


def test_site_owner_can_see_all_users_across_airports(client, app):
    with app.app_context():
        erzurum = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        trabzon = HavalimaniFactory(ad="Trabzon Havalimanı", kodu="TZX")
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-all@sarx.com")
        local_user = KullaniciFactory(
            rol="bakim_sorumlusu",
            is_deleted=False,
            tam_ad="Erzurum Personeli",
            kullanici_adi="erzurum@sarx.com",
            havalimani=erzurum,
        )
        remote_user = KullaniciFactory(
            rol="depo_sorumlusu",
            is_deleted=False,
            tam_ad="Trabzon Personeli",
            kullanici_adi="trabzon@sarx.com",
            havalimani=trabzon,
        )
        db.session.add_all([erzurum, trabzon, owner, local_user, remote_user])
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    response = client.get("/kullanicilar")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Erzurum Personeli" in html
    assert "Trabzon Personeli" in html


def test_non_owner_user_management_scope_is_limited_to_same_airport(client, app):
    with app.app_context():
        erzurum = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        trabzon = HavalimaniFactory(ad="Trabzon Havalimanı", kodu="TZX")
        admin_user = KullaniciFactory(
            rol="admin",
            is_deleted=False,
            tam_ad="Erzurum Yonetici",
            kullanici_adi="admin-erzurum@sarx.com",
            havalimani=erzurum,
        )
        local_user = KullaniciFactory(
            rol="bakim_sorumlusu",
            is_deleted=False,
            tam_ad="Ayni Havalimani Personeli",
            kullanici_adi="local@sarx.com",
            havalimani=erzurum,
        )
        remote_user = KullaniciFactory(
            rol="bakim_sorumlusu",
            is_deleted=False,
            tam_ad="Diger Havalimani Personeli",
            kullanici_adi="remote@sarx.com",
            havalimani=trabzon,
        )
        db.session.add_all([erzurum, trabzon, admin_user, local_user, remote_user])
        db.session.commit()
        admin_user_id = admin_user.id
        remote_user_id = remote_user.id

    _login(client, admin_user_id)
    response = client.get(f"/kullanicilar?user_id={remote_user_id}")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Ayni Havalimani Personeli" in html
    assert "Diger Havalimani Personeli" not in html
    assert "Yetkiniz olmayan kayıt görüntülenemedi." in html


def test_role_filter_limits_users_and_displays_selected_role(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-filter@sarx.com")
        maintenance_user = KullaniciFactory(
            rol="bakim_sorumlusu",
            is_deleted=False,
            tam_ad="Bakim Ekibi",
            kullanici_adi="bakim@sarx.com",
            havalimani=airport,
        )
        warehouse_user = KullaniciFactory(
            rol="depo_sorumlusu",
            is_deleted=False,
            tam_ad="Depo Ekibi",
            kullanici_adi="depo@sarx.com",
            havalimani=airport,
        )
        db.session.add_all([airport, owner, maintenance_user, warehouse_user])
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    response = client.get("/kullanicilar?role=bakim_sorumlusu")
    html = response.data.decode("utf-8")
    quick_select_html = _extract_select_markup(html, "userQuickSelect")

    assert response.status_code == 200
    assert "Bakim Ekibi" in html
    assert "Depo Ekibi" not in html
    assert "Rol: Bakım Sorumlusu" in html
    assert "Bakim Ekibi" in quick_select_html
    assert "Depo Ekibi" not in quick_select_html


def test_airport_filter_limits_users_and_displays_selected_airport(client, app):
    with app.app_context():
        erzurum = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        trabzon = HavalimaniFactory(ad="Trabzon Havalimanı", kodu="TZX")
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-airport@sarx.com")
        erzurum_user = KullaniciFactory(
            rol="bakim_sorumlusu",
            is_deleted=False,
            tam_ad="Erzurum Teknisyeni",
            kullanici_adi="erzurum-filter@sarx.com",
            havalimani=erzurum,
        )
        trabzon_user = KullaniciFactory(
            rol="depo_sorumlusu",
            is_deleted=False,
            tam_ad="Trabzon Depo",
            kullanici_adi="trabzon-filter@sarx.com",
            havalimani=trabzon,
        )
        db.session.add_all([erzurum, trabzon, owner, erzurum_user, trabzon_user])
        db.session.commit()
        owner_id = owner.id
        erzurum_id = erzurum.id

    _login(client, owner_id)
    response = client.get(f"/kullanicilar?airport_id={erzurum_id}")
    html = response.data.decode("utf-8")
    quick_select_html = _extract_select_markup(html, "userQuickSelect")

    assert response.status_code == 200
    assert "Erzurum Teknisyeni" in html
    assert "Trabzon Depo" not in html
    assert "Havalimanı: Erzurum Havalimanı" in html
    assert "Erzurum Teknisyeni" in quick_select_html
    assert "Trabzon Depo" not in quick_select_html


def test_status_filter_returns_archived_users(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-status@sarx.com")
        active_user = KullaniciFactory(
            rol="bakim_sorumlusu",
            is_deleted=False,
            tam_ad="Aktif Kullanıcı",
            kullanici_adi="aktif@sarx.com",
            havalimani=airport,
        )
        archived_user = KullaniciFactory(
            rol="depo_sorumlusu",
            is_deleted=True,
            tam_ad="Arşiv Kullanıcısı",
            kullanici_adi="arsiv@sarx.com",
            havalimani=airport,
        )
        db.session.add_all([airport, owner, active_user, archived_user])
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    response = client.get("/kullanicilar?status=archived")
    html = response.data.decode("utf-8")
    quick_select_html = _extract_select_markup(html, "userQuickSelect")

    assert response.status_code == 200
    assert "Arşiv Kullanıcısı" in html
    assert "Aktif Kullanıcı" not in html
    assert 'value="archived" selected' in html
    assert "Arşiv Kullanıcısı" in quick_select_html
    assert "Aktif Kullanıcı" not in quick_select_html


def test_combined_filters_reduce_user_list_and_update_result_summary(client, app):
    with app.app_context():
        erzurum = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        trabzon = HavalimaniFactory(ad="Trabzon Havalimanı", kodu="TZX")
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-combined@sarx.com")
        matching_user = KullaniciFactory(
            rol="bakim_sorumlusu",
            is_deleted=False,
            tam_ad="Usta Teknisyen",
            kullanici_adi="usta@sarx.com",
            havalimani=erzurum,
        )
        wrong_airport = KullaniciFactory(
            rol="bakim_sorumlusu",
            is_deleted=False,
            tam_ad="Usta Trabzon",
            kullanici_adi="usta-trabzon@sarx.com",
            havalimani=trabzon,
        )
        wrong_role = KullaniciFactory(
            rol="depo_sorumlusu",
            is_deleted=False,
            tam_ad="Usta Depo",
            kullanici_adi="usta-depo@sarx.com",
            havalimani=erzurum,
        )
        archived_match = KullaniciFactory(
            rol="bakim_sorumlusu",
            is_deleted=True,
            tam_ad="Usta Arşiv",
            kullanici_adi="usta-arsiv@sarx.com",
            havalimani=erzurum,
        )
        db.session.add_all([erzurum, trabzon, owner, matching_user, wrong_airport, wrong_role, archived_match])
        db.session.commit()
        owner_id = owner.id
        erzurum_id = erzurum.id

    _login(client, owner_id)
    response = client.get(
        f"/kullanicilar?q=usta&role=bakim_sorumlusu&airport_id={erzurum_id}&status=active"
    )
    html = response.data.decode("utf-8")
    quick_select_html = _extract_select_markup(html, "userQuickSelect")

    assert response.status_code == 200
    assert "Usta Teknisyen" in html
    assert "Usta Trabzon" not in html
    assert "Usta Depo" not in html
    assert "Usta Arşiv" not in html
    assert 'data-result-count="1"' in html
    assert "1 kayıt filtreyle listeleniyor" in html
    assert "Arama: usta" in html
    assert "Rol: Bakım Sorumlusu" in html
    assert "Havalimanı: Erzurum Havalimanı" in html
    assert "Usta Teknisyen" in quick_select_html
    assert "Usta Trabzon" not in quick_select_html


def test_empty_state_renders_when_filters_return_no_users(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-empty@sarx.com")
        staff = KullaniciFactory(
            rol="bakim_sorumlusu",
            is_deleted=False,
            tam_ad="Mevcut Personel",
            kullanici_adi="mevcut@sarx.com",
            havalimani=airport,
        )
        db.session.add_all([airport, owner, staff])
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    response = client.get("/kullanicilar?q=olmayan-sonuc")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert 'id="userServerEmpty"' in html
    assert "Seçili filtrelerle kullanıcı bulunamadı" in html
    assert 'id="userQuickSelect" class="form-control" aria-label="Kullanıcı seç" disabled' in html
    assert 'data-result-count="0"' in html


def test_detail_panel_is_rendered_after_filter_and_selection_blocks(client, app):
    with app.app_context():
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-layout@sarx.com")
        db.session.add(owner)
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    response = client.get("/kullanicilar")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Filtrele ve kullanıcıyı bul" in html
    assert "Kullanıcı seç" in html
    assert "Detay ve yetki düzenleme" in html
    assert html.index('class="panel filter-panel stage-accordion"') < html.index('class="panel user-directory-panel stage-accordion"')
    assert html.index('class="panel user-directory-panel stage-accordion"') < html.index('id="userDetailPanel"')
    assert html.index('id="userDetailPanel"') < html.index('id="newUserPanel"')
    assert 'data-filter-summary' in html
    assert 'data-detail-empty-state' in html
    assert html.count('data-stage-accordion') >= 3


def test_user_selector_hides_email_and_shows_name_airport_and_role(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-selector@sarx.com")
        staff = KullaniciFactory(
            rol="bakim_sorumlusu",
            is_deleted=False,
            tam_ad="Bakım Uzmanı",
            kullanici_adi="maint-selector@sarx.com",
            havalimani=airport,
        )
        db.session.add_all([airport, owner, staff])
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    response = client.get("/kullanicilar")
    html = response.data.decode("utf-8")
    quick_select_html = _extract_select_markup(html, "userQuickSelect")

    assert response.status_code == 200
    assert "Bakım Uzmanı • Erzurum Havalimanı • Bakım Sorumlusu" in quick_select_html
    assert "maint-selector@sarx.com" not in quick_select_html


def test_user_cards_render_core_identity_fields_cleanly(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-card@sarx.com")
        staff = KullaniciFactory(
            rol="bakim_sorumlusu",
            is_deleted=False,
            tam_ad="Kart Kullanıcısı",
            kullanici_adi="card-user@sarx.com",
            havalimani=airport,
        )
        db.session.add_all([airport, owner, staff])
        db.session.commit()
        owner_id = owner.id
        staff_id = staff.id

    _login(client, owner_id)
    response = client.get("/kullanicilar")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert f'data-user-card="{staff_id}"' in html
    assert "Kart Kullanıcısı" in html
    assert "card-user@sarx.com" in html
    assert "Havalimanı" in html
    assert "Rol" in html
    assert "Bakım Sorumlusu" in html


def test_user_management_renders_login_email_label_in_create_and_edit_forms(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-label@sarx.com")
        staff = KullaniciFactory(
            rol="bakim_sorumlusu",
            is_deleted=False,
            tam_ad="Etiket Kullanıcısı",
            kullanici_adi="etiket@sarx.com",
            havalimani=airport,
        )
        db.session.add_all([airport, owner, staff])
        db.session.commit()
        owner_id = owner.id
        staff_id = staff.id

    _login(client, owner_id)
    response = client.get(f"/kullanicilar?user_id={staff_id}")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert html.count("Giriş E-postası") >= 2
    assert "Bu alan kullanıcının sisteme girişte kullandığı e-posta adresidir." in html
    assert "Kullanıcı Adı" not in html
    assert html.count('type="email"') >= 2


def test_override_summary_is_split_into_allowed_and_withdrawn_sections(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-override@sarx.com")
        staff = KullaniciFactory(
            rol="bakim_sorumlusu",
            is_deleted=False,
            tam_ad="Override Kullanıcısı",
            kullanici_adi="override@sarx.com",
            havalimani=airport,
        )
        db.session.add_all([airport, owner, staff])
        db.session.flush()
        update_user_permission_overrides(staff.id, ["inventory.export"], ["logs.view"])
        db.session.commit()
        owner_id = owner.id
        staff_id = staff.id

    _login(client, owner_id)
    response = client.get(f"/kullanicilar?user_id={staff_id}")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert 'data-override-summary="allow"' in html
    assert 'data-override-summary="deny"' in html
    assert "Bu kullanıcıya ek olarak verilenler" in html
    assert "Bu kullanıcıdan özellikle kaldırılanlar" in html
    assert "İzin Verilenler" in html
    assert "Geri Çekilenler" in html


def test_override_summary_empty_states_are_rendered_cleanly(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-emptyoverride@sarx.com")
        staff = KullaniciFactory(
            rol="bakim_sorumlusu",
            is_deleted=False,
            tam_ad="Boş Override Kullanıcısı",
            kullanici_adi="empty-override@sarx.com",
            havalimani=airport,
        )
        db.session.add_all([airport, owner, staff])
        db.session.commit()
        owner_id = owner.id
        staff_id = staff.id

    _login(client, owner_id)
    response = client.get(f"/kullanicilar?user_id={staff_id}")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Ek özel izin yok." in html
    assert "Geri çekilen izin yok." in html


def test_detail_form_is_grouped_into_clear_sections(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-sections@sarx.com")
        staff = KullaniciFactory(
            rol="bakim_sorumlusu",
            is_deleted=False,
            tam_ad="Bölüm Kullanıcısı",
            kullanici_adi="section-user@sarx.com",
            havalimani=airport,
            telefon_numarasi="+905551112233",
        )
        db.session.add_all([airport, owner, staff])
        db.session.commit()
        owner_id = owner.id
        staff_id = staff.id

    _login(client, owner_id)
    response = client.get(f"/kullanicilar?user_id={staff_id}")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Temel bilgiler" in html
    assert "Rol ve havalimanı" in html
    assert "Telefon / iletişim" in html
    assert "Override özeti" in html
    assert "Yetki blokları" in html


def test_site_owner_can_view_phone_number_field(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-phone@sarx.com")
        staff = KullaniciFactory(
            rol="bakim_sorumlusu",
            is_deleted=False,
            tam_ad="Telefonlu Personel",
            kullanici_adi="phone-user@sarx.com",
            havalimani=airport,
            telefon_numarasi="+905551112233",
        )
        db.session.add_all([airport, owner, staff])
        db.session.commit()
        owner_id = owner.id
        staff_id = staff.id

    _login(client, owner_id)
    owner_response = client.get(f"/kullanicilar?user_id={staff_id}")
    owner_html = owner_response.data.decode("utf-8")

    assert owner_response.status_code == 200
    assert 'name="telefon_numarasi"' in owner_html
    assert "+905551112233" in owner_html


def test_non_owner_cannot_view_phone_number_field(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        admin_user = KullaniciFactory(
            rol="admin",
            is_deleted=False,
            kullanici_adi="admin-phone@sarx.com",
            havalimani=airport,
        )
        staff = KullaniciFactory(
            rol="bakim_sorumlusu",
            is_deleted=False,
            tam_ad="Telefonlu Personel",
            kullanici_adi="phone-user@sarx.com",
            havalimani=airport,
            telefon_numarasi="+905551112233",
        )
        db.session.add_all([airport, admin_user, staff])
        db.session.commit()
        admin_user_id = admin_user.id
        staff_id = staff.id

    _login(client, admin_user_id)
    response = client.get(f"/kullanicilar?user_id={staff_id}")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert 'name="telefon_numarasi"' not in html
    assert "+905551112233" not in html


def test_phone_number_is_saved_and_success_toasts_are_rendered(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-save@sarx.com")
        staff = KullaniciFactory(
            rol="bakim_sorumlusu",
            is_deleted=False,
            tam_ad="Kayit Personeli",
            kullanici_adi="save-user@sarx.com",
            havalimani=airport,
        )
        db.session.add_all([airport, owner, staff])
        db.session.commit()
        airport_id = airport.id
        owner_id = owner.id
        staff_id = staff.id

    _login(client, owner_id)
    response = client.post(
        f"/kullanici-guncelle/{staff_id}",
        data={
            "tam_ad": "Kayit Personeli",
            "k_adi": "save-user@sarx.com",
            "rol": "bakim_sorumlusu",
            "h_id": str(airport_id),
            "telefon_numarasi": "+90 555 111 22 33",
        },
        follow_redirects=True,
    )
    html = response.data.decode("utf-8")

    with app.app_context():
        updated_staff = db.session.get(type(staff), staff_id)
        assert updated_staff.telefon_numarasi == "+905551112233"

    assert response.status_code == 200
    assert "Kullanıcı yetkileri güncellendi." in html
    assert "Telefon numarası kaydedildi." in html
    assert 'flash-msg flash-success' in html


def test_new_user_panel_renders_as_collapsed_details_panel(client, app):
    with app.app_context():
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-newpanel@sarx.com")
        db.session.add(owner)
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    response = client.get("/kullanicilar")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert '<details class="panel new-user-panel" id="newUserPanel">' in html
    assert 'id="newUserSummaryLabel">Formu aç<' in html
    assert 'data-password-guidance' in html
    assert 'data-password-rule="special"' in html
    assert 'data-close-new-user-panel' in html


def test_user_management_inputs_render_validation_hooks(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-hooks@sarx.com")
        staff = KullaniciFactory(
            rol="bakim_sorumlusu",
            is_deleted=False,
            tam_ad="Doğrulama Kullanıcısı",
            kullanici_adi="hooks-user@sarx.com",
            havalimani=airport,
            telefon_numarasi="+905551112233",
        )
        db.session.add_all([airport, owner, staff])
        db.session.commit()
        owner_id = owner.id
        staff_id = staff.id

    _login(client, owner_id)
    response = client.get(f"/kullanicilar?user_id={staff_id}")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert 'data-uppercase-name' in html
    assert 'data-email-input' in html
    assert 'data-phone-input' in html
    assert 'inputmode="numeric"' in html
    assert 'autocomplete="tel"' in html
    assert '+90 5__ ___ __ __' in html


def test_invalid_email_is_rejected_in_user_create_form(client, app):
    with app.app_context():
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-invalidmail@sarx.com")
        db.session.add(owner)
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    response = client.post(
        "/kullanici-ekle",
        data={
            "tam_ad": "Hatali Mail",
            "k_adi": "hatali-mail",
            "sifre": "GucluTest@123",
            "rol": "readonly",
            "h_id": "",
        },
        follow_redirects=True,
    )
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Geçerli bir e-posta adresi girin." in html


def test_roles_page_renders_row_action_alignment_fix(client, app):
    with app.app_context():
        owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-rolecss@sarx.com")
        db.session.add(owner)
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    response = client.get("/admin/roles")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert ".row-actions:not(td)" in html
    assert "td.row-actions, .data-table td.row-actions" in html
