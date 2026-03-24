import re
import json

from extensions import db
from models import SiteAyarlari
from tests.factories import (
    HomeQuickLinkFactory,
    HomeSliderFactory,
    HomeStatCardFactory,
    InventoryAssetFactory,
    KullaniciFactory,
)


def test_active_sliders_visible_on_public_homepage(client, app):
    active_slider = HomeSliderFactory(title="Public Aktif Slider", image_url="https://example.com/active-slider.jpg", is_active=True)
    passive_slider = HomeSliderFactory(title="Public Pasif Slider", image_url="https://example.com/passive-slider.jpg", is_active=False)
    db.session.add_all([active_slider, passive_slider])
    db.session.commit()

    response = client.get("/")
    page = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "https://example.com/active-slider.jpg" in page
    assert "https://example.com/passive-slider.jpg" not in page


def test_non_primary_slider_backgrounds_are_deferred(client, app):
    first_slider = HomeSliderFactory(title="Public Slider 1", image_url="https://example.com/slider-1.jpg", is_active=True)
    second_slider = HomeSliderFactory(title="Public Slider 2", image_url="https://example.com/slider-2.jpg", is_active=True)
    db.session.add_all([first_slider, second_slider])
    db.session.commit()

    response = client.get("/")
    page = response.data.decode("utf-8")

    assert response.status_code == 200
    assert 'style="background-image:url(\'https://example.com/slider-1.jpg\')"' in page
    assert 'data-bg="https://example.com/slider-2.jpg"' in page
    assert 'style="background-image:url(\'https://example.com/slider-2.jpg\')"' not in page
    assert "function ensureSlideBackground(index)" in page


def test_homepage_renders_fallback_content_when_cms_empty(client, app):
    response = client.get("/")
    page = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "ARFF Özel Arama Kurtarma Timi" in page
    assert 'data-hero-label' in page
    assert "Duyurular" in page
    assert "Duyurular ve sahadan kısa notlar" not in page
    assert "Henüz yayınlanmış duyuru yok" in page
    assert "Timin ritmini gösteren kısa veriler" not in page
    assert 'data-announcement-carousel' not in page
    assert 'data-stats-grid' in page
    assert "ARFF SAR gönüllü tim akışı" not in page
    assert "Hazırlık, koordinasyon ve gönüllü güç aynı hatta" not in page
    assert "Sahaya yakın duran" not in page
    assert "Timimizi Tanıyın" not in page
    assert "Hazırlık sahada değil, her gün birlikte başlar" not in page
    assert "Detaylı Bilgi" not in page


def test_only_stat_cards_render_on_homepage(client, app):
    stat_assets = HomeStatCardFactory(title="Toplam Malzeme", value_text="24/7", subtitle="Canlı veri")
    stat_people = HomeStatCardFactory(title="Toplam Personel", value_text="99", subtitle="Canlı veri")
    quick = HomeQuickLinkFactory(title="Doküman Merkezi", description="Hızlı erişim", link_url="/dokumanlar")
    assets = [InventoryAssetFactory() for _ in range(3)]
    users = [KullaniciFactory() for _ in range(2)]
    db.session.add_all([stat_assets, stat_people, quick, *assets, *users])
    db.session.commit()

    response = client.get("/")
    page = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Toplam Malzeme" in page
    assert "Toplam Personel" in page
    assert "Aktif Tim" in page
    assert "Tamamlanan Eğitimler" in page
    assert "24/7" not in page
    assert re.search(r'data-homepage-stat="total_assets"[\s\S]*?<div class="stat-value" data-stat-final="3">3</div>', page)
    assert re.search(r'data-homepage-stat="total_personnel"[\s\S]*?<div class="stat-value" data-stat-final="2">2</div>', page)
    assert "/static/img/sayisal-ozet/simge_1_malzeme.png" in page
    assert "/static/img/sayisal-ozet/simge_2_personel.png" in page
    assert "/static/img/sayisal-ozet/simge_3_aktif_tim.png" in page
    assert "/static/img/sayisal-ozet/simge_4_egitim.png" in page
    assert "Doküman Merkezi" not in page


def test_header_and_footer_match_new_public_shell(client, app):
    response = client.get("/")
    page = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Anasayfa" in page
    assert "Hakkımızda" in page
    assert "Faaliyetlerimiz" in page
    assert "Giriş Yap" in page
    assert "Biz Kimiz?" in page
    assert "Misyon ve Vizyon" in page
    assert "Etik Değerler" in page
    assert "Eğitimler" in page
    assert "Tatbikatlar" in page
    assert "/hakkimizda/biz-kimiz" in page
    assert "/hakkimizda/misyon-ve-vizyon" in page
    assert "/hakkimizda/etik-degerler" in page
    assert "/faaliyetlerimiz/egitimler" in page
    assert "/faaliyetlerimiz/tatbikatlar" in page
    assert "Bağlantılar" not in page
    assert "Personel Girişi" not in page
    assert "ARFF SAR" in page
    assert "Bizimle iletişime geçin" in page
    assert 'data-public-footer' in page
    assert "SAR-X Sistem Kimliği" not in page
    assert "SAR-X ARFF" not in page


def test_header_logo_renders_when_site_logo_is_configured(client, app):
    settings = SiteAyarlari(
        baslik="ARFF SAR",
        iletisim_notu=json.dumps({"public_logo_url": "https://example.com/logo.png"}, ensure_ascii=False),
    )
    db.session.add(settings)
    db.session.commit()

    response = client.get("/")
    page = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "https://example.com/logo.png" in page
    assert 'alt="ARFF SAR logo"' in page


def test_homepage_about_cards_render_requested_order(client, app):
    response = client.get("/")
    page = response.data.decode("utf-8")

    assert response.status_code == 200
    assert page.index("Biz Kimiz") < page.index("Misyon") < page.index("Vizyon") < page.index("Etik Değerler")
    assert 'id="hakkimizda"' in page
    assert "Ekip Yapısı" not in page
    assert "Odak" not in page
    assert "Bakış" not in page
    assert "İlke" not in page


def test_homepage_handles_missing_public_tables_without_crashing(client, monkeypatch):
    import app as app_module

    original_table_exists = app_module.table_exists
    missing_tables = {
        "content_workflow",
        "home_slider",
        "slider_resim",
        "home_section",
        "announcement",
        "haber",
        "document_resource",
        "home_quick_link",
        "inventory_asset",
        "havalimani",
    }

    def patched_table_exists(table_name):
        if table_name in missing_tables:
            return False
        return original_table_exists(table_name)

    monkeypatch.setattr(app_module, "table_exists", patched_table_exists)

    response = client.get("/")
    page = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "ARFF Özel Arama Kurtarma Timi" in page
    assert "Henüz yayınlanmış duyuru yok" in page
