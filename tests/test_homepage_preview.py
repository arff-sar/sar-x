from extensions import db
from tests.factories import KullaniciFactory


def _login(client, user):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


def test_editor_can_render_preview(client, app):
    editor = KullaniciFactory(rol="editor")
    db.session.add(editor)
    db.session.commit()
    _login(client, editor)

    response = client.post(
        "/admin/homepage/preview/slider",
        data={
            "title": "Önizleme Başlığı",
            "subtitle": "Önizleme Alt Metni",
            "description": "Önizleme içerik metni",
            "image_path": "https://example.com/preview.jpg",
        },
    )
    page = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "İçerik Önizleme" in page
    assert "Önizleme Başlığı" in page


def test_anonymous_cannot_access_preview_endpoint(client, app):
    response = client.post("/admin/homepage/preview/slider", data={"title": "X"})
    assert response.status_code == 302


def test_non_editor_cannot_access_preview_endpoint(client, app):
    personel = KullaniciFactory(rol="personel")
    db.session.add(personel)
    db.session.commit()
    _login(client, personel)

    response = client.post("/admin/homepage/preview/slider", data={"title": "X"})
    assert response.status_code in [302, 403]
