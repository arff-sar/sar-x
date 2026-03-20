from extensions import db
from models import ContentWorkflow, HomeSlider
from tests.factories import HomeQuickLinkFactory, HomeSliderFactory, KullaniciFactory


def _login(client, user):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


def test_draft_slider_not_visible_until_published(client, app):
    editor = KullaniciFactory(rol="editor")
    db.session.add(editor)
    db.session.commit()
    _login(client, editor)

    create_resp = client.post(
        "/admin/homepage/sliders/new",
        data={
            "title": "Taslak Hero İçeriği",
            "subtitle": "Test",
            "description": "Taslak açıklaması",
            "image_url": "https://example.com/hero.jpg",
            "button_text": "İncele",
            "button_link": "#hakkimizda",
            "order_index": 0,
            "workflow_status": "draft",
            "is_active": "on",
        },
        follow_redirects=True,
    )
    assert create_resp.status_code == 200

    slider = HomeSlider.query.filter_by(title="Taslak Hero İçeriği").first()
    assert slider is not None
    wf = ContentWorkflow.query.filter_by(entity_type="slider", entity_id=slider.id).first()
    assert wf is not None
    assert wf.status == "draft"
    assert slider.is_active is False

    public_before = client.get("/")
    assert public_before.status_code == 200
    assert "Taslak Hero İçeriği" not in public_before.data.decode("utf-8")

    publish_resp = client.post(
        "/admin/homepage/slider/bulk",
        data={"bulk_action": "publish", "selected_ids": [str(slider.id)]},
        follow_redirects=True,
    )
    assert publish_resp.status_code == 200

    db.session.refresh(slider)
    db.session.refresh(wf)
    assert wf.status == "published"
    assert slider.is_active is True

    public_after = client.get("/")
    assert public_after.status_code == 200
    assert "Taslak Hero İçeriği" in public_after.data.decode("utf-8")


def test_reorder_updates_slider_order_indices(client, app):
    editor = KullaniciFactory(rol="editor")
    db.session.add(editor)
    db.session.commit()
    _login(client, editor)

    first = HomeSliderFactory(title="İlk Slider", order_index=0, is_active=True)
    second = HomeSliderFactory(title="İkinci Slider", order_index=1, is_active=True)
    db.session.add_all([first, second])
    db.session.flush()

    db.session.add_all(
        [
            ContentWorkflow(entity_type="slider", entity_id=first.id, status="published", last_edited_by_id=editor.id),
            ContentWorkflow(entity_type="slider", entity_id=second.id, status="published", last_edited_by_id=editor.id),
        ]
    )
    db.session.commit()

    move_resp = client.post(
        f"/admin/homepage/slider/{first.id}/move/down",
        follow_redirects=True,
    )
    assert move_resp.status_code == 200

    db.session.refresh(first)
    db.session.refresh(second)
    assert first.order_index == 1
    assert second.order_index == 0


def test_bulk_archive_sets_quick_links_passive(client, app):
    editor = KullaniciFactory(rol="editor")
    db.session.add(editor)
    db.session.commit()
    _login(client, editor)

    q1 = HomeQuickLinkFactory(title="Kart 1", order_index=0, is_active=True)
    q2 = HomeQuickLinkFactory(title="Kart 2", order_index=1, is_active=True)
    db.session.add_all([q1, q2])
    db.session.flush()

    wf1 = ContentWorkflow(entity_type="quicklink", entity_id=q1.id, status="published", last_edited_by_id=editor.id)
    wf2 = ContentWorkflow(entity_type="quicklink", entity_id=q2.id, status="published", last_edited_by_id=editor.id)
    db.session.add_all([wf1, wf2])
    db.session.commit()

    archive_resp = client.post(
        "/admin/homepage/quicklink/bulk",
        data={"bulk_action": "archive", "selected_ids": [str(q1.id), str(q2.id)]},
        follow_redirects=True,
    )
    assert archive_resp.status_code == 200

    db.session.refresh(q1)
    db.session.refresh(q2)
    db.session.refresh(wf1)
    db.session.refresh(wf2)
    assert wf1.status == "archived"
    assert wf2.status == "archived"
    assert q1.is_active is False
    assert q2.is_active is False


def test_editor_publish_falls_back_to_draft_when_disabled(client, app):
    app.config["HOMEPAGE_EDITOR_CAN_PUBLISH"] = False
    editor = KullaniciFactory(rol="editor")
    db.session.add(editor)
    db.session.commit()
    _login(client, editor)

    slider = HomeSliderFactory(title="Yayın Yetkisi Testi", order_index=0, is_active=False)
    db.session.add(slider)
    db.session.flush()
    wf = ContentWorkflow(entity_type="slider", entity_id=slider.id, status="draft", last_edited_by_id=editor.id)
    db.session.add(wf)
    db.session.commit()

    publish_resp = client.post(
        "/admin/homepage/slider/bulk",
        data={"bulk_action": "publish", "selected_ids": [str(slider.id)]},
        follow_redirects=True,
    )
    assert publish_resp.status_code == 200

    db.session.refresh(slider)
    db.session.refresh(wf)
    assert wf.status == "draft"
    assert slider.is_active is False
