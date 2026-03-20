from extensions import db
from models import HomeSlider
from tests.factories import KullaniciFactory


def _login(client, user):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


def test_editor_can_create_and_edit_slider(client, app):
    editor = KullaniciFactory(rol="editor")
    db.session.add(editor)
    db.session.commit()
    _login(client, editor)

    create_resp = client.post(
        "/admin/homepage/sliders/new",
        data={
            "title": "Yeni Hero Mesajı",
            "subtitle": "Kurumsal Operasyon",
            "description": "Editor tarafından eklendi",
            "image_url": "https://example.com/hero.jpg",
            "button_text": "Detaylı Bilgi",
            "button_link": "#hakkimizda",
            "order_index": 1,
            "is_active": "on",
        },
        follow_redirects=True,
    )
    assert create_resp.status_code == 200

    slider = HomeSlider.query.filter_by(title="Yeni Hero Mesajı").first()
    assert slider is not None

    edit_resp = client.post(
        f"/admin/homepage/sliders/{slider.id}/edit",
        data={
            "title": "Güncel Hero Mesajı",
            "subtitle": "Kurumsal Operasyon",
            "description": "Editor tarafından güncellendi",
            "image_url": "https://example.com/hero2.jpg",
            "button_text": "İncele",
            "button_link": "#duyurular",
            "order_index": 2,
            "is_active": "on",
        },
        follow_redirects=True,
    )
    assert edit_resp.status_code == 200

    db.session.refresh(slider)
    assert slider.title == "Güncel Hero Mesajı"
    assert slider.order_index == 2


def test_editor_cannot_access_user_management(client, app):
    editor = KullaniciFactory(rol="editor")
    db.session.add(editor)
    db.session.commit()
    _login(client, editor)

    response = client.get("/kullanicilar")
    assert response.status_code in [302, 403]


def test_editor_cannot_access_site_settings(client, app):
    editor = KullaniciFactory(rol="editor")
    db.session.add(editor)
    db.session.commit()
    _login(client, editor)

    response = client.get("/site-yonetimi")
    assert response.status_code in [302, 403]
