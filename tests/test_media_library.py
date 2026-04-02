import io

from extensions import db
from models import MediaAsset
from tests.factories import KullaniciFactory


def _login(client, user):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


def test_media_upload_rejects_invalid_extension(client, app):
    editor = KullaniciFactory(rol="editor")
    db.session.add(editor)
    db.session.commit()
    _login(client, editor)

    response = client.post(
        "/admin/homepage/media/upload",
        data={
            "title": "Zararlı Dosya",
            "alt_text": "Test",
            "media_file": (io.BytesIO(b"dummy"), "payload.exe"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert MediaAsset.query.count() == 0


def test_media_upload_rejects_invalid_mimetype(client, app):
    editor = KullaniciFactory(rol="editor")
    db.session.add(editor)
    db.session.commit()
    _login(client, editor)

    response = client.post(
        "/admin/homepage/media/upload",
        data={
            "title": "Yanlış MIME",
            "media_file": (io.BytesIO(b"dummy"), "fake.png", "text/plain"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert MediaAsset.query.count() == 0


def test_media_upload_success_and_toggle(client, app):
    editor = KullaniciFactory(rol="editor")
    db.session.add(editor)
    db.session.commit()
    _login(client, editor)

    upload_resp = client.post(
        "/admin/homepage/media/upload",
        data={
            "title": "Hero Görseli",
            "alt_text": "Operasyon sahası",
            "media_file": (io.BytesIO(b"\x89PNG\r\n\x1a\n"), "hero.png", "image/png"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert upload_resp.status_code == 200

    asset = MediaAsset.query.first()
    assert asset is not None
    assert asset.file_type == "image"
    assert asset.is_active is True
    assert asset.file_path.startswith("/static/uploads/cms/")

    toggle_resp = client.post(
        f"/admin/homepage/media/{asset.id}/toggle",
        follow_redirects=True,
    )
    assert toggle_resp.status_code == 200

    db.session.refresh(asset)
    assert asset.is_active is False


def test_media_upload_rejects_invalid_file_signature(client, app):
    editor = KullaniciFactory(rol="editor")
    db.session.add(editor)
    db.session.commit()
    _login(client, editor)

    response = client.post(
        "/admin/homepage/media/upload",
        data={
            "title": "Sahte PDF",
            "alt_text": "Test",
            "media_file": (io.BytesIO(b"not-a-real-pdf"), "fake.pdf", "application/pdf"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert MediaAsset.query.count() == 0


def test_media_library_ignores_legacy_picker_query_and_keeps_normal_layout(client, app):
    editor = KullaniciFactory(rol="editor")
    db.session.add(editor)
    db.session.flush()
    db.session.add_all(
        [
            MediaAsset(
                title="Slider Görseli",
                file_path="/static/uploads/cms/slider.png",
                file_type="image",
                alt_text="Slider",
                uploaded_by_id=editor.id,
                is_active=True,
            ),
            MediaAsset(
                title="PDF Doküman",
                file_path="/static/uploads/cms/form.pdf",
                file_type="document",
                alt_text="",
                uploaded_by_id=editor.id,
                is_active=True,
            ),
        ]
    )
    db.session.commit()
    _login(client, editor)

    response = client.get("/admin/homepage/media?picker=1&target_field=image_path")
    page = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Medya Kütüphanesi" in page
    assert "selectMediaAsset" not in page
    assert "window.opener" not in page
    assert "postMessage" not in page
    assert "Slider Görseli" in page
