from datetime import datetime

from extensions import db
from models import Announcement, HomeSection
from tests.factories import AnnouncementFactory, HomeSliderFactory, KullaniciFactory


def _login(client, user):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


def test_public_homepage_shows_only_active_sliders(client, app):
    active_slider = HomeSliderFactory(title="Aktif Slider", image_url="https://example.com/aktif.jpg", is_active=True)
    passive_slider = HomeSliderFactory(title="Pasif Slider", image_url="https://example.com/pasif.jpg", is_active=False)
    db.session.add_all([active_slider, passive_slider])
    db.session.commit()

    response = client.get("/")
    page = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "https://example.com/aktif.jpg" in page
    assert "https://example.com/pasif.jpg" not in page


def test_passive_announcement_not_visible_on_public_homepage(client, app):
    published = AnnouncementFactory(title="Yayındaki Duyuru", slug="yayindaki-duyuru", is_published=True)
    draft = AnnouncementFactory(title="Taslak Duyuru", slug="taslak-duyuru", is_published=False)
    db.session.add_all([published, draft])
    db.session.commit()

    response = client.get("/")
    page = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Yayındaki Duyuru" in page
    assert "Taslak Duyuru" not in page


def test_homepage_announcement_preview_payload_renders(client, app):
    announcement = AnnouncementFactory(
        title="Eğitim Daveti",
        slug="egitim-daveti",
        summary="Hafta sonu saha çalışması yapılacak.",
        cover_image="https://example.com/duyuru.jpg",
        published_at=datetime(2026, 3, 18, 14, 30),
        is_published=True,
    )
    db.session.add(announcement)
    db.session.commit()

    response = client.get("/")
    page = response.data.decode("utf-8")

    assert response.status_code == 200
    assert 'data-announcement-carousel' in page
    assert "announcementCarouselTitle" in page
    assert "announcementCarouselImage" in page
    assert "announcementCarouselData" in page
    assert "Eğitim Daveti" in page
    assert "18.03.2026" in page
    assert "Duyuru içeriğine ulaşmak için tıklayınız." in page
    assert 'id="announcementCarouselImage"' in page
    assert 'loading="eager"' in page
    assert 'fetchpriority="high"' in page
    assert 'decoding="async"' in page


