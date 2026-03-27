import re
import unicodedata
from datetime import datetime
from types import SimpleNamespace

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError

from decorators import has_permission, homepage_editor_required
from extensions import (
    audit_log,
    db,
    guvenli_metin,
    is_allowed_file,
    is_allowed_mime,
    limiter,
    log_kaydet,
    secure_upload_filename,
    table_exists,
)
from homepage_demo import filter_homepage_demo_items, homepage_demo_is_active, is_homepage_demo_item
from storage import get_storage_adapter
from models import (
    Announcement,
    ContentSEO,
    ContentWorkflow,
    DocumentResource,
    HomeQuickLink,
    HomeSection,
    HomeSlider,
    HomeStatCard,
    MediaAsset,
    get_tr_now,
)


content_bp = Blueprint("content", __name__)

WORKFLOW_DRAFT = "draft"
WORKFLOW_PUBLISHED = "published"
WORKFLOW_PASSIVE = "passive"
WORKFLOW_ARCHIVED = "archived"
ALLOWED_WORKFLOW_STATUSES = {
    WORKFLOW_DRAFT,
    WORKFLOW_PUBLISHED,
    WORKFLOW_PASSIVE,
    WORKFLOW_ARCHIVED,
}

CONTENT_TYPE_MAP = {
    "slider": HomeSlider,
    "section": HomeSection,
    "announcement": Announcement,
    "document": DocumentResource,
    "stat": HomeStatCard,
    "quicklink": HomeQuickLink,
}


def _can_publish():
    return has_permission("homepage.publish")


def _resolve_status_from_form(default):
    status = (request.form.get("workflow_status") or "").strip().lower()
    if status not in ALLOWED_WORKFLOW_STATUSES:
        return default
    if status == WORKFLOW_PUBLISHED and not _can_publish():
        return WORKFLOW_DRAFT
    return status


def _to_bool(value):
    return str(value).lower() in {"1", "true", "on", "yes"}


def _to_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_order_index(value, default=0):
    return max(_to_int(value, default), 0)


def _slugify(value):
    text = str(value or "").strip().lower()
    tr_map = str.maketrans("çğıöşü", "cgiosu")
    text = text.translate(tr_map)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "duyuru"


def _parse_datetime_input(value):
    cleaned = guvenli_metin(value or "").strip()
    if not cleaned:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


def _unique_slug(base_slug, announcement_id=None):
    candidate = base_slug
    index = 2
    while True:
        query = Announcement.query.filter_by(slug=candidate)
        if announcement_id:
            query = query.filter(Announcement.id != announcement_id)
        if query.first() is None:
            return candidate
        candidate = f"{base_slug}-{index}"
        index += 1


def _validate_document_path(value):
    cleaned = guvenli_metin(value or "").strip()
    if not cleaned:
        return True

    lowered = cleaned.lower()
    if lowered.startswith(("javascript:", "data:", "vbscript:")):
        return False

    if lowered.startswith(("http://", "https://")):
        return True

    allowed_ext = current_app.config.get("ALLOWED_UPLOAD_EXTENSIONS", set())
    return is_allowed_file(cleaned, allowed_ext)


def _validate_media_path(value):
    cleaned = guvenli_metin(value or "").strip()
    if not cleaned:
        return True

    lowered = cleaned.lower()
    if lowered.startswith(("javascript:", "data:", "vbscript:")):
        return False

    if lowered.startswith(("http://", "https://")):
        return True

    allowed_ext = current_app.config.get("ALLOWED_UPLOAD_EXTENSIONS", set())
    return is_allowed_file(cleaned, allowed_ext)


def _validate_link_url(value):
    cleaned = guvenli_metin(value or "").strip()
    if not cleaned:
        return True
    lowered = cleaned.lower()
    if lowered.startswith(("javascript:", "data:", "vbscript:")):
        return False
    if cleaned.startswith("/"):
        return True
    if lowered.startswith(("http://", "https://", "mailto:", "tel:", "#")):
        return True
    return False


def _public_layout_context():
    loader = current_app.extensions.get("public_site_snapshot_loader")
    if callable(loader):
        try:
            snapshot = loader()
        except Exception:
            snapshot = {}
        return {
            "ayarlar": snapshot.get("ayarlar"),
            "menuler": [],
        }
    return {"ayarlar": None, "menuler": []}


def _safe_public_result(factory, required_tables, fallback):
    if any(not table_exists(table_name) for table_name in required_tables):
        return fallback
    try:
        return factory()
    except SQLAlchemyError:
        db.session.rollback()
        return fallback


def _published_sections_for_keys(*keys):
    requested_keys = [key for key in keys if key]
    if not requested_keys:
        return []
    rows = _safe_public_result(
        lambda: HomeSection.query.filter(
            HomeSection.section_key.in_(requested_keys),
            HomeSection.is_active.is_(True),
        ).order_by(HomeSection.order_index.asc(), HomeSection.id.asc()).all(),
        ("home_section",),
        [],
    )
    rows = [item for item in rows if _current_workflow_status("section", item) == WORKFLOW_PUBLISHED]
    rows = filter_homepage_demo_items(rows)
    order_map = {key: idx for idx, key in enumerate(requested_keys)}
    return sorted(rows, key=lambda item: (order_map.get(item.section_key, 999), item.order_index or 0, item.id))


def _section_entry(section, fallback):
    return SimpleNamespace(
        title=(section.title if section and section.title else fallback.get("title")),
        subtitle=(section.subtitle if section and section.subtitle else fallback.get("subtitle", "")),
        content=(section.content if section and section.content else fallback.get("content", "")),
        image_url=(section.image_path if section and getattr(section, "image_path", None) else fallback.get("image_url", "")),
        section_key=(section.section_key if section else fallback.get("section_key", "")),
    )


def _legacy_visibility_status(content_type, item):
    if content_type == "announcement":
        return WORKFLOW_PUBLISHED if item.is_published else WORKFLOW_DRAFT
    return WORKFLOW_PUBLISHED if item.is_active else WORKFLOW_PASSIVE


def _get_workflow(content_type, entity_id):
    if not table_exists("content_workflow"):
        return None
    try:
        return ContentWorkflow.query.filter_by(entity_type=content_type, entity_id=entity_id).first()
    except SQLAlchemyError:
        db.session.rollback()
        return None


def _ensure_workflow(content_type, item, default_status=None):
    workflow = _get_workflow(content_type, item.id)
    if workflow:
        return workflow

    initial_status = default_status or _legacy_visibility_status(content_type, item)
    workflow = ContentWorkflow(
        entity_type=content_type,
        entity_id=item.id,
        status=initial_status,
        published_at=get_tr_now() if initial_status == WORKFLOW_PUBLISHED else None,
        published_by_id=current_user.id if initial_status == WORKFLOW_PUBLISHED else None,
        last_edited_by_id=current_user.id if current_user.is_authenticated else None,
        last_action="bootstrap",
    )
    db.session.add(workflow)
    return workflow


def _apply_visibility_from_status(content_type, item, status):
    if content_type == "announcement":
        item.is_published = status == WORKFLOW_PUBLISHED
        if item.is_published and not item.published_at:
            item.published_at = get_tr_now()
        if status != WORKFLOW_PUBLISHED:
            item.published_at = None
        return

    if hasattr(item, "is_active"):
        item.is_active = status == WORKFLOW_PUBLISHED


def _set_workflow_status(content_type, item, status, action):
    status = status if status in ALLOWED_WORKFLOW_STATUSES else WORKFLOW_DRAFT
    if status == WORKFLOW_PUBLISHED and not _can_publish():
        status = WORKFLOW_DRAFT

    workflow = _ensure_workflow(content_type, item, default_status=status)
    workflow.status = status
    workflow.last_action = action
    workflow.last_edited_by_id = current_user.id
    if status == WORKFLOW_PUBLISHED:
        workflow.published_at = get_tr_now()
        workflow.published_by_id = current_user.id

    _apply_visibility_from_status(content_type, item, status)
    return workflow


def _current_workflow_status(content_type, item):
    workflow = _get_workflow(content_type, item.id)
    if workflow:
        return workflow.status
    return _legacy_visibility_status(content_type, item)


