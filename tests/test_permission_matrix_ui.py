import io
import re

from pypdf import PdfReader

from decorators import DEFAULT_ROLE_PERMISSIONS
from extensions import db
from tests.factories import KullaniciFactory


def _login(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def _module_block(html, module_key):
    marker = f'data-module-card="{module_key}"'
    start = html.find(marker)
    assert start != -1, f"{module_key} bloğu bulunamadı"
    next_start = html.find('data-module-card="', start + len(marker))
    if next_start == -1:
        next_start = len(html)
    return html[start:next_start]


def test_selected_role_permissions_render_in_matching_accordion_block(client, app):
    owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-matrix@sarx.com")
    db.session.add(owner)
    db.session.commit()

    _login(client, owner.id)
    response = client.get("/admin/permissions?role_key=editor")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    homepage_block = _module_block(html, "homepage")
    inventory_block = _module_block(html, "inventory")

    assert re.search(r'value="homepage\.view"[^>]*checked', homepage_block)
    assert re.search(r'value="homepage\.edit"[^>]*checked', homepage_block)
    assert 'data-active-chip="homepage.view"' in homepage_block
    assert 'data-selected-chip-group="homepage"' in homepage_block
    assert 'data-empty-chip-state' in inventory_block
    assert not re.search(r'value="inventory\.view"[^>]*checked', inventory_block)


def test_new_permission_stays_visible_inside_its_category_block_after_save(client, app):
    owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-matrix-save@sarx.com")
    db.session.add(owner)
    db.session.commit()

    selected_permissions = sorted(set(DEFAULT_ROLE_PERMISSIONS["personel"]) | {"reports.view"})

    _login(client, owner.id)
    response = client.post(
        "/admin/permissions",
        data={
            "role_key": "personel",
            "selected_permissions": selected_permissions,
        },
        follow_redirects=True,
    )
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    reports_block = _module_block(html, "reports")
    assert re.search(r'value="reports\.view"[^>]*checked', reports_block)
    assert 'data-active-chip="reports.view"' in reports_block
    assert "Permission matrix guncellendi." in html


def test_permission_matrix_page_contains_live_summary_and_tooltip_data(client, app):
    owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-matrix-live@sarx.com")
    db.session.add(owner)
    db.session.commit()

    _login(client, owner.id)
    response = client.get("/admin/permissions?role_key=admin")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert 'data-matrix-summary' in html
    assert 'id="matrixSummaryBody"' in html
    assert 'id="rolePermissionMapData"' in html
    assert 'data-tooltip-trigger' in html
    assert 'role="tooltip"' in html
    assert 'data-selected-chip-group="inventory"' in html
    assert 'data-module-count="inventory"' in html


def test_permission_matrix_pdf_export_returns_role_summary(client, app):
    owner = KullaniciFactory(rol="sahip", is_deleted=False, kullanici_adi="owner-matrix-pdf@sarx.com")
    db.session.add(owner)
    db.session.commit()

    _login(client, owner.id)
    response = client.post(
        "/admin/permissions/export/pdf",
        data={
            "role_key": "personel",
            "selected_permissions": sorted(DEFAULT_ROLE_PERMISSIONS["personel"]),
        },
    )

    assert response.status_code == 200
    assert response.mimetype == "application/pdf"

    reader = PdfReader(io.BytesIO(response.data))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)

    assert "Ekip Üyesi" in text
    assert "dashboard.view" in text
    assert "Aktif Matrix Özeti" in text