def test_public_dropdown_pages_open_and_render_section_content(client, app):
    admin = KullaniciFactory(rol="sahip")
    db.session.add(admin)
    db.session.commit()

    from models import HomeSection

    db.session.add_all(
        [
            HomeSection(section_key="about", title="Biz Kimiz?", subtitle="Ekip yapısı", content="Biz kimiz içeriği", image_url="https://example.com/biz-kimiz.jpg", is_active=True),
            HomeSection(section_key="mission", title="Misyon", subtitle="Misyon başlığı", content="Misyon içeriği", is_active=True),
            HomeSection(section_key="vision", title="Vizyon", subtitle="Vizyon başlığı", content="Vizyon içeriği", is_active=True),
            HomeSection(section_key="ethics", title="Etik Değerler", subtitle="Etik başlığı", content="Etik içeriği", is_active=True),
            HomeSection(section_key="training", title="Temel Eğitim", subtitle="Eğitim başlığı", content="Eğitim içeriği", image_url="https://example.com/egitim-1.jpg", is_active=True),
            HomeSection(section_key="training", title="Saha Tekrarı", subtitle="Tekrar oturumu", content="İkinci eğitim içeriği", image_url="https://example.com/egitim-2.jpg", is_active=True),
            HomeSection(section_key="exercise", title="Kule Tatbikatı", subtitle="Tatbikat başlığı", content="Tatbikat içeriği", image_url="https://example.com/tatbikat-1.jpg", is_active=True),
            HomeSection(section_key="exercise", title="Gece Senaryosu", subtitle="Senaryo tekrarı", content="İkinci tatbikat içeriği", image_url="https://example.com/tatbikat-2.jpg", is_active=True),
        ]
    )
    db.session.commit()

    routes = [
        ("/hakkimizda/biz-kimiz", "Biz kimiz içeriği"),
        ("/hakkimizda/misyon-ve-vizyon", "Misyon içeriği"),
        ("/hakkimizda/etik-degerler", "Etik içeriği"),
        ("/faaliyetlerimiz/egitimler", "Eğitim içeriği"),
        ("/faaliyetlerimiz/tatbikatlar", "Tatbikat içeriği"),
    ]

    for path, expected in routes:
        response = client.get(path)
        page = response.data.decode("utf-8")
        assert response.status_code == 200
        assert expected in page

    about_page = client.get("/hakkimizda/biz-kimiz").data.decode("utf-8")
    assert "https://example.com/biz-kimiz.jpg" in about_page
    assert "<h2>Biz Kimiz?</h2>" not in about_page

    ethics_page = client.get("/hakkimizda/etik-degerler").data.decode("utf-8")
    assert "<h2>Etik Değerler</h2>" not in ethics_page

    mission_page = client.get("/hakkimizda/misyon-ve-vizyon").data.decode("utf-8")
    assert "<h2>Misyon</h2>" in mission_page
    assert "<h2>Vizyon</h2>" in mission_page

    training_page = client.get("/faaliyetlerimiz/egitimler").data.decode("utf-8")
    assert "Temel Eğitim" in training_page
    assert "Saha Tekrarı" in training_page
    assert "https://example.com/egitim-1.jpg" in training_page
    assert "https://example.com/egitim-2.jpg" in training_page
    assert 'data-module-system="modules"' in training_page
    assert 'data-info-back' in training_page

    drills_page = client.get("/faaliyetlerimiz/tatbikatlar").data.decode("utf-8")
    assert "Kule Tatbikatı" in drills_page
    assert "Gece Senaryosu" in drills_page
    assert "https://example.com/tatbikat-1.jpg" in drills_page
    assert "https://example.com/tatbikat-2.jpg" in drills_page
    assert 'data-module-system="modules"' in drills_page


def test_training_and_drills_pages_render_shared_empty_safe_layout(client, app):
    training_response = client.get("/faaliyetlerimiz/egitimler")
    drills_response = client.get("/faaliyetlerimiz/tatbikatlar")

    training_page = training_response.data.decode("utf-8")
    drills_page = drills_response.data.decode("utf-8")

    assert training_response.status_code == 200
    assert drills_response.status_code == 200
    assert 'data-module-system="modules"' in training_page
    assert 'data-module-system="modules"' in drills_page
    assert 'data-info-back' in training_page
    assert 'data-info-back' in drills_page
    assert "Eğitimler" in training_page
    assert "Tatbikatlar" in drills_page


def test_admin_and_editor_can_access_homepage_management(client, app):
    admin = KullaniciFactory(rol="sahip")
    editor = KullaniciFactory(rol="editor")
    db.session.add_all([admin, editor])
    db.session.commit()

    _login(client, admin)
    admin_resp = client.get("/admin/homepage")
    assert admin_resp.status_code == 200

    _login(client, editor)
    editor_resp = client.get("/admin/homepage")
    assert editor_resp.status_code == 200


def test_unauthorized_user_cannot_access_homepage_management(client, app):
    anonymous_resp = client.get("/admin/homepage")
    assert anonymous_resp.status_code == 302

    personel = KullaniciFactory(rol="personel")
    db.session.add(personel)
    db.session.commit()
    _login(client, personel)

    forbidden_resp = client.get("/admin/homepage")
    assert forbidden_resp.status_code in [302, 403]


def test_admin_can_access_all_homepage_management_pages(client, app):
    admin = KullaniciFactory(rol="sahip")
    db.session.add(admin)
    db.session.commit()
    _login(client, admin)

    endpoints = [
        "/admin/homepage",
        "/admin/homepage/sliders",
        "/admin/homepage/sections",
        "/admin/homepage/announcements",
        "/admin/homepage/documents",
        "/admin/homepage/stats",
        "/admin/homepage/quick-links",
    ]
    for path in endpoints:
        response = client.get(path)
        assert response.status_code == 200