def _workflow_map(content_type, entities):
    entity_ids = [entity.id for entity in entities]
    if not entity_ids:
        return {}
    if not table_exists("content_workflow"):
        return {
            entity.id: SimpleNamespace(
                entity_type=content_type,
                entity_id=entity.id,
                status=_legacy_visibility_status(content_type, entity),
                published_at=getattr(entity, "published_at", None),
                published_by_id=None,
                last_edited_by_id=None,
                last_action="virtual_fallback",
            )
            for entity in entities
        }

    try:
        rows = ContentWorkflow.query.filter(
            ContentWorkflow.entity_type == content_type,
            ContentWorkflow.entity_id.in_(entity_ids),
        ).all()
    except SQLAlchemyError:
        db.session.rollback()
        rows = []
    mapped = {row.entity_id: row for row in rows}
    for entity in entities:
        if entity.id not in mapped:
            mapped[entity.id] = SimpleNamespace(
                entity_type=content_type,
                entity_id=entity.id,
                status=_legacy_visibility_status(content_type, entity),
                published_at=getattr(entity, "published_at", None),
                published_by_id=None,
                last_edited_by_id=None,
                last_action="virtual_fallback",
            )
    return mapped


def _seo_for_announcement(announcement_id):
    if not table_exists("content_seo"):
        return None
    try:
        return ContentSEO.query.filter_by(entity_type="announcement", entity_id=announcement_id).first()
    except SQLAlchemyError:
        db.session.rollback()
        return None


def _ensure_announcement_seo(announcement_id):
    seo = _seo_for_announcement(announcement_id)
    if seo:
        return seo
    seo = ContentSEO(entity_type="announcement", entity_id=announcement_id)
    db.session.add(seo)
    return seo


def _seo_map_for_announcements(announcements):
    ids = [item.id for item in announcements]
    if not ids:
        return {}
    if not table_exists("content_seo"):
        return {}
    try:
        rows = ContentSEO.query.filter(
            ContentSEO.entity_type == "announcement",
            ContentSEO.entity_id.in_(ids),
        ).all()
    except SQLAlchemyError:
        db.session.rollback()
        return {}
    return {row.entity_id: row for row in rows}


def _apply_common_filters(query, model, content_type):
    search = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "").strip().lower()

    if search:
        if content_type == "announcement":
            query = query.filter(
                or_(
                    model.title.ilike(f"%{search}%"),
                    model.slug.ilike(f"%{search}%"),
                    model.summary.ilike(f"%{search}%"),
                )
            )
        elif hasattr(model, "description"):
            query = query.filter(
                or_(
                    model.title.ilike(f"%{search}%"),
                    model.description.ilike(f"%{search}%"),
                )
            )
        else:
            query = query.filter(model.title.ilike(f"%{search}%"))

    records = query.all()
    if status in ALLOWED_WORKFLOW_STATUSES:
        records = [item for item in records if _current_workflow_status(content_type, item) == status]
    return records, search, status


def _swap_order_with_neighbor(content_type, item, direction):
    model = CONTENT_TYPE_MAP[content_type]
    base_query = model.query
    current_order = item.order_index or 0
    if direction == "up":
        neighbor = base_query.filter(model.order_index < current_order).order_by(model.order_index.desc(), model.id.desc()).first()
    else:
        neighbor = base_query.filter(model.order_index > current_order).order_by(model.order_index.asc(), model.id.asc()).first()

    if not neighbor:
        return False

    neighbor_order = neighbor.order_index or 0
    item.order_index = neighbor_order
    neighbor.order_index = current_order
    return True


def _normalize_order(content_type):
    model = CONTENT_TYPE_MAP[content_type]
    rows = model.query.order_by(model.order_index.asc(), model.id.asc()).all()
    for idx, row in enumerate(rows):
        row.order_index = idx
    db.session.commit()
    audit_log("homepage.order.normalize", outcome="success", content_type=content_type, count=len(rows))
    log_kaydet("Anasayfa İçerik", f"Sıralama normalize edildi: {content_type}")


def _is_allowed_upload_mimetype(upload):
    mime = (getattr(upload, "mimetype", "") or "").lower()
    # Bazı istemciler güvenilir MIME göndermez; dosya adı doğrulamasıyla birlikte esnek davran.
    if not mime or mime == "application/octet-stream":
        return True
    return mime.startswith("image/") or mime == "application/pdf"


# --- PUBLIC CONTENT ROUTES ---

@content_bp.route("/duyurular/<string:slug>")
@content_bp.route("/duyuru/<string:slug>")
def public_announcement_detail(slug):
    announcement = _safe_public_result(
        lambda: Announcement.query.filter_by(slug=slug, is_published=True).first(),
        ("announcement",),
        None,
    )
    if announcement is None:
        abort(404)
    if _current_workflow_status("announcement", announcement) != WORKFLOW_PUBLISHED:
        abort(404)
    if homepage_demo_is_active() and not is_homepage_demo_item(announcement):
        abort(404)
    seo = _seo_for_announcement(announcement.id)
    return render_template("announcement_detail.html", announcement=announcement, seo=seo, **_public_layout_context())


@content_bp.route("/duyurular")
def public_announcements():
    announcements = _safe_public_result(
        lambda: Announcement.query.filter_by(is_published=True).order_by(
            Announcement.published_at.desc(), Announcement.id.desc()
        ).all(),
        ("announcement",),
        [],
    )
    announcements = [item for item in announcements if _current_workflow_status("announcement", item) == WORKFLOW_PUBLISHED]
    announcements = filter_homepage_demo_items(announcements)
    seo_map = _seo_map_for_announcements(announcements)
    return render_template("announcements.html", announcements=announcements, seo_map=seo_map, **_public_layout_context())


@content_bp.route("/dokumanlar")
@content_bp.route("/formlar")
def public_documents():
    documents = _safe_public_result(
        lambda: DocumentResource.query.filter_by(is_active=True).order_by(
            DocumentResource.order_index.asc(), DocumentResource.id.asc()
        ).all(),
        ("document_resource",),
        [],
    )
    documents = [item for item in documents if _current_workflow_status("document", item) == WORKFLOW_PUBLISHED]
    documents = filter_homepage_demo_items(documents)
    return render_template("documents.html", documents=documents, **_public_layout_context())


@content_bp.route("/hakkimizda/biz-kimiz")
def public_about_who_we_are():
    sections = _published_sections_for_keys("about")
    entries = sections or [None]
    cards = [
        _section_entry(
            item,
            {
                "title": "Biz Kimiz?",
                "subtitle": "Tim Yapısı",
                "content": "ARFF özel arama kurtarma gönüllülerinin birlikte hareket ettiği, sahaya yakın ve dayanışma odaklı bir ekip yapısı.",
                "image_url": "",
            },
        )
        for item in entries
    ]
    return render_template(
        "public_info_page.html",
        page_group="Hakkımızda",
        page_title="Biz Kimiz?",
        page_lead="Ekibin nasıl çalıştığını, sahaya nasıl hazır kaldığını ve birlikte hareket etme biçimini burada bulabilirsiniz.",
        cards=cards,
        page_variant="feature",
        **_public_layout_context(),
    )


@content_bp.route("/hakkimizda/misyon-ve-vizyon")
def public_about_mission_vision():
    mission_sections = _published_sections_for_keys("mission")
    vision_sections = _published_sections_for_keys("vision")
    cards = [
        _section_entry(
            mission_sections[0] if mission_sections else None,
            {
                "title": "Misyon",
                "subtitle": "Ortak Yön",
                "content": "Hazırlığı canlı tutmak, sahada birbirimize destek olmak ve ihtiyaç anında hızlıca organize olmak.",
            },
        ),
        _section_entry(
            vision_sections[0] if vision_sections else None,
            {
                "title": "Vizyon",
                "subtitle": "Uzun Vadeli Bakış",
                "content": "Güven, gönüllülük ve ekip dayanışmasını koruyarak güçlü bir saha kültürü oluşturmak.",
            },
        ),
    ]
    return render_template(
        "public_info_page.html",
        page_group="Hakkımızda",
        page_title="Misyon ve Vizyon",
        page_lead="Neden birlikte hareket ettiğimizi ve uzun vadede nasıl bir ekip kültürü kurmak istediğimizi anlatan iki kısa başlık.",
        cards=cards,
        page_variant="duo",
        **_public_layout_context(),
    )


