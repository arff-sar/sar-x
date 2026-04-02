import pytest

from homepage_demo import (
    HOMEPAGE_DEMO_SEED_TAG,
    clear_homepage_demo_data,
    get_homepage_demo_status,
    seed_homepage_demo_data,
)
from extensions import db
from models import Announcement, DemoSeedRecord, DocumentResource, HomeQuickLink, HomeSection, HomeSlider, HomeStatCard
from tests.factories import (
    AnnouncementFactory,
    DocumentResourceFactory,
    HomeQuickLinkFactory,
    HomeSectionFactory,
    HomeSliderFactory,
    HomeStatCardFactory,
    KullaniciFactory,
)


def _login(client, user):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


def test_homepage_demo_seed_is_idempotent(app):
    app.config["DEMO_TOOLS_ENABLED"] = True

    with app.app_context():
        result = seed_homepage_demo_data()
        summary = result["summary"]

        assert result["created"] is True
        assert summary["sliders"] == 3
        assert summary["announcements"] == 5
        assert summary["documents"] == 2
        assert summary["quick_links"] == 2
        assert summary["stats"] == 4
        assert summary["sections"] == 12
        assert summary["training_modules"] == 4
        assert summary["exercise_modules"] == 4
        assert "Biz Kimiz" in summary["pages"]
        assert "Eğitimler" in summary["pages"]
        assert "Tatbikatlar" in summary["pages"]

        first_counts = (
            HomeSlider.query.count(),
            Announcement.query.count(),
            DocumentResource.query.count(),
            HomeQuickLink.query.count(),
            HomeStatCard.query.count(),
            HomeSection.query.count(),
            DemoSeedRecord.query.filter_by(seed_tag=HOMEPAGE_DEMO_SEED_TAG).count(),
        )

        second = seed_homepage_demo_data()
        second_counts = (
            HomeSlider.query.count(),
            Announcement.query.count(),
            DocumentResource.query.count(),
            HomeQuickLink.query.count(),
            HomeStatCard.query.count(),
            HomeSection.query.count(),
            DemoSeedRecord.query.filter_by(seed_tag=HOMEPAGE_DEMO_SEED_TAG).count(),
        )

        assert second["created"] is False
        assert first_counts == second_counts
        assert get_homepage_demo_status()["active"] is True


def test_homepage_demo_clear_only_removes_demo_records(app):
    app.config["DEMO_TOOLS_ENABLED"] = True

    with app.app_context():
        real_slider = HomeSliderFactory(title="Gerçek Slider Başlığı")
        real_announcement = AnnouncementFactory(
            title="Gerçek Duyuru Başlığı",
            slug="gercek-duyuru-basligi",
            is_published=True,
        )
        real_document = DocumentResourceFactory(title="Gerçek Doküman Başlığı", file_path="/docs/gercek.pdf")
        real_quicklink = HomeQuickLinkFactory(title="Gerçek Hızlı Link Başlığı", link_url="/gercek-link")
        real_stat = HomeStatCardFactory(title="Gerçek İstatistik", value_text="9")
        real_section = HomeSectionFactory(section_key="training", title="Gerçek Eğitim Modülü")
        db.session.add_all([real_slider, real_announcement, real_document, real_quicklink, real_stat, real_section])
        db.session.commit()

        seed_homepage_demo_data()
        result = clear_homepage_demo_data()

        assert result["deleted"] > 0
        assert DemoSeedRecord.query.filter_by(seed_tag=HOMEPAGE_DEMO_SEED_TAG).count() == 0
        assert HomeSlider.query.filter_by(title="Gerçek Slider Başlığı").first() is not None
        assert Announcement.query.filter_by(slug="gercek-duyuru-basligi").first() is not None
        assert DocumentResource.query.filter_by(title="Gerçek Doküman Başlığı").first() is not None
        assert HomeQuickLink.query.filter_by(title="Gerçek Hızlı Link Başlığı").first() is not None
        assert HomeStatCard.query.filter_by(title="Gerçek İstatistik").first() is not None
        assert HomeSection.query.filter_by(title="Gerçek Eğitim Modülü").first() is not None
        assert get_homepage_demo_status()["active"] is False


def test_site_settings_shows_homepage_demo_panel(client, app):
    app.config["DEMO_TOOLS_ENABLED"] = True
    owner = KullaniciFactory(rol="sahip")
    db.session.add(owner)
    db.session.commit()
    _login(client, owner)

    response = client.get("/site-yonetimi")
    page = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Anasayfa Demo Araçları" in page
    assert "Anasayfa Demosunu Kur" in page
    assert "Anasayfa Demosunu Temizle" in page
    assert "Oluşan içerik sayfaları" in page