def test_admin_homepage_dashboard_focuses_on_core_public_modules(client, app):
    admin = KullaniciFactory(rol="sahip")
    db.session.add(admin)
    db.session.commit()
    _login(client, admin)

    response = client.get("/admin/homepage")
    page = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Yeni Slider Ekle" in page
    assert "Yeni Public İçerik Modülü Ekle" in page
    assert "İstatistik Kartlarını Düzenle" in page
    assert "Yeni Doküman Ekle" not in page
    assert "Hızlı Bağlantı" not in page


def test_admin_homepage_forms_expose_new_labels(client, app):
    admin = KullaniciFactory(rol="sahip")
    db.session.add(admin)
    db.session.commit()
    _login(client, admin)

    slider_response = client.get("/admin/homepage/sliders/new")
    announcement_response = client.get("/admin/homepage/announcements/new")
    stats_response = client.get("/admin/homepage/stats")
    section_response = client.get("/admin/homepage/sections/new")

    slider_page = slider_response.data.decode("utf-8")
    announcement_page = announcement_response.data.decode("utf-8")
    stats_page = stats_response.data.decode("utf-8")
    section_page = section_response.data.decode("utf-8")

    assert slider_response.status_code == 200
    assert "Ana Başlık" in slider_page
    assert "Detay için tıklayınız" in slider_page

    assert announcement_response.status_code == 200
    assert 'name="published_at"' in announcement_page
    assert "Bağlantı Adresi (slug)" in announcement_page
    assert "Boş bırakırsanız sistem başlıktan otomatik üretir." in announcement_page
    assert "Meta Başlığı (arama motoru başlığı)" in announcement_page
    assert "Meta Açıklaması (arama motoru özeti)" in announcement_page
    assert "Yayın Durumu" in announcement_page
    assert "Anasayfada ve detay sayfasında göster" in announcement_page

    assert stats_response.status_code == 200
    assert "İstatistik Kartları" in stats_page
    assert section_response.status_code == 200
    assert "Eğitimler Sayfası Modülü" in section_page
    assert "Tatbikatlar Sayfası Modülü" in section_page


def test_active_sliders_listed_on_management_page(client, app):
    admin = KullaniciFactory(rol="sahip")
    db.session.add(admin)
    db.session.commit()
    _login(client, admin)

    active_slider = HomeSliderFactory(title="Liste Aktif Slider", is_active=True)
    passive_slider = HomeSliderFactory(title="Liste Pasif Slider", is_active=False)
    db.session.add_all([active_slider, passive_slider])
    db.session.commit()

    response = client.get("/admin/homepage/sliders")
    page = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Liste Aktif Slider" in page
    assert "Liste Pasif Slider" in page


def test_slug_collision_is_prevented_with_unique_suffix(client, app):
    editor = KullaniciFactory(rol="editor")
    db.session.add(editor)
    db.session.commit()
    _login(client, editor)

    first_response = client.post(
        "/admin/homepage/announcements/new",
        data={
            "title": "Operasyon Duyurusu",
            "slug": "operasyon-duyurusu",
            "summary": "Kısa özet",
            "content": "İlk duyuru metni",
            "is_published": "on",
        },
        follow_redirects=True,
    )
    assert first_response.status_code == 200

    second_response = client.post(
        "/admin/homepage/announcements/new",
        data={
            "title": "Operasyon Duyurusu İkinci",
            "slug": "operasyon-duyurusu",
            "summary": "Kısa özet 2",
            "content": "İkinci duyuru metni",
            "is_published": "on",
        },
        follow_redirects=True,
    )
    assert second_response.status_code == 200

    records = Announcement.query.order_by(Announcement.id.asc()).all()
    assert len(records) == 2
    assert records[0].slug == "operasyon-duyurusu"
    assert records[1].slug.startswith("operasyon-duyurusu")
    assert records[1].slug != records[0].slug