@content_bp.route("/hakkimizda/etik-degerler")
def public_about_ethics():
    sections = _published_sections_for_keys("ethics")
    entries = sections or [None]
    cards = [
        _section_entry(
            item,
            {
                "title": "Etik Değerler",
                "subtitle": "Tim Kültürü",
                "content": "Sahada saygı, sorumluluk, güven ve gönüllülük çizgisini birlikte korumak.",
            },
        )
        for item in entries
    ]
    return render_template(
        "public_info_page.html",
        page_group="Hakkımızda",
        page_title="Etik Değerler",
        page_lead="Tim kültürünü güçlü tutan ilkeler; güven, dayanışma ve sorumluluk duygusunun günlük sahaya nasıl yansıdığını gösterir.",
        cards=cards,
        page_variant="feature",
        **_public_layout_context(),
    )


@content_bp.route("/faaliyetlerimiz/egitimler")
def public_training_page():
    sections = _published_sections_for_keys("training")
    entries = sections or [None]
    cards = [
        _section_entry(
            item,
            {
                "title": "Eğitimler",
                "subtitle": "Hazırlık Modülü",
                "content": "Teknik tekrarlar, ekip içi hazırlık oturumları ve sahaya dönük pratiklerle tim refleksini canlı tutan çalışmalar.",
            },
        )
        for item in entries
    ]
    return render_template(
        "public_info_page.html",
        page_group="Faaliyetlerimiz",
        page_title="Eğitimler",
        page_lead="Yakın dönem eğitimler, ekip içi tekrarlar ve hazırlığı diri tutan çalışmalar bu sayfada ayrı bir başlık altında toplanır.",
        cards=cards,
        page_variant="modules",
        **_public_layout_context(),
    )


@content_bp.route("/faaliyetlerimiz/tatbikatlar")
def public_drills_page():
    sections = _published_sections_for_keys("exercise", "operation")
    entries = sections or [None]
    cards = [
        _section_entry(
            item,
            {
                "title": "Tatbikatlar",
                "subtitle": "Uygulama Modülü",
                "content": "Saha uyumunu, hızını ve görev paylaşımını canlı tutan uygulamalı çalışmalar ve tatbikat notları.",
            },
        )
        for item in entries
    ]
    return render_template(
        "public_info_page.html",
        page_group="Faaliyetlerimiz",
        page_title="Tatbikatlar",
        page_lead="Tatbikat odaklı çalışmalar; senaryo pratikleri, görev paylaşımı ve ekip koordinasyonunun sahaya yansıyan tarafını gösterir.",
        cards=cards,
        page_variant="modules",
        **_public_layout_context(),
    )


# --- HOMEPAGE MANAGEMENT ROUTES (ADMIN + EDITOR) ---

@content_bp.route("/admin/homepage")
@login_required
@homepage_editor_required
def homepage_dashboard():
    slider_rows = HomeSlider.query.all()
    section_rows = HomeSection.query.all()
    announcement_rows = Announcement.query.all()
    document_rows = DocumentResource.query.all()
    stat_rows = HomeStatCard.query.all()
    quicklink_rows = HomeQuickLink.query.all()

    slider_wf = _workflow_map("slider", slider_rows)
    section_wf = _workflow_map("section", section_rows)
    announcement_wf = _workflow_map("announcement", announcement_rows)
    document_wf = _workflow_map("document", document_rows)
    stat_wf = _workflow_map("stat", stat_rows)
    quicklink_wf = _workflow_map("quicklink", quicklink_rows)

    def _count_status(workflow_rows, status):
        return sum(1 for row in workflow_rows.values() if row.status == status)

    return render_template(
        "admin/homepage_dashboard.html",
        slider_count=len(slider_rows),
        section_count=len(section_rows),
        announcement_count=len(announcement_rows),
        document_count=len(document_rows),
        stat_count=len(stat_rows),
        quicklink_count=len(quicklink_rows),
        published_count=(
            _count_status(slider_wf, WORKFLOW_PUBLISHED)
            + _count_status(section_wf, WORKFLOW_PUBLISHED)
            + _count_status(announcement_wf, WORKFLOW_PUBLISHED)
            + _count_status(document_wf, WORKFLOW_PUBLISHED)
            + _count_status(stat_wf, WORKFLOW_PUBLISHED)
            + _count_status(quicklink_wf, WORKFLOW_PUBLISHED)
        ),
        draft_count=(
            _count_status(slider_wf, WORKFLOW_DRAFT)
            + _count_status(section_wf, WORKFLOW_DRAFT)
            + _count_status(announcement_wf, WORKFLOW_DRAFT)
            + _count_status(document_wf, WORKFLOW_DRAFT)
            + _count_status(stat_wf, WORKFLOW_DRAFT)
            + _count_status(quicklink_wf, WORKFLOW_DRAFT)
        ),
    )


@content_bp.route("/admin/homepage/sliders")
@login_required
@homepage_editor_required
def homepage_slider_list():
    query = HomeSlider.query.order_by(HomeSlider.order_index.asc(), HomeSlider.id.asc())
    sliders, search_query, selected_status = _apply_common_filters(query, HomeSlider, "slider")
    workflow_map = _workflow_map("slider", sliders)
    return render_template(
        "admin/homepage_slider_list.html",
        sliders=sliders,
        workflow_map=workflow_map,
        search_query=search_query,
        selected_status=selected_status,
    )


@content_bp.route("/admin/homepage/sliders/new", methods=["GET", "POST"])
@login_required
@homepage_editor_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"), methods=["POST"])
def homepage_slider_create():
    if request.method == "POST":
        title = guvenli_metin(request.form.get("title") or "").strip()
        if not title:
            flash("Slider başlığı zorunludur.", "danger")
            return redirect(url_for("content.homepage_slider_create"))

        image_path = guvenli_metin(request.form.get("image_path") or request.form.get("image_url") or "").strip()
        if not _validate_media_path(image_path):
            flash("Slider görsel yolu güvenlik doğrulamasını geçemedi.", "danger")
            return redirect(url_for("content.homepage_slider_create"))

        fallback_active = _to_bool(request.form.get("is_active"))
        workflow_status = _resolve_status_from_form(WORKFLOW_PUBLISHED if fallback_active else WORKFLOW_DRAFT)

        slider = HomeSlider(
            title=title,
            subtitle=guvenli_metin(request.form.get("subtitle") or "").strip(),
            description=guvenli_metin(request.form.get("description") or "").strip(),
            image_url=image_path,
            button_text=guvenli_metin(request.form.get("button_text") or "").strip() or "Detaylı Bilgi",
            button_link=guvenli_metin(request.form.get("button_link") or "").strip() or "#",
            order_index=_normalize_order_index(request.form.get("order_index"), 0),
            is_active=fallback_active,
        )
        db.session.add(slider)
        db.session.flush()
        _set_workflow_status("slider", slider, workflow_status, action="create")
        db.session.commit()
        log_kaydet("Anasayfa İçerik", f"Slider eklendi: {slider.title}")
        audit_log(
            "homepage.slider.create",
            outcome="success",
            slider_id=slider.id,
            title=slider.title,
            status=workflow_status,
        )
        flash("Slider başarıyla eklendi.", "success")
        return redirect(url_for("content.homepage_slider_list"))

    return render_template(
        "admin/homepage_slider_form.html",
        slider=None,
        workflow_status=WORKFLOW_DRAFT,
    )