def test_homepage_demo_routes_render_demo_content_without_mixing_real_content(client, app):
    app.config["DEMO_TOOLS_ENABLED"] = True

    owner = KullaniciFactory(rol="sahip")
    real_slider = HomeSliderFactory(title="Gerçek Slider Başlığı", image_url="https://example.com/gercek-slider.jpg")
    real_announcement = AnnouncementFactory(
        title="Gerçek Duyuru Başlığı",
        slug="gercek-duyuru-basligi",
        is_published=True,
    )
    real_stat = HomeStatCardFactory(title="Gerçek İstatistik", value_text="9")
    real_document = DocumentResourceFactory(title="Gerçek Form Başlığı", file_path="/docs/gercek-form.pdf")
    real_training = HomeSectionFactory(section_key="training", title="Gerçek Eğitim Modülü")
    real_exercise = HomeSectionFactory(section_key="exercise", title="Gerçek Tatbikat Modülü")
    db.session.add_all([owner, real_slider, real_announcement, real_stat, real_document, real_training, real_exercise])
    db.session.commit()
    _login(client, owner)

    seed_response = client.post("/demo-veri/anasayfa/olustur", follow_redirects=True)
    seed_page = seed_response.data.decode("utf-8")

    assert seed_response.status_code == 200
    assert "Anasayfa demo içeriği kuruldu." in seed_page

    home_page = client.get("/").data.decode("utf-8")
    assert "ARFF Özel Arama Kurtarma Timi" in home_page
    assert "Hazırlık sahada değil, her gün birlikte başlar" not in home_page
    assert "Hafta sonu ortak eğitim buluşması" in home_page
    assert "Toplam Malzeme" in home_page
    assert "Gerçek Slider Başlığı" not in home_page
    assert "Gerçek Duyuru Başlığı" not in home_page
    assert "Gerçek İstatistik" not in home_page

    announcements_page = client.get("/duyurular").data.decode("utf-8")
    assert "Gönüllü koordinasyon toplantısı" in announcements_page
    assert "Gerçek Duyuru Başlığı" not in announcements_page

    training_page = client.get("/faaliyetlerimiz/egitimler").data.decode("utf-8")
    assert "Temel enkaz arama eğitimi" in training_page
    assert "Gerçek Eğitim Modülü" not in training_page

    drills_page = client.get("/faaliyetlerimiz/tatbikatlar").data.decode("utf-8")
    assert "Gece operasyon hazırlık tatbikatı" in drills_page
    assert "Gerçek Tatbikat Modülü" not in drills_page

    documents_page = client.get("/formlar").data.decode("utf-8")
    assert "Gerçek Form Başlığı" not in documents_page
    assert "ARFF-SAR Operasyon Hazırlık Kontrol Formu" in documents_page

    clear_response = client.post("/demo-veri/anasayfa/temizle", follow_redirects=True)
    clear_page = clear_response.data.decode("utf-8")

    assert clear_response.status_code == 200
    assert "Anasayfa demo içeriği temizlendi." in clear_page

    restored_home = client.get("/").data.decode("utf-8")
    assert "https://example.com/gercek-slider.jpg" in restored_home
    assert "Gerçek Duyuru Başlığı" in client.get("/duyurular").data.decode("utf-8")
    assert "Gerçek Form Başlığı" in client.get("/formlar").data.decode("utf-8")
    assert HomeSlider.query.filter_by(title="Gerçek Slider Başlığı").first() is not None
    assert Announcement.query.filter_by(slug="gercek-duyuru-basligi").first() is not None


def test_homepage_demo_seed_is_blocked_in_production_env(app):
    app.config["DEMO_TOOLS_ENABLED"] = True
    app.config["ENV"] = "production"

    with app.app_context():
        with pytest.raises(RuntimeError, match="kapalı"):
            seed_homepage_demo_data()


def test_homepage_demo_routes_are_blocked_in_production_even_if_flag_enabled(client, app):
    app.config["DEMO_TOOLS_ENABLED"] = True
    app.config["ENV"] = "production"

    owner = KullaniciFactory(rol="sahip")
    db.session.add(owner)
    db.session.commit()
    _login(client, owner)

    seed_response = client.post("/demo-veri/anasayfa/olustur", follow_redirects=False)
    clear_response = client.post("/demo-veri/anasayfa/temizle", follow_redirects=False)

    assert seed_response.status_code == 404
    assert clear_response.status_code == 404
