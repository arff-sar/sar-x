from datetime import datetime

from extensions import db
from tests.factories import AnnouncementFactory, DocumentResourceFactory


def test_unpublished_announcements_hidden_from_public_list(client, app):
    published = AnnouncementFactory(
        title="Yayınlanan Duyuru",
        slug="yayinlanan-duyuru",
        published_at=datetime(2026, 3, 17, 9, 45),
        is_published=True,
    )
    hidden = AnnouncementFactory(title="Gizli Duyuru", slug="gizli-duyuru", is_published=False)
    db.session.add_all([published, hidden])
    db.session.commit()

    response = client.get("/duyurular")
    page = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Yayınlanan Duyuru" in page
    assert "Gizli Duyuru" not in page
    assert "17.03.2026 09:45" in page


def test_published_announcement_detail_page_opens(client, app):
    published = AnnouncementFactory(title="Detay Duyurusu", slug="detay-duyurusu", is_published=True)
    hidden = AnnouncementFactory(title="Yasak Duyuru", slug="yasak-duyuru", is_published=False)
    db.session.add_all([published, hidden])
    db.session.commit()

    ok_response = client.get("/duyurular/detay-duyurusu")
    hidden_response = client.get("/duyurular/yasak-duyuru")

    assert ok_response.status_code == 200
    assert "Detay Duyurusu" in ok_response.data.decode("utf-8")
    assert "Güncel Paylaşım" in ok_response.data.decode("utf-8")
    assert hidden_response.status_code == 404


def test_public_documents_list_shows_only_active_records(client, app):
    active_doc = DocumentResourceFactory(title="Aktif Form", is_active=True)
    passive_doc = DocumentResourceFactory(title="Pasif Form", is_active=False)
    db.session.add_all([active_doc, passive_doc])
    db.session.commit()

    response = client.get("/dokumanlar")
    page = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Aktif Form" in page
    assert "Pasif Form" not in page


def test_public_announcements_empty_state_renders_with_refined_copy(client, app):
    response = client.get("/duyurular")
    page = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Henüz yayınlanmış duyuru yok" in page
    assert "Duyuru Akışı" in page
    assert "Tim içi duyurular" in page


def test_public_announcement_routes_degrade_safely_when_tables_missing(client, monkeypatch):
    import routes.content as content_module

    original_table_exists = content_module.table_exists

    def patched_table_exists(table_name):
        if table_name in {"announcement", "content_seo", "content_workflow", "document_resource", "home_section"}:
            return False
        return original_table_exists(table_name)

    monkeypatch.setattr(content_module, "table_exists", patched_table_exists)

    list_response = client.get("/duyurular")
    detail_response = client.get("/duyurular/olmayan-duyuru")
    documents_response = client.get("/dokumanlar")
    training_response = client.get("/faaliyetlerimiz/egitimler")

    assert list_response.status_code == 200
    assert "Henüz yayınlanmış duyuru yok" in list_response.data.decode("utf-8")
    assert detail_response.status_code == 404
    assert documents_response.status_code == 200
    assert training_response.status_code == 200