@content_bp.route("/admin/homepage/sliders/<int:slider_id>/edit", methods=["GET", "POST"])
@login_required
@homepage_editor_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"), methods=["POST"])
def homepage_slider_edit(slider_id):
    slider = HomeSlider.query.get_or_404(slider_id)
    if request.method == "POST":
        title = guvenli_metin(request.form.get("title") or "").strip()
        if not title:
            flash("Slider başlığı zorunludur.", "danger")
            return redirect(url_for("content.homepage_slider_edit", slider_id=slider.id))

        image_path = guvenli_metin(request.form.get("image_path") or request.form.get("image_url") or "").strip()
        if not _validate_media_path(image_path):
            flash("Slider görsel yolu güvenlik doğrulamasını geçemedi.", "danger")
            return redirect(url_for("content.homepage_slider_edit", slider_id=slider.id))

        fallback_active = _to_bool(request.form.get("is_active"))
        workflow_status = _resolve_status_from_form(WORKFLOW_PUBLISHED if fallback_active else WORKFLOW_DRAFT)

        slider.title = title
        slider.subtitle = guvenli_metin(request.form.get("subtitle") or "").strip()
        slider.description = guvenli_metin(request.form.get("description") or "").strip()
        slider.image_url = image_path
        slider.button_text = guvenli_metin(request.form.get("button_text") or "").strip() or "Detaylı Bilgi"
        slider.button_link = guvenli_metin(request.form.get("button_link") or "").strip() or "#"
        slider.order_index = _normalize_order_index(request.form.get("order_index"), 0)
        slider.is_active = fallback_active
        _set_workflow_status("slider", slider, workflow_status, action="update")
        db.session.commit()
        log_kaydet("Anasayfa İçerik", f"Slider güncellendi: {slider.title}")
        audit_log(
            "homepage.slider.update",
            outcome="success",
            slider_id=slider.id,
            title=slider.title,
            status=workflow_status,
        )
        flash("Slider güncellendi.", "success")
        return redirect(url_for("content.homepage_slider_list"))

    return render_template(
        "admin/homepage_slider_form.html",
        slider=slider,
        workflow_status=_current_workflow_status("slider", slider),
    )


@content_bp.route("/admin/homepage/sliders/<int:slider_id>/toggle", methods=["POST"])
@login_required
@homepage_editor_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
def homepage_slider_toggle(slider_id):
    slider = HomeSlider.query.get_or_404(slider_id)
    current_status = _current_workflow_status("slider", slider)
    next_status = WORKFLOW_PASSIVE if current_status == WORKFLOW_PUBLISHED else WORKFLOW_PUBLISHED
    _set_workflow_status("slider", slider, next_status, action="toggle")
    db.session.commit()
    log_kaydet("Anasayfa İçerik", f"Slider durumu değiştirildi: {slider.title} -> {next_status}")
    audit_log(
        "homepage.slider.toggle",
        outcome="success",
        slider_id=slider.id,
        status=next_status,
    )
    flash("Slider durumu güncellendi.", "success")
    return redirect(url_for("content.homepage_slider_list"))


@content_bp.route("/admin/homepage/sliders/<int:slider_id>/delete", methods=["POST"])
@login_required
@homepage_editor_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
def homepage_slider_delete(slider_id):
    slider = HomeSlider.query.get_or_404(slider_id)
    ContentWorkflow.query.filter_by(entity_type="slider", entity_id=slider.id).delete()
    db.session.delete(slider)
    db.session.commit()
    audit_log("homepage.slider.delete", outcome="success", slider_id=slider.id)
    flash("Slider silindi.", "info")
    return redirect(url_for("content.homepage_slider_list"))


@content_bp.route("/admin/homepage/sections")
@login_required
@homepage_editor_required
def homepage_section_list():
    query = HomeSection.query.order_by(HomeSection.section_key.asc(), HomeSection.order_index.asc())
    sections, search_query, selected_status = _apply_common_filters(query, HomeSection, "section")
    workflow_map = _workflow_map("section", sections)
    return render_template(
        "admin/homepage_section_list.html",
        sections=sections,
        workflow_map=workflow_map,
        search_query=search_query,
        selected_status=selected_status,
    )


@content_bp.route("/admin/homepage/sections/new", methods=["GET", "POST"])
@login_required
@homepage_editor_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"), methods=["POST"])
def homepage_section_create():
    if request.method == "POST":
        title = guvenli_metin(request.form.get("title") or "").strip()
        section_key = guvenli_metin(request.form.get("section_key") or "").strip()
        if not title or not section_key:
            flash("Bölüm anahtarı ve başlık zorunludur.", "danger")
            return redirect(url_for("content.homepage_section_create"))

        image_path = guvenli_metin(request.form.get("image_path") or request.form.get("image_url") or "").strip()
        if not _validate_media_path(image_path):
            flash("Bölüm görsel yolu güvenlik doğrulamasını geçemedi.", "danger")
            return redirect(url_for("content.homepage_section_create"))

        fallback_active = _to_bool(request.form.get("is_active"))
        workflow_status = _resolve_status_from_form(WORKFLOW_PUBLISHED if fallback_active else WORKFLOW_DRAFT)

        section = HomeSection(
            section_key=section_key,
            title=title,
            subtitle=guvenli_metin(request.form.get("subtitle") or "").strip(),
            content=guvenli_metin(request.form.get("content") or "").strip(),
            icon=guvenli_metin(request.form.get("icon") or "").strip(),
            image_url=image_path,
            order_index=_normalize_order_index(request.form.get("order_index"), 0),
            is_active=fallback_active,
        )
        db.session.add(section)
        db.session.flush()
        _set_workflow_status("section", section, workflow_status, action="create")
        db.session.commit()
        log_kaydet("Anasayfa İçerik", f"Bölüm eklendi: {section.section_key} / {section.title}")
        audit_log(
            "homepage.section.create",
            outcome="success",
            section_id=section.id,
            key=section.section_key,
            status=workflow_status,
        )
        flash("Anasayfa bölümü eklendi.", "success")
        return redirect(url_for("content.homepage_section_list"))

    return render_template(
        "admin/homepage_section_form.html",
        section=None,
        workflow_status=WORKFLOW_DRAFT,
    )


@content_bp.route("/admin/homepage/sections/<int:section_id>/edit", methods=["GET", "POST"])
@login_required
@homepage_editor_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"), methods=["POST"])
def homepage_section_edit(section_id):
    section = HomeSection.query.get_or_404(section_id)
    if request.method == "POST":
        title = guvenli_metin(request.form.get("title") or "").strip()
        section_key = guvenli_metin(request.form.get("section_key") or "").strip()
        if not title or not section_key:
            flash("Bölüm anahtarı ve başlık zorunludur.", "danger")
            return redirect(url_for("content.homepage_section_edit", section_id=section.id))

        image_path = guvenli_metin(request.form.get("image_path") or request.form.get("image_url") or "").strip()
        if not _validate_media_path(image_path):
            flash("Bölüm görsel yolu güvenlik doğrulamasını geçemedi.", "danger")
            return redirect(url_for("content.homepage_section_edit", section_id=section.id))

        fallback_active = _to_bool(request.form.get("is_active"))
        workflow_status = _resolve_status_from_form(WORKFLOW_PUBLISHED if fallback_active else WORKFLOW_DRAFT)

        section.section_key = section_key
        section.title = title
        section.subtitle = guvenli_metin(request.form.get("subtitle") or "").strip()
        section.content = guvenli_metin(request.form.get("content") or "").strip()
        section.icon = guvenli_metin(request.form.get("icon") or "").strip()
        section.image_url = image_path
        section.order_index = _normalize_order_index(request.form.get("order_index"), 0)
        section.is_active = fallback_active
        _set_workflow_status("section", section, workflow_status, action="update")
        db.session.commit()
        log_kaydet("Anasayfa İçerik", f"Bölüm güncellendi: {section.section_key} / {section.title}")
        audit_log(
            "homepage.section.update",
            outcome="success",
            section_id=section.id,
            key=section.section_key,
            status=workflow_status,
        )
        flash("Bölüm güncellendi.", "success")
        return redirect(url_for("content.homepage_section_list"))

    return render_template(
        "admin/homepage_section_form.html",
        section=section,
        workflow_status=_current_workflow_status("section", section),
    )


@content_bp.route("/admin/homepage/sections/<int:section_id>/toggle", methods=["POST"])
@login_required
@homepage_editor_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
def homepage_section_toggle(section_id):
    section = HomeSection.query.get_or_404(section_id)
    current_status = _current_workflow_status("section", section)
    next_status = WORKFLOW_PASSIVE if current_status == WORKFLOW_PUBLISHED else WORKFLOW_PUBLISHED
    _set_workflow_status("section", section, next_status, action="toggle")
    db.session.commit()
    log_kaydet("Anasayfa İçerik", f"Bölüm durumu değiştirildi: {section.section_key} -> {next_status}")
    audit_log(
        "homepage.section.toggle",
        outcome="success",
        section_id=section.id,
        status=next_status,
    )
    flash("Bölüm durumu güncellendi.", "success")
    return redirect(url_for("content.homepage_section_list"))


@content_bp.route("/admin/homepage/sections/<int:section_id>/delete", methods=["POST"])
@login_required
@homepage_editor_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
def homepage_section_delete(section_id):
    section = HomeSection.query.get_or_404(section_id)
    ContentWorkflow.query.filter_by(entity_type="section", entity_id=section.id).delete()
    db.session.delete(section)
    db.session.commit()
    audit_log("homepage.section.delete", outcome="success", section_id=section.id)
    flash("Bölüm silindi.", "info")
    return redirect(url_for("content.homepage_section_list"))


@content_bp.route("/admin/homepage/announcements")
@login_required
@homepage_editor_required
def homepage_announcements_list():
    query = Announcement.query.order_by(Announcement.created_at.desc())
    announcements, search_query, selected_status = _apply_common_filters(query, Announcement, "announcement")
    workflow_map = _workflow_map("announcement", announcements)
    seo_map = _seo_map_for_announcements(announcements)
    return render_template(
        "admin/homepage_announcements_list.html",
        announcements=announcements,
        workflow_map=workflow_map,
        seo_map=seo_map,
        search_query=search_query,
        selected_status=selected_status,
    )


@content_bp.route("/admin/homepage/announcements/new", methods=["GET", "POST"])
@login_required
@homepage_editor_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"), methods=["POST"])
def homepage_announcement_create():
    if request.method == "POST":
        title = guvenli_metin(request.form.get("title") or "").strip()
        content = guvenli_metin(request.form.get("content") or "").strip()
        if not title or not content:
            flash("Duyuru başlığı ve içeriği zorunludur.", "danger")
            return redirect(url_for("content.homepage_announcement_create"))

        raw_slug = guvenli_metin(request.form.get("slug") or "").strip() or _slugify(title)
        slug = _unique_slug(_slugify(raw_slug))
        fallback_publish = _to_bool(request.form.get("is_published"))
        workflow_status = _resolve_status_from_form(WORKFLOW_PUBLISHED if fallback_publish else WORKFLOW_DRAFT)
        published_at = _parse_datetime_input(request.form.get("published_at"))

        cover_image = guvenli_metin(request.form.get("cover_image") or "").strip()
        if not _validate_media_path(cover_image):
            flash("Duyuru görsel yolu güvenlik doğrulamasını geçemedi.", "danger")
            return redirect(url_for("content.homepage_announcement_create"))

        announcement = Announcement(
            title=title,
            slug=slug,
            summary=guvenli_metin(request.form.get("summary") or "").strip(),
            content=content,
            cover_image=cover_image,
            is_published=fallback_publish,
            published_at=published_at or (get_tr_now() if fallback_publish else None),
            author_id=current_user.id,
        )
        db.session.add(announcement)
        db.session.flush()

        seo = _ensure_announcement_seo(announcement.id)
        seo.meta_title = guvenli_metin(request.form.get("meta_title") or "").strip()
        seo.meta_description = guvenli_metin(request.form.get("meta_description") or "").strip()
        _set_workflow_status("announcement", announcement, workflow_status, action="create")

        db.session.commit()
        log_kaydet("Anasayfa İçerik", f"Duyuru eklendi: {announcement.title} ({announcement.slug})")
        audit_log(
            "homepage.announcement.create",
            outcome="success",
            announcement_id=announcement.id,
            slug=announcement.slug,
            status=workflow_status,
        )
        flash("Duyuru kaydedildi.", "success")
        return redirect(url_for("content.homepage_announcements_list"))

    return render_template(
        "admin/homepage_announcement_form.html",
        announcement=None,
        seo=None,
        workflow_status=WORKFLOW_DRAFT,
    )


@content_bp.route("/admin/homepage/announcements/<int:announcement_id>/edit", methods=["GET", "POST"])
@login_required
@homepage_editor_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"), methods=["POST"])
def homepage_announcement_edit(announcement_id):
    announcement = Announcement.query.get_or_404(announcement_id)
    if request.method == "POST":
        title = guvenli_metin(request.form.get("title") or "").strip()
        content = guvenli_metin(request.form.get("content") or "").strip()
        if not title or not content:
            flash("Duyuru başlığı ve içeriği zorunludur.", "danger")
            return redirect(url_for("content.homepage_announcement_edit", announcement_id=announcement.id))

        cover_image = guvenli_metin(request.form.get("cover_image") or "").strip()
        if not _validate_media_path(cover_image):
            flash("Duyuru görsel yolu güvenlik doğrulamasını geçemedi.", "danger")
            return redirect(url_for("content.homepage_announcement_edit", announcement_id=announcement.id))

        raw_slug = guvenli_metin(request.form.get("slug") or "").strip() or _slugify(title)
        fallback_publish = _to_bool(request.form.get("is_published"))
        workflow_status = _resolve_status_from_form(WORKFLOW_PUBLISHED if fallback_publish else WORKFLOW_DRAFT)
        published_at = _parse_datetime_input(request.form.get("published_at"))
        announcement.slug = _unique_slug(_slugify(raw_slug), announcement.id)
        announcement.title = title
        announcement.summary = guvenli_metin(request.form.get("summary") or "").strip()
        announcement.content = content
        announcement.cover_image = cover_image
        announcement.is_published = fallback_publish
        announcement.published_at = published_at or (
            announcement.published_at if fallback_publish and announcement.published_at else get_tr_now() if fallback_publish else None
        )

        seo = _ensure_announcement_seo(announcement.id)
        seo.meta_title = guvenli_metin(request.form.get("meta_title") or "").strip()
        seo.meta_description = guvenli_metin(request.form.get("meta_description") or "").strip()
        _set_workflow_status("announcement", announcement, workflow_status, action="update")

        db.session.commit()
        log_kaydet("Anasayfa İçerik", f"Duyuru güncellendi: {announcement.title} ({announcement.slug})")
        audit_log(
            "homepage.announcement.update",
            outcome="success",
            announcement_id=announcement.id,
            slug=announcement.slug,
            status=workflow_status,
        )
        flash("Duyuru güncellendi.", "success")
        return redirect(url_for("content.homepage_announcements_list"))

    return render_template(
        "admin/homepage_announcement_form.html",
        announcement=announcement,
        seo=_seo_for_announcement(announcement.id),
        workflow_status=_current_workflow_status("announcement", announcement),
    )


@content_bp.route("/admin/homepage/announcements/<int:announcement_id>/toggle", methods=["POST"])
@login_required
@homepage_editor_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
def homepage_announcement_toggle(announcement_id):
    announcement = Announcement.query.get_or_404(announcement_id)
    current_status = _current_workflow_status("announcement", announcement)
    next_status = WORKFLOW_PASSIVE if current_status == WORKFLOW_PUBLISHED else WORKFLOW_PUBLISHED
    _set_workflow_status("announcement", announcement, next_status, action="toggle")
    db.session.commit()
    log_kaydet("Anasayfa İçerik", f"Duyuru yayın durumu değiştirildi: {announcement.slug} -> {next_status}")
    audit_log(
        "homepage.announcement.toggle",
        outcome="success",
        announcement_id=announcement.id,
        status=next_status,
    )
    flash("Duyuru yayın durumu güncellendi.", "success")
    return redirect(url_for("content.homepage_announcements_list"))


@content_bp.route("/admin/homepage/announcements/<int:announcement_id>/delete", methods=["POST"])
@login_required
@homepage_editor_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
def homepage_announcement_delete(announcement_id):
    announcement = Announcement.query.get_or_404(announcement_id)
    ContentWorkflow.query.filter_by(entity_type="announcement", entity_id=announcement.id).delete()
    ContentSEO.query.filter_by(entity_type="announcement", entity_id=announcement.id).delete()
    db.session.delete(announcement)
    db.session.commit()
    audit_log("homepage.announcement.delete", outcome="success", announcement_id=announcement.id)
    flash("Duyuru silindi.", "info")
    return redirect(url_for("content.homepage_announcements_list"))


@content_bp.route("/admin/homepage/documents")
@login_required
@homepage_editor_required
def homepage_documents_list():
    query = DocumentResource.query.order_by(DocumentResource.order_index.asc(), DocumentResource.id.asc())
    documents, search_query, selected_status = _apply_common_filters(query, DocumentResource, "document")
    workflow_map = _workflow_map("document", documents)
    return render_template(
        "admin/homepage_documents_list.html",
        documents=documents,
        workflow_map=workflow_map,
        search_query=search_query,
        selected_status=selected_status,
    )


@content_bp.route("/admin/homepage/documents/new", methods=["GET", "POST"])
@login_required
@homepage_editor_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"), methods=["POST"])
def homepage_document_create():
    if request.method == "POST":
        title = guvenli_metin(request.form.get("title") or "").strip()
        if not title:
            flash("Doküman başlığı zorunludur.", "danger")
            return redirect(url_for("content.homepage_document_create"))

        file_path = guvenli_metin(request.form.get("file_path") or "").strip()
        if not _validate_document_path(file_path):
            flash("Doküman bağlantısı güvenlik doğrulamasını geçemedi.", "danger")
            return redirect(url_for("content.homepage_document_create"))

        fallback_active = _to_bool(request.form.get("is_active"))
        workflow_status = _resolve_status_from_form(WORKFLOW_PUBLISHED if fallback_active else WORKFLOW_DRAFT)

        document = DocumentResource(
            title=title,
            description=guvenli_metin(request.form.get("description") or "").strip(),
            file_path=file_path,
            category=guvenli_metin(request.form.get("category") or "").strip(),
            order_index=_normalize_order_index(request.form.get("order_index"), 0),
            is_active=fallback_active,
        )
        db.session.add(document)
        db.session.flush()
        _set_workflow_status("document", document, workflow_status, action="create")
        db.session.commit()
        log_kaydet("Anasayfa İçerik", f"Doküman eklendi: {document.title}")
        audit_log(
            "homepage.document.create",
            outcome="success",
            document_id=document.id,
            title=document.title,
            status=workflow_status,
        )
        flash("Doküman kaydedildi.", "success")
        return redirect(url_for("content.homepage_documents_list"))

    return render_template(
        "admin/homepage_documents_form.html",
        document=None,
        workflow_status=WORKFLOW_DRAFT,
    )


@content_bp.route("/admin/homepage/documents/<int:document_id>/edit", methods=["GET", "POST"])
@login_required
@homepage_editor_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"), methods=["POST"])
def homepage_document_edit(document_id):
    document = DocumentResource.query.get_or_404(document_id)
    if request.method == "POST":
        title = guvenli_metin(request.form.get("title") or "").strip()
        if not title:
            flash("Doküman başlığı zorunludur.", "danger")
            return redirect(url_for("content.homepage_document_edit", document_id=document.id))

        file_path = guvenli_metin(request.form.get("file_path") or "").strip()
        if not _validate_document_path(file_path):
            flash("Doküman bağlantısı güvenlik doğrulamasını geçemedi.", "danger")
            return redirect(url_for("content.homepage_document_edit", document_id=document.id))

        fallback_active = _to_bool(request.form.get("is_active"))
        workflow_status = _resolve_status_from_form(WORKFLOW_PUBLISHED if fallback_active else WORKFLOW_DRAFT)

        document.title = title
        document.description = guvenli_metin(request.form.get("description") or "").strip()
        document.file_path = file_path
        document.category = guvenli_metin(request.form.get("category") or "").strip()
        document.order_index = _normalize_order_index(request.form.get("order_index"), 0)
        document.is_active = fallback_active
        _set_workflow_status("document", document, workflow_status, action="update")
        db.session.commit()
        log_kaydet("Anasayfa İçerik", f"Doküman güncellendi: {document.title}")
        audit_log(
            "homepage.document.update",
            outcome="success",
            document_id=document.id,
            title=document.title,
            status=workflow_status,
        )
        flash("Doküman güncellendi.", "success")
        return redirect(url_for("content.homepage_documents_list"))

    return render_template(
        "admin/homepage_documents_form.html",
        document=document,
        workflow_status=_current_workflow_status("document", document),
    )


@content_bp.route("/admin/homepage/documents/<int:document_id>/toggle", methods=["POST"])
@login_required
@homepage_editor_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
def homepage_document_toggle(document_id):
    document = DocumentResource.query.get_or_404(document_id)
    current_status = _current_workflow_status("document", document)
    next_status = WORKFLOW_PASSIVE if current_status == WORKFLOW_PUBLISHED else WORKFLOW_PUBLISHED
    _set_workflow_status("document", document, next_status, action="toggle")
    db.session.commit()
    log_kaydet("Anasayfa İçerik", f"Doküman durumu değiştirildi: {document.title} -> {next_status}")
    audit_log(
        "homepage.document.toggle",
        outcome="success",
        document_id=document.id,
        status=next_status,
    )
    flash("Doküman durumu güncellendi.", "success")
    return redirect(url_for("content.homepage_documents_list"))


@content_bp.route("/admin/homepage/documents/<int:document_id>/delete", methods=["POST"])
@login_required
@homepage_editor_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
def homepage_document_delete(document_id):
    document = DocumentResource.query.get_or_404(document_id)
    ContentWorkflow.query.filter_by(entity_type="document", entity_id=document.id).delete()
    db.session.delete(document)
    db.session.commit()
    audit_log("homepage.document.delete", outcome="success", document_id=document.id)
    flash("Doküman silindi.", "info")
    return redirect(url_for("content.homepage_documents_list"))


@content_bp.route("/admin/homepage/stats")
@login_required
@homepage_editor_required
def homepage_stats_list():
    query = HomeStatCard.query.order_by(HomeStatCard.order_index.asc(), HomeStatCard.id.asc())
    stats, search_query, selected_status = _apply_common_filters(query, HomeStatCard, "stat")
    workflow_map = _workflow_map("stat", stats)
    return render_template(
        "admin/homepage_stats_list.html",
        stats=stats,
        workflow_map=workflow_map,
        search_query=search_query,
        selected_status=selected_status,
    )


@content_bp.route("/admin/homepage/stats/new", methods=["POST"])
@login_required
@homepage_editor_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
def homepage_stat_create():
    title = guvenli_metin(request.form.get("title") or "").strip()
    value_text = guvenli_metin(request.form.get("value_text") or "").strip()
    if not title or not value_text:
        flash("İstatistik başlığı ve değeri zorunludur.", "danger")
        return redirect(url_for("content.homepage_stats_list"))

    fallback_active = _to_bool(request.form.get("is_active"))
    workflow_status = _resolve_status_from_form(WORKFLOW_PUBLISHED if fallback_active else WORKFLOW_DRAFT)

    card = HomeStatCard(
        title=title,
        value_text=value_text,
        subtitle=guvenli_metin(request.form.get("subtitle") or "").strip(),
        icon=guvenli_metin(request.form.get("icon") or "").strip(),
        order_index=_normalize_order_index(request.form.get("order_index"), 0),
        is_active=fallback_active,
    )
    db.session.add(card)
    db.session.flush()
    _set_workflow_status("stat", card, workflow_status, action="create")
    db.session.commit()
    audit_log("homepage.stat.create", outcome="success", stat_id=card.id, status=workflow_status)
    log_kaydet("Anasayfa İçerik", f"İstatistik kartı eklendi: {card.title}")
    flash("İstatistik kartı eklendi.", "success")
    return redirect(url_for("content.homepage_stats_list"))


@content_bp.route("/admin/homepage/stats/<int:card_id>/edit", methods=["POST"])
@login_required
@homepage_editor_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
def homepage_stat_edit(card_id):
    card = HomeStatCard.query.get_or_404(card_id)
    title = guvenli_metin(request.form.get("title") or "").strip()
    value_text = guvenli_metin(request.form.get("value_text") or "").strip()
    if not title or not value_text:
        flash("İstatistik başlığı ve değeri zorunludur.", "danger")
        return redirect(url_for("content.homepage_stats_list"))

    fallback_active = _to_bool(request.form.get("is_active"))
    workflow_status = _resolve_status_from_form(WORKFLOW_PUBLISHED if fallback_active else WORKFLOW_DRAFT)

    card.title = title
    card.value_text = value_text
    card.subtitle = guvenli_metin(request.form.get("subtitle") or "").strip()
    card.icon = guvenli_metin(request.form.get("icon") or "").strip()
    card.order_index = _normalize_order_index(request.form.get("order_index"), 0)
    card.is_active = fallback_active
    _set_workflow_status("stat", card, workflow_status, action="update")
    db.session.commit()
    audit_log("homepage.stat.update", outcome="success", stat_id=card.id, status=workflow_status)
    log_kaydet("Anasayfa İçerik", f"İstatistik kartı güncellendi: {card.title}")
    flash("İstatistik kartı güncellendi.", "success")
    return redirect(url_for("content.homepage_stats_list"))


@content_bp.route("/admin/homepage/stats/<int:card_id>/toggle", methods=["POST"])
@login_required
@homepage_editor_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
def homepage_stat_toggle(card_id):
    card = HomeStatCard.query.get_or_404(card_id)
    current_status = _current_workflow_status("stat", card)
    next_status = WORKFLOW_PASSIVE if current_status == WORKFLOW_PUBLISHED else WORKFLOW_PUBLISHED
    _set_workflow_status("stat", card, next_status, action="toggle")
    db.session.commit()
    audit_log("homepage.stat.toggle", outcome="success", stat_id=card.id, status=next_status)
    log_kaydet("Anasayfa İçerik", f"İstatistik kartı durumu değiştirildi: {card.title} -> {next_status}")
    flash("Kart durumu güncellendi.", "success")
    return redirect(url_for("content.homepage_stats_list"))


@content_bp.route("/admin/homepage/stats/<int:card_id>/delete", methods=["POST"])
@login_required
@homepage_editor_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
def homepage_stat_delete(card_id):
    card = HomeStatCard.query.get_or_404(card_id)
    ContentWorkflow.query.filter_by(entity_type="stat", entity_id=card.id).delete()
    db.session.delete(card)
    db.session.commit()
    audit_log("homepage.stat.delete", outcome="success", stat_id=card.id)
    flash("Kart silindi.", "info")
    return redirect(url_for("content.homepage_stats_list"))


@content_bp.route("/admin/homepage/quick-links")
@login_required
@homepage_editor_required
def homepage_quicklinks_list():
    query = HomeQuickLink.query.order_by(HomeQuickLink.order_index.asc(), HomeQuickLink.id.asc())
    links, search_query, selected_status = _apply_common_filters(query, HomeQuickLink, "quicklink")
    workflow_map = _workflow_map("quicklink", links)
    return render_template(
        "admin/homepage_quicklinks_list.html",
        links=links,
        workflow_map=workflow_map,
        search_query=search_query,
        selected_status=selected_status,
    )


@content_bp.route("/admin/homepage/quick-links/new", methods=["POST"])
@login_required
@homepage_editor_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
def homepage_quicklink_create():
    title = guvenli_metin(request.form.get("title") or "").strip()
    if not title:
        flash("Hızlı bağlantı başlığı zorunludur.", "danger")
        return redirect(url_for("content.homepage_quicklinks_list"))

    link_url = guvenli_metin(request.form.get("link_url") or "").strip() or "#"
    if not _validate_link_url(link_url):
        flash("Bağlantı URL değeri güvenlik doğrulamasını geçemedi.", "danger")
        return redirect(url_for("content.homepage_quicklinks_list"))

    fallback_active = _to_bool(request.form.get("is_active"))
    workflow_status = _resolve_status_from_form(WORKFLOW_PUBLISHED if fallback_active else WORKFLOW_DRAFT)

    link = HomeQuickLink(
        title=title,
        description=guvenli_metin(request.form.get("description") or "").strip(),
        link_url=link_url,
        icon=guvenli_metin(request.form.get("icon") or "").strip(),
        order_index=_normalize_order_index(request.form.get("order_index"), 0),
        is_active=fallback_active,
    )
    db.session.add(link)
    db.session.flush()
    _set_workflow_status("quicklink", link, workflow_status, action="create")
    db.session.commit()
    audit_log("homepage.quicklink.create", outcome="success", quicklink_id=link.id, status=workflow_status)
    log_kaydet("Anasayfa İçerik", f"Hızlı bağlantı eklendi: {link.title}")
    flash("Hızlı bağlantı eklendi.", "success")
    return redirect(url_for("content.homepage_quicklinks_list"))


@content_bp.route("/admin/homepage/quick-links/<int:link_id>/edit", methods=["POST"])
@login_required
@homepage_editor_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
def homepage_quicklink_edit(link_id):
    link = HomeQuickLink.query.get_or_404(link_id)
    title = guvenli_metin(request.form.get("title") or "").strip()
    if not title:
        flash("Hızlı bağlantı başlığı zorunludur.", "danger")
        return redirect(url_for("content.homepage_quicklinks_list"))

    link_url = guvenli_metin(request.form.get("link_url") or "").strip() or "#"
    if not _validate_link_url(link_url):
        flash("Bağlantı URL değeri güvenlik doğrulamasını geçemedi.", "danger")
        return redirect(url_for("content.homepage_quicklinks_list"))

    fallback_active = _to_bool(request.form.get("is_active"))
    workflow_status = _resolve_status_from_form(WORKFLOW_PUBLISHED if fallback_active else WORKFLOW_DRAFT)

    link.title = title
    link.description = guvenli_metin(request.form.get("description") or "").strip()
    link.link_url = link_url
    link.icon = guvenli_metin(request.form.get("icon") or "").strip()
    link.order_index = _normalize_order_index(request.form.get("order_index"), 0)
    link.is_active = fallback_active
    _set_workflow_status("quicklink", link, workflow_status, action="update")
    db.session.commit()
    audit_log("homepage.quicklink.update", outcome="success", quicklink_id=link.id, status=workflow_status)
    log_kaydet("Anasayfa İçerik", f"Hızlı bağlantı güncellendi: {link.title}")
    flash("Hızlı bağlantı güncellendi.", "success")
    return redirect(url_for("content.homepage_quicklinks_list"))


@content_bp.route("/admin/homepage/quick-links/<int:link_id>/toggle", methods=["POST"])
@login_required
@homepage_editor_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
def homepage_quicklink_toggle(link_id):
    link = HomeQuickLink.query.get_or_404(link_id)
    current_status = _current_workflow_status("quicklink", link)
    next_status = WORKFLOW_PASSIVE if current_status == WORKFLOW_PUBLISHED else WORKFLOW_PUBLISHED
    _set_workflow_status("quicklink", link, next_status, action="toggle")
    db.session.commit()
    audit_log("homepage.quicklink.toggle", outcome="success", quicklink_id=link.id, status=next_status)
    log_kaydet("Anasayfa İçerik", f"Hızlı bağlantı durumu değiştirildi: {link.title} -> {next_status}")
    flash("Bağlantı durumu güncellendi.", "success")
    return redirect(url_for("content.homepage_quicklinks_list"))


@content_bp.route("/admin/homepage/quick-links/<int:link_id>/delete", methods=["POST"])
@login_required
@homepage_editor_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
def homepage_quicklink_delete(link_id):
    link = HomeQuickLink.query.get_or_404(link_id)
    ContentWorkflow.query.filter_by(entity_type="quicklink", entity_id=link.id).delete()
    db.session.delete(link)
    db.session.commit()
    audit_log("homepage.quicklink.delete", outcome="success", quicklink_id=link.id)
    flash("Bağlantı silindi.", "info")
    return redirect(url_for("content.homepage_quicklinks_list"))


def _content_list_endpoint(content_type):
    endpoint_map = {
        "slider": "content.homepage_slider_list",
        "section": "content.homepage_section_list",
        "announcement": "content.homepage_announcements_list",
        "document": "content.homepage_documents_list",
        "stat": "content.homepage_stats_list",
        "quicklink": "content.homepage_quicklinks_list",
    }
    return endpoint_map.get(content_type, "content.homepage_dashboard")


@content_bp.route("/admin/homepage/<string:content_type>/bulk", methods=["POST"])
@login_required
@homepage_editor_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
def homepage_bulk_action(content_type):
    model = CONTENT_TYPE_MAP.get(content_type)
    if not model:
        abort(404)

    action = (request.form.get("bulk_action") or "").strip().lower()
    raw_ids = request.form.getlist("selected_ids")
    selected_ids = [int(item_id) for item_id in raw_ids if str(item_id).isdigit()]

    if not selected_ids:
        flash("Lütfen toplu işlem için en az bir kayıt seçin.", "warning")
        return redirect(url_for(_content_list_endpoint(content_type)))

    rows = model.query.filter(model.id.in_(selected_ids)).all()
    if not rows:
        flash("Seçilen kayıtlar bulunamadı.", "danger")
        return redirect(url_for(_content_list_endpoint(content_type)))

    if action in {"publish", "activate"}:
        status = WORKFLOW_PUBLISHED
        if not _can_publish():
            flash("Yayınlama yetkiniz bulunmuyor. Kayıtlar taslak durumuna alındı.", "warning")
            status = WORKFLOW_DRAFT
        for row in rows:
            _set_workflow_status(content_type, row, status, action="bulk_publish")
        db.session.commit()
        log_kaydet("Anasayfa İçerik", f"Toplu yayın işlemi: {content_type} ({len(rows)} kayıt)")
        audit_log("homepage.bulk.publish", outcome="success", content_type=content_type, count=len(rows), status=status)
        flash(f"{len(rows)} kayıt için yayın durumu güncellendi.", "success")
    elif action in {"passive", "deactivate"}:
        for row in rows:
            _set_workflow_status(content_type, row, WORKFLOW_PASSIVE, action="bulk_passive")
        db.session.commit()
        log_kaydet("Anasayfa İçerik", f"Toplu pasif işlemi: {content_type} ({len(rows)} kayıt)")
        audit_log("homepage.bulk.passive", outcome="success", content_type=content_type, count=len(rows))
        flash(f"{len(rows)} kayıt pasif duruma alındı.", "success")
    elif action == "archive":
        for row in rows:
            _set_workflow_status(content_type, row, WORKFLOW_ARCHIVED, action="bulk_archive")
        db.session.commit()
        log_kaydet("Anasayfa İçerik", f"Toplu arşiv işlemi: {content_type} ({len(rows)} kayıt)")
        audit_log("homepage.bulk.archive", outcome="success", content_type=content_type, count=len(rows))
        flash(f"{len(rows)} kayıt arşiv durumuna alındı.", "success")
    elif action == "normalize":
        _normalize_order(content_type)
        flash("Sıralama normalize edildi.", "success")
    else:
        flash("Geçersiz toplu işlem seçildi.", "danger")

    return redirect(url_for(_content_list_endpoint(content_type)))


@content_bp.route("/admin/homepage/<string:content_type>/<int:item_id>/move/<string:direction>", methods=["POST"])
@login_required
@homepage_editor_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
def homepage_move_item(content_type, item_id, direction):
    model = CONTENT_TYPE_MAP.get(content_type)
    if not model:
        abort(404)
    if direction not in {"up", "down"}:
        abort(400)

    row = model.query.get_or_404(item_id)
    moved = _swap_order_with_neighbor(content_type, row, direction)
    if moved:
        db.session.commit()
        log_kaydet("Anasayfa İçerik", f"Sıralama değişti: {content_type} #{item_id} ({direction})")
        audit_log("homepage.order.move", outcome="success", content_type=content_type, entity_id=item_id, direction=direction)
        flash("Sıralama güncellendi.", "success")
    else:
        flash("Kayıt zaten sınır konumda.", "info")
    return redirect(url_for(_content_list_endpoint(content_type)))


@content_bp.route("/admin/homepage/media")
@login_required
@homepage_editor_required
def media_library():
    query = MediaAsset.query.order_by(MediaAsset.created_at.desc())
    search = (request.args.get("q") or "").strip()
    if search:
        query = query.filter(
            or_(
                MediaAsset.title.ilike(f"%{search}%"),
                MediaAsset.file_path.ilike(f"%{search}%"),
                MediaAsset.alt_text.ilike(f"%{search}%"),
            )
        )
    assets = query.limit(300).all()
    return render_template("admin/media_library.html", assets=assets, search_query=search)


@content_bp.route("/admin/homepage/media/upload", methods=["POST"])
@login_required
@homepage_editor_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
def media_upload():
    upload = request.files.get("media_file")
    title = guvenli_metin(request.form.get("title") or "").strip() or "Yeni Medya"
    alt_text = guvenli_metin(request.form.get("alt_text") or "").strip()

    if not upload or not upload.filename:
        flash("Yükleme için bir dosya seçin.", "danger")
        return redirect(url_for("content.media_library"))

    safe_name = secure_upload_filename(upload.filename)
    if not safe_name:
        flash("Dosya adı geçersiz.", "danger")
        return redirect(url_for("content.media_library"))

    allowed_extensions = current_app.config.get("ALLOWED_UPLOAD_EXTENSIONS", set())
    if not is_allowed_file(safe_name, allowed_extensions):
        flash("Dosya uzantısına izin verilmiyor.", "danger")
        return redirect(url_for("content.media_library"))

    if not is_allowed_mime(safe_name, allowed_mime_prefixes=("image/", "application/pdf"), upload=upload):
        flash("Dosya türü güvenlik doğrulamasını geçemedi.", "danger")
        return redirect(url_for("content.media_library"))
    if not _is_allowed_upload_mimetype(upload):
        flash("Yüklenen dosya MIME türü desteklenmiyor.", "danger")
        return redirect(url_for("content.media_library"))

    final_name = f"{get_tr_now().strftime('%Y%m%d%H%M%S')}_{safe_name}"
    stored = get_storage_adapter().save_upload(upload, folder="cms", filename=final_name)

    extension = final_name.rsplit(".", 1)[1].lower()
    file_type = "image" if extension in {"png", "jpg", "jpeg", "gif", "webp"} else "document"

    asset = MediaAsset(
        title=title,
        file_path=stored.public_url,
        file_type=file_type,
        alt_text=alt_text,
        uploaded_by_id=current_user.id,
        is_active=True,
    )
    db.session.add(asset)
    db.session.commit()

    log_kaydet("Anasayfa İçerik", f"Medya yüklendi: {asset.file_path}")
    audit_log("homepage.media.upload", outcome="success", media_id=asset.id, file_type=file_type)
    flash("Medya dosyası başarıyla yüklendi.", "success")
    return redirect(url_for("content.media_library"))


@content_bp.route("/admin/homepage/media/<int:asset_id>/toggle", methods=["POST"])
@login_required
@homepage_editor_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
def media_toggle(asset_id):
    asset = MediaAsset.query.get_or_404(asset_id)
    asset.is_active = not asset.is_active
    db.session.commit()
    audit_log("homepage.media.toggle", outcome="success", media_id=asset.id, active=asset.is_active)
    flash("Medya durumu güncellendi.", "success")
    return redirect(url_for("content.media_library"))


@content_bp.route("/admin/homepage/preview/<string:content_type>", methods=["POST"])
@login_required
@homepage_editor_required
def content_preview(content_type):
    if content_type not in CONTENT_TYPE_MAP:
        abort(404)

    preview_data = {
        "content_type": content_type,
        "title": guvenli_metin(request.form.get("title") or "").strip(),
        "subtitle": guvenli_metin(request.form.get("subtitle") or "").strip(),
        "description": guvenli_metin(request.form.get("description") or "").strip(),
        "summary": guvenli_metin(request.form.get("summary") or "").strip(),
        "content": guvenli_metin(request.form.get("content") or "").strip(),
        "icon": guvenli_metin(request.form.get("icon") or "").strip(),
        "image_path": guvenli_metin(
            request.form.get("image_path")
            or request.form.get("image_url")
            or request.form.get("cover_image")
            or ""
        ).strip(),
        "button_text": guvenli_metin(request.form.get("button_text") or "").strip(),
        "button_link": guvenli_metin(request.form.get("button_link") or "").strip(),
        "value_text": guvenli_metin(request.form.get("value_text") or "").strip(),
        "link_url": guvenli_metin(request.form.get("link_url") or "").strip(),
        "file_path": guvenli_metin(request.form.get("file_path") or "").strip(),
    }
    audit_log("homepage.preview.create", outcome="success", content_type=content_type)
    log_kaydet("Anasayfa İçerik", f"Önizleme oluşturuldu: {content_type}")
    return render_template("admin/homepage_preview.html", preview=preview_data)
