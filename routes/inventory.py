import io
import base64
import json
import mimetypes
from pathlib import Path
from urllib.parse import unquote, urlparse
from datetime import datetime, timedelta

import pandas as pd
from sqlalchemy.exc import IntegrityError
from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required
from reportlab.rl_config import TTFSearchPath
from xhtml2pdf import pisa

from extensions import (
    audit_log,
    column_exists,
    create_approval_request,
    create_notification,
    create_notification_once,
    db,
    guvenli_metin,
    is_allowed_file,
    is_allowed_mime,
    limiter,
    log_kaydet,
    secure_upload_filename,
)
from models import (
    ApprovalRequest,
    AssignmentHistoryEntry,
    AssignmentItem,
    AssignmentRecipient,
    AssignmentRecord,
    AssetOperationalState,
    AssetMeterReading,
    BakimKaydi,
    CalibrationRecord,
    CalibrationSchedule,
    ConsumableItem,
    ConsumableStockMovement,
    EquipmentTemplate,
    Havalimani,
    InventoryAsset,
    IslemLog,
    Kutu,
    Kullanici,
    MaintenanceFormTemplate,
    MaintenanceHistory,
    MaintenanceInstruction,
    MaintenancePlan,
    Malzeme,
    MaintenanceTriggerRule,
    PPERecord,
    PPERecordEvent,
    SparePartStock,
    TatbikatBelgesi,
    TR_TZ,
    Notification,
    WorkOrder,
    get_tr_now,
)
from extensions import table_exists
from qr_logic import generate_qr_data
from decorators import (
    CANONICAL_ROLE_ADMIN,
    CANONICAL_ROLE_SYSTEM,
    CANONICAL_ROLE_TEAM_LEAD,
    get_effective_role,
    has_permission,
    permission_required,
)
from google_drive_service import GoogleDriveError, get_drill_drive_service
from reporting import build_dashboard_kpis
from storage import get_storage_adapter
from demo_data import apply_platform_demo_scope


inventory_bp = Blueprint("inventory", __name__)

ASSIGNMENT_STATUS_LABELS = {
    "active": "Aktif",
    "returned": "İade Edildi",
    "partial": "Kısmi İade",
    "cancelled": "İptal",
}
PPE_STATUS_LABELS = {
    "aktif": "Aktif",
    "eksik": "Eksik",
    "hasarli": "Hasarlı",
    "kayip": "Kayıp",
    "kullanim_disi": "Kullanım Dışı",
    "degisim_talebi": "Değişim Talebi",
}
SIGNED_ASSIGNMENT_ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "webp"}
PPE_ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "webp"}
DRILL_ALLOWED_EXTENSIONS = {"rar", "zip", "7z"}
DRILL_ALLOWED_MIME_TYPES = (
    "application/zip",
    "application/x-zip-compressed",
    "application/x-7z-compressed",
    "application/x-rar-compressed",
    "application/vnd.rar",
    "application/octet-stream",
)


def havalimani_filtreli_sorgu(model_sinifi):
    if _can_view_all_operational_scope():
        query = model_sinifi.query.filter_by(is_deleted=False)
    else:
        query = model_sinifi.query.filter_by(havalimani_id=current_user.havalimani_id, is_deleted=False)
    if hasattr(model_sinifi, "id"):
        query = apply_platform_demo_scope(query, model_sinifi.__name__, model_sinifi.id)
    return query


def _can_view_all_operational_scope():
    return has_permission("logs.view") or has_permission("settings.manage")


def _visible_operational_airports():
    if _can_view_all_operational_scope():
        query = Havalimani.query.filter_by(is_deleted=False)
    else:
        query = Havalimani.query.filter_by(
            is_deleted=False,
            id=current_user.havalimani_id,
        )
    query = apply_platform_demo_scope(query, "Havalimani", Havalimani.id)
    return query.order_by(Havalimani.kodu.asc()).all()


def _visible_personnel_query(airport_id=None):
    query = Kullanici.query.filter_by(is_deleted=False)
    if _can_view_all_operational_scope():
        if airport_id == "global":
            scoped = query.filter(Kullanici.havalimani_id.is_(None))
            return apply_platform_demo_scope(scoped, "Kullanici", Kullanici.id)
        if airport_id:
            scoped = query.filter(Kullanici.havalimani_id == airport_id)
            return apply_platform_demo_scope(scoped, "Kullanici", Kullanici.id)
        return apply_platform_demo_scope(query, "Kullanici", Kullanici.id)
    if current_user.havalimani_id is None:
        scoped = query.filter(Kullanici.havalimani_id.is_(None))
        return apply_platform_demo_scope(scoped, "Kullanici", Kullanici.id)
    scoped = query.filter(Kullanici.havalimani_id == current_user.havalimani_id)
    return apply_platform_demo_scope(scoped, "Kullanici", Kullanici.id)


def _visible_material_query(airport_id=None):
    query = Malzeme.query.filter_by(is_deleted=False)
    if _can_view_all_operational_scope():
        if airport_id:
            scoped = query.filter(Malzeme.havalimani_id == airport_id)
            return apply_platform_demo_scope(scoped, "Malzeme", Malzeme.id)
        return apply_platform_demo_scope(query, "Malzeme", Malzeme.id)
    scoped = query.filter(Malzeme.havalimani_id == current_user.havalimani_id)
    return apply_platform_demo_scope(scoped, "Malzeme", Malzeme.id)


def _can_issue_assignments(actor=None):
    actor = actor or current_user
    return bool(
        getattr(actor, "is_authenticated", False)
        and get_effective_role(actor) in {CANONICAL_ROLE_SYSTEM, CANONICAL_ROLE_TEAM_LEAD}
    )


def _assignment_scope():
    query = AssignmentRecord.query.filter_by(is_deleted=False)
    if _can_view_all_operational_scope():
        return query
    if has_permission("assignment.manage") or has_permission("assignment.create"):
        return query.filter(AssignmentRecord.airport_id == current_user.havalimani_id)
    return query.join(AssignmentRecipient).filter(AssignmentRecipient.user_id == current_user.id).distinct()


def _ppe_scope():
    query = PPERecord.query.filter_by(is_deleted=False)
    if _can_view_all_operational_scope():
        return query
    if has_permission("ppe.manage"):
        return query.filter(PPERecord.airport_id == current_user.havalimani_id)
    return query.filter(PPERecord.user_id == current_user.id)


def _drill_scope():
    query = TatbikatBelgesi.query.filter_by(is_deleted=False)
    if get_effective_role(current_user) in {CANONICAL_ROLE_SYSTEM, CANONICAL_ROLE_ADMIN}:
        return apply_platform_demo_scope(query, "TatbikatBelgesi", TatbikatBelgesi.id)
    if current_user.havalimani_id is None:
        scoped = query.filter(TatbikatBelgesi.havalimani_id.is_(None))
        return apply_platform_demo_scope(scoped, "TatbikatBelgesi", TatbikatBelgesi.id)
    scoped = query.filter(TatbikatBelgesi.havalimani_id == current_user.havalimani_id)
    return apply_platform_demo_scope(scoped, "TatbikatBelgesi", TatbikatBelgesi.id)


def _can_view_drills_for_airport(airport_id):
    if get_effective_role(current_user) in {CANONICAL_ROLE_SYSTEM, CANONICAL_ROLE_ADMIN}:
        return True
    return bool(current_user.havalimani_id and current_user.havalimani_id == airport_id)


def _can_manage_drills_for_airport(airport_id):
    if get_effective_role(current_user) == CANONICAL_ROLE_SYSTEM:
        return True
    return bool(
        get_effective_role(current_user) == CANONICAL_ROLE_TEAM_LEAD
        and current_user.havalimani_id
        and current_user.havalimani_id == airport_id
    )


def _visible_drill_airports():
    if get_effective_role(current_user) in {CANONICAL_ROLE_SYSTEM, CANONICAL_ROLE_ADMIN}:
        query = Havalimani.query.filter_by(is_deleted=False)
        query = apply_platform_demo_scope(query, "Havalimani", Havalimani.id)
        return query.order_by(Havalimani.kodu.asc()).all()
    if current_user.havalimani_id is None:
        return []
    query = Havalimani.query.filter_by(
        is_deleted=False,
        id=current_user.havalimani_id,
    )
    query = apply_platform_demo_scope(query, "Havalimani", Havalimani.id)
    return query.order_by(Havalimani.kodu.asc()).all()


def _drill_file_size(upload):
    stream = getattr(upload, "stream", None)
    if stream is None:
        return int(getattr(upload, "content_length", 0) or 0)
    try:
        position = stream.tell()
    except Exception:
        position = 0
    try:
        stream.seek(0, io.SEEK_END)
        size = stream.tell()
    except Exception:
        size = int(getattr(upload, "content_length", 0) or 0)
    finally:
        try:
            stream.seek(position)
        except Exception:
            pass
    return int(size or 0)


def _validate_drill_upload(upload):
    if not upload or not upload.filename:
        return None, None, "Yüklenecek dosya seçilmedi."
    safe_name = secure_upload_filename(upload.filename)
    if not safe_name:
        return None, None, "Dosya adı güvenli hale getirilemedi."
    if not is_allowed_file(safe_name, DRILL_ALLOWED_EXTENSIONS):
        return None, None, "Sadece RAR, ZIP veya 7Z arşiv dosyası yükleyebilirsiniz."

    file_size = _drill_file_size(upload)
    if file_size <= 0:
        return None, None, "Boş dosya yüklenemez."
    max_bytes = int(current_app.config.get("DRILL_MAX_FILE_SIZE") or current_app.config.get("MAX_CONTENT_LENGTH") or 0)
    if max_bytes and file_size > max_bytes:
        max_mb = max(1, int(max_bytes / (1024 * 1024)))
        return None, None, f"Tatbikat dosyası en fazla {max_mb} MB olabilir."

    mime_type = getattr(upload, "mimetype", None) or mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
    if not any(mime_type.startswith(prefix) for prefix in DRILL_ALLOWED_MIME_TYPES):
        return None, None, "Arşiv dosyası türü doğrulanamadı. RAR, ZIP veya 7Z yükleyin."
    return safe_name, mime_type, None


def _build_drill_storage_filename(drill_date, safe_name):
    extension = Path(safe_name).suffix.lower()
    candidate = secure_upload_filename(f"{drill_date.strftime('%d.%m.%Y')}_tatbikat{extension}")
    if not candidate or not is_allowed_file(candidate, DRILL_ALLOWED_EXTENSIONS):
        raise ValueError("Tatbikat dosya adı güvenli biçimde oluşturulamadı.")
    return candidate


def _format_drill_file_size(size):
    amount = float(size or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if amount < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(amount)} {unit}"
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return "0 B"


def _get_drill_document_or_403(document_id):
    document = TatbikatBelgesi.query.filter_by(id=document_id, is_deleted=False).first_or_404()
    if not _can_view_drills_for_airport(document.havalimani_id):
        abort(403)
    return document


def _redirect_after_google_oauth():
    if current_user.is_authenticated:
        if getattr(current_user, "is_sahip", False) or has_permission("settings.manage"):
            return redirect(url_for("admin.site_yonetimi", tab="genel"))
        if has_permission("drill.view"):
            return redirect(url_for("inventory.tatbikat_listesi"))
    return redirect(url_for("auth.login"))


def _next_assignment_no():
    now = get_tr_now()
    return f"ZMT-{now.strftime('%Y%m%d%H%M%S')}-{now.microsecond % 1000:03d}"


def _parse_int_list(values):
    rows = []
    for value in values or []:
        try:
            rows.append(int(value))
        except (TypeError, ValueError):
            continue
    return rows


def _append_assignment_history(assignment, event_type, note):
    db.session.add(
        AssignmentHistoryEntry(
            assignment_id=assignment.id,
            event_type=event_type,
            event_note=note,
            created_by_id=current_user.id if current_user.is_authenticated else None,
        )
    )


def _recalculate_assignment_status(assignment):
    if assignment.status == "cancelled":
        return assignment.status
    items = [item for item in assignment.items if not item.is_deleted]
    if not items:
        assignment.status = "cancelled"
        return assignment.status
    if all((item.remaining_quantity or 0) <= 0 for item in items):
        assignment.status = "returned"
    elif any(float(item.returned_quantity or 0) > 0 for item in items):
        assignment.status = "partial"
    else:
        assignment.status = "active"
    return assignment.status


def _assignment_status_label(value):
    return ASSIGNMENT_STATUS_LABELS.get(value, value)


def _ppe_status_label(value):
    return PPE_STATUS_LABELS.get(value, value)


def _validate_upload(upload, allowed_extensions, allowed_mime_prefixes):
    if not upload or not upload.filename:
        return None, "Yüklenecek dosya seçilmedi."
    safe_name = secure_upload_filename(upload.filename)
    if not safe_name:
        return None, "Dosya adı güvenli hale getirilemedi."
    if not is_allowed_file(safe_name, allowed_extensions):
        return None, "Dosya uzantısı desteklenmiyor."
    if not is_allowed_mime(safe_name, allowed_mime_prefixes=allowed_mime_prefixes, upload=upload):
        return None, "Dosya türü desteklenmiyor."
    return safe_name, None


def _pdf_link_callback(uri, _rel):
    if not uri:
        return uri
    if uri.startswith("file://"):
        return unquote(urlparse(uri).path)
    if uri.startswith("/"):
        return uri
    return uri


def _assignment_pdf_font_uris():
    search_roots = []
    for candidate in list(TTFSearchPath) + [
        "/usr/share/fonts",
        "/usr/local/share/fonts",
        "/usr/share/fonts/truetype",
        "/usr/share/fonts/truetype/dejavu",
        "/usr/share/fonts/truetype/liberation2",
        "/Library/Fonts",
        "/System/Library/Fonts",
        "/System/Library/Fonts/Supplemental",
        str(Path.home() / "Library/Fonts"),
    ]:
        path = Path(candidate)
        if path.exists() and path not in search_roots:
            search_roots.append(path)

    font_candidates = [
        ("Vera.ttf", "VeraBd.ttf"),
        ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"),
        ("Arial Unicode.ttf", "Arial Unicode.ttf"),
        ("Arial.ttf", "Arial Bold.ttf"),
    ]

    def _find_font(filename):
        for root in search_roots:
            direct = root / filename
            if direct.exists():
                return direct
            nested = list(root.rglob(filename))
            if nested:
                return nested[0]
        return None

    for regular_name, bold_name in font_candidates:
        regular = _find_font(regular_name)
        if not regular:
            continue
        bold = _find_font(bold_name) or regular
        return {
            "regular": regular.resolve().as_uri(),
            "bold": bold.resolve().as_uri(),
        }

    return {"regular": "", "bold": ""}


def _asset_scope():
    query = InventoryAsset.query.filter_by(is_deleted=False)
    if has_permission("logs.view") or has_permission("settings.manage"):
        scoped = query
    else:
        scoped = query.filter_by(havalimani_id=current_user.havalimani_id)
    return apply_platform_demo_scope(scoped, "InventoryAsset", InventoryAsset.id)


def _asset_qr_url(asset):
    return url_for("inventory.quick_asset_view", asset_id=asset.id, _external=True)


def _asset_qr_payload(asset):
    return asset.qr_code or _asset_qr_url(asset)


def _asset_qr_context(asset):
    return {
        "qr_payload": _asset_qr_payload(asset),
        "asset_code": asset.asset_code,
        "airport_name": asset.qr_label_airport_name,
    }


def _box_scope():
    query = Kutu.query.filter_by(is_deleted=False)
    if _can_view_all_box_scope():
        scoped = query
    else:
        scoped = query.filter_by(havalimani_id=current_user.havalimani_id)
    return apply_platform_demo_scope(scoped, "Kutu", Kutu.id)


def _can_view_all_box_scope():
    return get_effective_role(current_user) == CANONICAL_ROLE_SYSTEM


def _can_manage_box_airport(airport_id):
    actor_role = get_effective_role(current_user)
    if actor_role == CANONICAL_ROLE_SYSTEM:
        return True
    return bool(
        actor_role == CANONICAL_ROLE_TEAM_LEAD
        and current_user.havalimani_id
        and current_user.havalimani_id == airport_id
    )


def _validate_box_write_access(airport_id):
    if not _can_manage_box_airport(airport_id):
        abort(403)


def _extract_box_sequence(code, airport_code):
    if not code:
        return None
    normalized = str(code).strip().upper()
    prefix = f"{airport_code}-SAR-"
    if not normalized.startswith(prefix):
        return None
    serial_part = normalized[len(prefix):]
    if not serial_part.isdigit():
        return None
    return int(serial_part)


def _next_box_code_for_airport(airport):
    airport_code = (airport.kodu or "").strip().upper()
    if not airport_code:
        raise ValueError("Havalimanı kodu bulunamadı.")
    existing_codes = [
        row[0]
        for row in db.session.query(Kutu.kodu)
        .filter(
            Kutu.havalimani_id == airport.id,
        )
        .all()
    ]
    sequences = [seq for seq in (_extract_box_sequence(code, airport_code) for code in existing_codes) if seq is not None]
    next_serial = (max(sequences) + 1) if sequences else 1
    return f"{airport_code}-SAR-{next_serial:02d}"


def _create_box_with_generated_code(airport_id, marka=None):
    airport = db.session.get(Havalimani, airport_id)
    if not airport or airport.is_deleted:
        raise ValueError("Geçerli bir havalimanı bulunamadı.")

    normalized_brand = guvenli_metin(marka or "").strip() or None

    for _ in range(8):
        generated_code = _next_box_code_for_airport(airport)
        kutu = Kutu(
            kodu=generated_code,
            marka=normalized_brand,
            konum=generated_code,
            havalimani_id=airport.id,
        )
        db.session.add(kutu)
        try:
            db.session.flush()
            return kutu
        except IntegrityError:
            db.session.rollback()
    raise ValueError("Kutu kodu üretilemedi. Lütfen tekrar deneyin.")


def _box_qr_context(box):
    return {
        "qr_payload": box.qr_payload,
        "box_code": box.qr_code_label,
        "airport_name": box.qr_label_airport_name,
    }


def _sync_asset_location(material):
    if not material or not material.linked_asset:
        return
    material.linked_asset.depot_location = material.kutu.kodu if material.kutu else material.linked_asset.depot_location
    material.linked_asset.havalimani_id = material.havalimani_id
    material.linked_asset.unit_count = material.stok_miktari or material.linked_asset.unit_count


def _ensure_operational_state(asset):
    if asset.operational_state:
        return asset.operational_state
    state = AssetOperationalState(asset_id=asset.id, lifecycle_status="active")
    db.session.add(state)
    db.session.flush()
    return state


def _consumable_scope():
    query = ConsumableItem.query.filter_by(is_deleted=False, is_active=True)
    query = apply_platform_demo_scope(query, "ConsumableItem", ConsumableItem.id)
    return query.order_by(ConsumableItem.title.asc())


def _consumable_balance(consumable_id, airport_id):
    movements = ConsumableStockMovement.query.filter_by(
        consumable_id=consumable_id,
        airport_id=airport_id,
        is_deleted=False,
    ).all()
    balance = 0.0
    for movement in movements:
        sign = 1 if movement.movement_type in {"in", "adjust", "transfer"} else -1
        balance += sign * float(movement.quantity or 0)
    return round(balance, 2)


def _lifecycle_to_status(lifecycle_status):
    mapping = {
        "planned": "pasif",
        "received": "pasif",
        "active": "aktif",
        "in_maintenance": "bakimda",
        "calibration_due": "bakimda",
        "out_of_service": "pasif",
        "decommissioned": "pasif",
        "disposed": "hurda",
        "transferred": "aktif",
    }
    return mapping.get(lifecycle_status, "aktif")


def _create_operational_alerts():
    today = get_tr_now().date()
    asset_rows = _asset_scope().all()
    if table_exists("consumable_item") and table_exists("consumable_stock_movement"):
        for consumable in _consumable_scope().all():
            balance = _consumable_balance(consumable.id, current_user.havalimani_id) if current_user.havalimani_id else 0
            if current_user.havalimani_id and balance <= float(consumable.critical_level or 0):
                create_notification_once(
                    current_user.id,
                    "consumable_critical_stock",
                    "Kritik sarf stoğu",
                    f"{consumable.title} kritik stok seviyesine indi.",
                    link_url=url_for("inventory.consumables"),
                    severity="danger",
                )
            elif current_user.havalimani_id and balance <= float(consumable.min_stock_level or 0):
                create_notification_once(
                    current_user.id,
                    "consumable_low_stock",
                    "Düşük sarf stoğu",
                    f"{consumable.title} minimum stok seviyesine yaklaştı.",
                    link_url=url_for("inventory.consumables"),
                    severity="warning",
                )

    for asset in asset_rows:
        if asset.next_calibration_date and asset.next_calibration_date < today:
            create_notification_once(
                current_user.id,
                "calibration_overdue",
                "Geciken kalibrasyon",
                f"{asset.asset_code} için kalibrasyon gecikti.",
                link_url=url_for("inventory.calibration_records"),
                severity="warning",
            )
        elif asset.next_calibration_date and asset.next_calibration_date <= (today + timedelta(days=15)):
            create_notification_once(
                current_user.id,
                "calibration_upcoming",
                "Yaklaşan kalibrasyon",
                f"{asset.asset_code} için kalibrasyon tarihi yaklaşıyor.",
                link_url=url_for("inventory.calibration_records"),
                severity="info",
            )
        if asset.warranty_end_date and today <= asset.warranty_end_date <= (today + timedelta(days=30)):
            create_notification_once(
                current_user.id,
                "warranty_expiring",
                "Garanti bitişi yaklaşıyor",
                f"{asset.asset_code} için garanti bitiş tarihi yaklaşıyor.",
                link_url=url_for("inventory.asset_lifecycle"),
                severity="warning",
            )
        if asset.is_critical and asset.lifecycle_status == "out_of_service":
            create_notification_once(
                current_user.id,
                "critical_out_of_service",
                "Kritik ekipman servis dışı",
                f"{asset.asset_code} kritik ekipman servis dışı durumunda.",
                link_url=url_for("inventory.asset_lifecycle"),
                severity="danger",
            )


def _parse_date(raw_value):
    if not raw_value:
        return None
    normalized = str(raw_value).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(normalized, fmt).date()
        except (TypeError, ValueError):
            continue
    return None


def _parse_positive_int(raw_value, default=1):
    try:
        value = int(str(raw_value).strip())
    except (TypeError, ValueError, AttributeError):
        return default
    return max(value, 1)


def _normalize_status(status_value):
    mapping = {
        "Aktif": "aktif",
        "Bakımda": "bakimda",
        "Arızalı": "arizali",
        "Hurda": "hurda",
        "Pasif": "pasif",
        "aktif": "aktif",
        "bakimda": "bakimda",
        "arizali": "arizali",
        "hurda": "hurda",
        "pasif": "pasif",
    }
    return mapping.get(status_value, "aktif")


def _display_status(status_value):
    mapping = {
        "aktif": "Aktif",
        "bakimda": "Bakımda",
        "arizali": "Arızalı",
        "hurda": "Hurda",
        "pasif": "Pasif",
    }
    return mapping.get(status_value, "Aktif")


def _ensure_box(kutu_kodu, havalimani_id, marka=None):
    kutu = Kutu.query.filter_by(kodu=kutu_kodu, havalimani_id=havalimani_id, is_deleted=False).first()
    if kutu:
        if marka:
            kutu.marka = guvenli_metin(marka).strip()
        return kutu
    kutu = Kutu(
        kodu=kutu_kodu,
        marka=guvenli_metin(marka or "").strip() or None,
        havalimani_id=havalimani_id,
        konum=kutu_kodu,
    )
    db.session.add(kutu)
    db.session.flush()
    return kutu


def _ensure_template_from_form(form_data, selected_template_id):
    if selected_template_id:
        template = db.session.get(EquipmentTemplate, selected_template_id)
        if template and not template.is_deleted and template.is_active:
            return template
        return None

    template_name = guvenli_metin(form_data.get("ad") or "").strip()
    if not template_name:
        return None

    template = EquipmentTemplate(
        name=template_name,
        category=guvenli_metin(form_data.get("kategori") or "").strip(),
        brand=guvenli_metin(form_data.get("marka") or "").strip(),
        model_code=guvenli_metin(form_data.get("model") or "").strip(),
        description=guvenli_metin(form_data.get("aciklama") or "").strip(),
        technical_specs=guvenli_metin(form_data.get("teknik") or "").strip(),
        manufacturer=guvenli_metin(form_data.get("uretici") or "").strip(),
        maintenance_period_days=form_data.get("bakim_periyodu_gun", type=int) or 180,
        criticality_level=(form_data.get("kritik_seviye") or "normal").strip(),
        default_maintenance_form_id=form_data.get("bakim_formu_id", type=int) or None,
        is_active=True,
    )
    db.session.add(template)
    db.session.flush()
    return template


def _create_asset_and_legacy_material(template, kutu, havalimani_id, form_data):
    status_display = form_data.get("durum", "Aktif")
    status_internal = _normalize_status(status_display)

    legacy_material = Malzeme(
        ad=guvenli_metin(form_data.get("ad") or template.name),
        seri_no=guvenli_metin(form_data.get("seri_no") or ""),
        teknik_ozellikler=guvenli_metin(form_data.get("teknik") or template.technical_specs),
        stok_miktari=form_data.get("stok", type=int) or 1,
        durum=status_display,
        kritik_mi=True if form_data.get("kritik") == "on" else False,
        son_bakim_tarihi=_parse_date(form_data.get("bakim")),
        gelecek_bakim_tarihi=_parse_date(form_data.get("gelecek_bakim")),
        kutu_id=kutu.id,
        havalimani_id=havalimani_id,
    )
    db.session.add(legacy_material)
    db.session.flush()

    parent_asset_id = form_data.get("parent_asset_id", type=int)
    parent_asset = None
    if parent_asset_id:
        parent_asset = InventoryAsset.query.filter_by(
            id=parent_asset_id,
            havalimani_id=havalimani_id,
            is_deleted=False,
        ).first()

    asset = InventoryAsset(
        equipment_template_id=template.id,
        havalimani_id=havalimani_id,
        legacy_material_id=legacy_material.id,
        parent_asset_id=parent_asset.id if parent_asset else None,
        serial_no=guvenli_metin(form_data.get("seri_no") or ""),
        qr_code="",
        asset_tag=guvenli_metin(form_data.get("demirbas_no") or ""),
        unit_count=form_data.get("stok", type=int) or 1,
        depot_location=guvenli_metin(form_data.get("depo_konumu") or kutu.kodu),
        status=status_internal,
        maintenance_state=(form_data.get("bakim_durumu") or "normal").strip(),
        last_maintenance_date=_parse_date(form_data.get("bakim")),
        next_maintenance_date=_parse_date(form_data.get("gelecek_bakim")),
        acquired_date=_parse_date(form_data.get("edinim_tarihi")),
        warranty_end_date=_parse_date(form_data.get("garanti_bitis_tarihi")),
        notes=guvenli_metin(form_data.get("notlar") or ""),
        maintenance_period_days=form_data.get("bakim_periyodu_gun", type=int) or template.maintenance_period_days,
        is_critical=True if form_data.get("kritik") == "on" else False,
    )
    db.session.add(asset)
    db.session.flush()
    asset.qr_code = _asset_qr_url(asset)

    period_days = asset.maintenance_period_days or template.maintenance_period_days
    if period_days:
        plan = MaintenancePlan(
            name=f"{template.name} Periyodik Bakım Planı",
            equipment_template_id=template.id,
            asset_id=asset.id,
            owner_airport_id=havalimani_id,
            period_days=period_days,
            start_date=get_tr_now().date(),
            last_maintenance_date=asset.last_maintenance_date,
            is_active=True,
        )
        plan.recalculate_next_due_date(asset.last_maintenance_date or get_tr_now().date())
        asset.next_maintenance_date = asset.next_maintenance_date or plan.next_due_date
        legacy_material.gelecek_bakim_tarihi = legacy_material.gelecek_bakim_tarihi or asset.next_maintenance_date
        db.session.add(plan)

    return asset, legacy_material


@inventory_bp.route("/dashboard")
@login_required
@permission_required("dashboard.view")
def dashboard():
    if _can_view_all_operational_scope():
        h_ad = "Genel Müdürlük / Tüm Birimler"
    else:
        h_ad = current_user.havalimani.ad

    bugun = datetime.now(TR_TZ).date()
    on_bes_gun_sonra = bugun + timedelta(days=15)
    trend_days = request.args.get("trend_days", type=int) or 30
    if trend_days not in {7, 30, 90}:
        trend_days = 30

    bakim_sorgu = havalimani_filtreli_sorgu(Malzeme).filter(
        Malzeme.gelecek_bakim_tarihi <= on_bes_gun_sonra,
        Malzeme.durum != "Hurda",
    )
    ariza_sorgu = havalimani_filtreli_sorgu(Malzeme).filter_by(durum="Arızalı")

    asset_query = _asset_scope()
    due_today_count = asset_query.filter(
        InventoryAsset.next_maintenance_date.isnot(None),
        InventoryAsset.next_maintenance_date >= bugun,
        InventoryAsset.next_maintenance_date <= on_bes_gun_sonra,
    ).count()
    overdue_count = asset_query.filter(
        InventoryAsset.next_maintenance_date.isnot(None),
        InventoryAsset.next_maintenance_date < bugun,
        InventoryAsset.status != "pasif",
    ).count()
    critical_fault_count = asset_query.filter(
        InventoryAsset.is_critical.is_(True),
        InventoryAsset.status.in_(["arizali", "bakimda"]),
    ).count()

    open_work_order_query = WorkOrder.query.filter_by(is_deleted=False).join(InventoryAsset).filter(
        InventoryAsset.is_deleted.is_(False),
        WorkOrder.status.in_(["acik", "atandi", "islemde"]),
    )
    if not _can_view_all_operational_scope():
        open_work_order_query = open_work_order_query.filter(
            InventoryAsset.havalimani_id == current_user.havalimani_id
        )
    open_work_order_count = open_work_order_query.count()

    low_stock_query = SparePartStock.query.filter_by(is_deleted=False, is_active=True)
    if not _can_view_all_operational_scope():
        low_stock_query = low_stock_query.filter(SparePartStock.airport_id == current_user.havalimani_id)
    low_stock_items = low_stock_query.all()
    low_stock_count = sum(
        1
        for stock in low_stock_items
        if stock.available_quantity
        <= float(stock.reorder_point if stock.reorder_point is not None else (stock.spare_part.min_stock_level if stock.spare_part else 0))
    )

    meter_rule_query = MaintenanceTriggerRule.query.filter_by(is_deleted=False, is_active=True).join(
        InventoryAsset, MaintenanceTriggerRule.asset_id == InventoryAsset.id, isouter=True
    )
    if not _can_view_all_operational_scope():
        meter_rule_query = meter_rule_query.filter(
            (MaintenanceTriggerRule.asset_id.is_(None))
            | (InventoryAsset.havalimani_id == current_user.havalimani_id)
        )
    meter_rules = meter_rule_query.all()
    meter_warning_count = 0
    for rule in meter_rules:
        if not rule.meter_definition_id:
            continue
        asset = rule.asset_owner
        if not asset:
            continue
        last_reading = AssetMeterReading.query.filter_by(
            is_deleted=False,
            asset_id=asset.id,
            meter_definition_id=rule.meter_definition_id,
        ).order_by(AssetMeterReading.reading_at.desc()).first()
        if not last_reading:
            continue
        warning_threshold = float(rule.threshold_value or 0) - float(rule.warning_lead_value or 0)
        if last_reading.reading_value >= max(warning_threshold, 0):
            meter_warning_count += 1

    auto_work_order_query = WorkOrder.query.filter_by(is_deleted=False, source_type="meter_trigger").join(InventoryAsset)
    auto_work_order_query = auto_work_order_query.filter(
        InventoryAsset.is_deleted.is_(False),
        WorkOrder.status.in_(["acik", "atandi", "islemde", "beklemede_parca", "beklemede_onay"]),
    )
    if not _can_view_all_operational_scope():
        auto_work_order_query = auto_work_order_query.filter(InventoryAsset.havalimani_id == current_user.havalimani_id)
    auto_work_order_count = auto_work_order_query.count()

    child_fault_query = _asset_scope().filter(
        InventoryAsset.parent_asset_id.isnot(None),
        InventoryAsset.status.in_(["arizali", "bakimda"]),
    )
    child_fault_count = child_fault_query.count()

    calibration_overdue_count = _asset_scope().filter(
        InventoryAsset.next_calibration_date.isnot(None),
        InventoryAsset.next_calibration_date < bugun,
        InventoryAsset.status != "pasif",
    ).count()
    calibration_upcoming_count = _asset_scope().filter(
        InventoryAsset.next_calibration_date.isnot(None),
        InventoryAsset.next_calibration_date >= bugun,
        InventoryAsset.next_calibration_date <= on_bes_gun_sonra,
    ).count()
    warranty_expiring_count = _asset_scope().filter(
        InventoryAsset.warranty_end_date.isnot(None),
        InventoryAsset.warranty_end_date >= bugun,
        InventoryAsset.warranty_end_date <= (bugun + timedelta(days=30)),
    ).count()
    out_of_service_critical_count = sum(1 for asset in _asset_scope().all() if asset.is_critical and asset.lifecycle_status == "out_of_service")
    low_consumable_count = 0
    critical_consumable_count = 0
    if table_exists("consumable_item") and table_exists("consumable_stock_movement") and current_user.havalimani_id:
        for consumable in _consumable_scope().all():
            balance = _consumable_balance(consumable.id, current_user.havalimani_id)
            if balance <= float(consumable.critical_level or 0):
                critical_consumable_count += 1
            if balance <= float(consumable.min_stock_level or 0):
                low_consumable_count += 1
    total_asset_count = asset_query.count()

    urgent_actions = []
    for material in ariza_sorgu.order_by(Malzeme.updated_at.desc()).limit(3).all():
        urgent_actions.append(
            {
                "name": material.ad,
                "meta": f"Kutu: {material.kutu.kodu if material.kutu else '-'} · Durum: {material.durum}",
                "tag": "ARIZA",
                "tag_class": "tag-red",
                "url": url_for("inventory.kutu_detay", kodu=material.kutu.kodu) if material.kutu else url_for("inventory.envanter"),
            }
        )
    for material in bakim_sorgu.order_by(Malzeme.gelecek_bakim_tarihi.asc()).limit(4).all():
        if len(urgent_actions) >= 5:
            break
        urgent_actions.append(
            {
                "name": material.ad,
                "meta": f"Kutu: {material.kutu.kodu if material.kutu else '-'} · Tarih: {material.gelecek_bakim_tarihi.strftime('%d.%m.%Y') if material.gelecek_bakim_tarihi else '-'}",
                "tag": "BAKIM",
                "tag_class": "tag-amber",
                "url": url_for("inventory.kutu_detay", kodu=material.kutu.kodu) if material.kutu else url_for("inventory.envanter"),
            }
        )

    pending_approval_count = 0
    unread_notification_count = 0
    critical_role_change_count = 0
    qr_regen_pending_count = 0
    critical_audit_24h_count = 0
    if table_exists("approval_request"):
        pending_approval_count = ApprovalRequest.query.filter_by(status="pending").count()
        critical_role_change_count = ApprovalRequest.query.filter_by(status="pending", approval_type="role_change").count()
        qr_regen_pending_count = ApprovalRequest.query.filter_by(status="pending", approval_type="qr_regenerate").count()
    if table_exists("notification"):
        unread_notification_count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
    if table_exists("islem_log") and column_exists("islem_log", "event_key") and column_exists("islem_log", "outcome"):
        last_day = get_tr_now().replace(tzinfo=None) - timedelta(hours=24)
        critical_audit_24h_count = IslemLog.query.filter(
            IslemLog.zaman >= last_day,
            IslemLog.outcome.in_(["failed", "success"]),
            IslemLog.event_key.in_([
                "role.assignment.change",
                "role.assignment.pending",
                "permission.matrix.update",
                "inventory.qr.regenerate",
                "inventory.asset_code.change_attempt",
            ]),
        ).count()

    return render_template(
        "dashboard.html",
        havalimani_ad=h_ad,
        bakim_uyarilari=bakim_sorgu.all(),
        arizali_malzemeler=ariza_sorgu.all(),
        toplam_ekipman_sayi=total_asset_count,
        bugun=bugun,
        bugun_bakim_yaklasan_sayi=due_today_count,
        geciken_bakim_sayi=overdue_count,
        acik_is_emri_sayi=open_work_order_count,
        kritik_arizali_sayi=critical_fault_count,
        dusuk_stok_parca_sayi=low_stock_count,
        sayac_yaklasan_bakim_sayi=meter_warning_count,
        otomatik_is_emri_sayi=auto_work_order_count,
        child_asset_ariza_sayi=child_fault_count,
        kalibrasyon_gecikme_sayi=calibration_overdue_count,
        yaklasan_kalibrasyon_sayi=calibration_upcoming_count,
        garanti_yaklasan_sayi=warranty_expiring_count,
        dusuk_sarf_sayi=low_consumable_count,
        kritik_sarf_sayi=critical_consumable_count,
        kritik_servis_disi_sayi=out_of_service_critical_count,
        approval_bekleyen_sayi=pending_approval_count,
        okunmamis_bildirim_sayi=unread_notification_count,
        kritik_rol_degisim_sayi=critical_role_change_count,
        qr_yenileme_talep_sayi=qr_regen_pending_count,
        kritik_audit_24h_sayi=critical_audit_24h_count,
        acil_aksiyonlar=urgent_actions,
        dashboard_trends=build_dashboard_kpis(current_user, {"trend_days": trend_days, "demo_scope": "all"})["kpis"],
        trend_days=trend_days,
    )


@inventory_bp.route("/dashboard/alerts/sync", methods=["POST"])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
@permission_required("dashboard.view")
def dashboard_alert_sync():
    _create_operational_alerts()
    return ("", 204)


@inventory_bp.route("/envanter")
@login_required
@permission_required("inventory.view")
def envanter():
    selected_airport = request.args.get("havalimani_id", type=int)
    selected_category = request.args.get("kategori", "").strip()
    selected_maintenance = request.args.get("bakim_durumu", "").strip()
    selected_work_order = request.args.get("is_emri_durumu", "").strip()
    selected_critical = request.args.get("kritik", "").strip()

    query = havalimani_filtreli_sorgu(Malzeme)
    if _can_view_all_operational_scope() and selected_airport:
        query = query.filter(Malzeme.havalimani_id == selected_airport)

    if selected_critical == "1":
        query = query.filter(Malzeme.kritik_mi.is_(True))

    malzemeler = query.order_by(Malzeme.created_at.desc()).all()
    malzemeler = [
        malzeme
        for malzeme in malzemeler
        if not malzeme.linked_asset or malzeme.linked_asset.lifecycle_status not in {"disposed", "decommissioned"}
    ]
    today = get_tr_now().date()

    if selected_maintenance:
        filtered = []
        for malzeme in malzemeler:
            next_date = malzeme.gelecek_bakim_tarihi
            if selected_maintenance == "geciken" and next_date and next_date < today:
                filtered.append(malzeme)
            elif selected_maintenance == "yaklasan" and next_date and today <= next_date <= (today + timedelta(days=15)):
                filtered.append(malzeme)
            elif selected_maintenance == "normal" and (not next_date or next_date > (today + timedelta(days=15))):
                filtered.append(malzeme)
        malzemeler = filtered

    if selected_category:
        malzemeler = [
            item
            for item in malzemeler
            if item.linked_asset
            and item.linked_asset.equipment_template
            and (item.linked_asset.equipment_template.category or "").lower() == selected_category.lower()
        ]

    if selected_work_order:
        filtered = []
        for malzeme in malzemeler:
            asset = malzeme.linked_asset
            if not asset:
                continue
            has_match = any(order.status == selected_work_order for order in asset.work_orders if not order.is_deleted)
            if has_match:
                filtered.append(malzeme)
        malzemeler = filtered

    if _can_view_all_operational_scope():
        h_ad = "Genel Envanter (Tüm Birimler)"
        havalimanlari = _visible_operational_airports()
    else:
        h_ad = current_user.havalimani.ad
        havalimanlari = [current_user.havalimani] if current_user.havalimani else []

    categories = (
        db.session.query(EquipmentTemplate.category)
        .filter(
            EquipmentTemplate.is_deleted.is_(False),
            EquipmentTemplate.category.isnot(None),
            EquipmentTemplate.category != "",
        )
        .distinct()
        .all()
    )

    return render_template(
        "envanter.html",
        malzemeler=malzemeler,
        havalimani_ad=h_ad,
        havalimanlari=havalimanlari,
        categories=[row[0] for row in categories],
        selected_airport=selected_airport,
        selected_category=selected_category,
        selected_maintenance=selected_maintenance,
        selected_work_order=selected_work_order,
        selected_critical=selected_critical,
    )


@inventory_bp.route("/malzeme-ekle", methods=["GET", "POST"])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"), methods=["POST"])
@permission_required("inventory.create")
def malzeme_ekle():
    templates = EquipmentTemplate.query.filter_by(is_deleted=False, is_active=True).order_by(
        EquipmentTemplate.name.asc()
    ).all()
    form_templates = MaintenanceFormTemplate.query.filter_by(is_deleted=False, is_active=True).order_by(
        MaintenanceFormTemplate.name.asc()
    ).all()

    if request.method == "POST":
        kutu_kodu = guvenli_metin(request.form.get("kutu_kodu") or "").upper().strip()
        if not kutu_kodu:
            flash("Kutu/depo kodu zorunludur.", "danger")
            return redirect(url_for("inventory.malzeme_ekle"))

        if current_user.is_sahip:
            havalimani_id = request.form.get("havalimani_id", type=int)
            if not havalimani_id:
                havalimani_id = current_user.havalimani_id or 1
        else:
            havalimani_id = current_user.havalimani_id

        template_id = request.form.get("template_id", type=int)
        central_catalog_flag = request.form.get("central_catalog") == "on"
        template = _ensure_template_from_form(request.form, template_id)

        if not template and central_catalog_flag:
            flash("Merkezi katalog kaydı için malzeme adı zorunludur.", "danger")
            return redirect(url_for("inventory.malzeme_ekle"))

        if not template:
            # Şablon seçimi yapılmadıysa bile profesyonel yapıyı korumak için yerel bir şablon oluşturuyoruz.
            template = _ensure_template_from_form(request.form, None)

        if not template:
            flash("Merkezi şablon oluşturulamadı.", "danger")
            return redirect(url_for("inventory.malzeme_ekle"))

        kutu = _ensure_box(kutu_kodu, havalimani_id)
        asset, legacy_material = _create_asset_and_legacy_material(
            template=template,
            kutu=kutu,
            havalimani_id=havalimani_id,
            form_data=request.form,
        )

        db.session.commit()
        log_kaydet(
            "Envanter",
            f"Yeni ekipman eklendi: {legacy_material.ad} ({legacy_material.havalimani.kodu}) / Şablon: {template.name}",
        )
        audit_log("inventory.asset.create", outcome="success", asset_id=asset.id, airport_id=havalimani_id)
        if asset.parent_asset_id:
            audit_log(
                "inventory.asset.link_child",
                outcome="success",
                asset_id=asset.id,
                parent_asset_id=asset.parent_asset_id,
            )
        flash("Malzeme başarıyla eklendi ve bakım varlığı oluşturuldu.", "success")
        return redirect(url_for("inventory.envanter"))

    if current_user.is_sahip:
        havalimanlari = _visible_operational_airports()
    else:
        havalimanlari = [current_user.havalimani] if current_user.havalimani else []
    parent_candidates = _asset_scope().order_by(InventoryAsset.created_at.desc()).limit(200).all()

    return render_template(
        "malzeme_ekle.html",
        templates=templates,
        form_templates=form_templates,
        havalimanlari=havalimanlari,
        parent_candidates=parent_candidates,
    )


@inventory_bp.route("/merkezi-katalog")
@login_required
@permission_required("inventory.create")
def merkezi_katalog():
    templates = EquipmentTemplate.query.filter_by(is_deleted=False, is_active=True).order_by(
        EquipmentTemplate.name.asc()
    ).all()
    form_templates = MaintenanceFormTemplate.query.filter_by(is_deleted=False, is_active=True).order_by(
        MaintenanceFormTemplate.name.asc()
    ).all()
    airports = _visible_operational_airports()
    return render_template(
        "ekipman_sablonlari.html",
        templates=templates,
        form_templates=form_templates,
        airports=airports,
    )


@inventory_bp.route("/merkezi-sablondan-envantere-ekle/<int:template_id>", methods=["POST"])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
@permission_required("inventory.create")
def merkezi_sablondan_envantere_ekle(template_id):
    template = EquipmentTemplate.query.filter_by(id=template_id, is_deleted=False, is_active=True).first_or_404()

    if current_user.is_sahip:
        havalimani_id = request.form.get("havalimani_id", type=int) or current_user.havalimani_id or 1
    else:
        havalimani_id = current_user.havalimani_id

    kutu_kodu = guvenli_metin(request.form.get("kutu_kodu") or "MERKEZ-01").upper().strip()
    kutu = _ensure_box(kutu_kodu, havalimani_id)

    asset, legacy_material = _create_asset_and_legacy_material(
        template=template,
        kutu=kutu,
        havalimani_id=havalimani_id,
        form_data=request.form,
    )
    legacy_material.ad = template.name

    db.session.commit()
    log_kaydet(
        "Merkezi Şablon",
        f"Merkezi şablondan birime ekipman eklendi: {template.name} -> {legacy_material.havalimani.kodu}",
    )
    if asset.parent_asset_id:
        audit_log(
            "inventory.asset.link_child",
            outcome="success",
            asset_id=asset.id,
            parent_asset_id=asset.parent_asset_id,
        )
    flash("Merkezi katalogdan ekipman envantere eklendi.", "success")
    return redirect(url_for("inventory.envanter"))


@inventory_bp.route("/asset-duzenle/<int:asset_id>", methods=["POST"])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
@permission_required("inventory.edit")
def asset_duzenle(asset_id):
    asset = _asset_scope().filter(InventoryAsset.id == asset_id).first_or_404()
    requested_asset_code = guvenli_metin(request.form.get("asset_code") or "").strip()
    if requested_asset_code and requested_asset_code != asset.asset_code:
        log_kaydet(
            "Güvenlik",
            f"Asset code değişikliği denemesi engellendi: {asset.asset_code} -> {requested_asset_code}",
            event_key="inventory.asset_code.change_attempt",
            target_model="InventoryAsset",
            target_id=asset.id,
            outcome="failed",
        )
        audit_log("inventory.asset_code.change_attempt", outcome="failed", asset_id=asset.id)
        flash("Asset code doğrudan değiştirilemez.", "danger")
        return redirect(url_for("inventory.envanter"))
    asset.serial_no = guvenli_metin(request.form.get("seri_no") or asset.serial_no)
    asset.unit_count = request.form.get("stok", type=int) or asset.unit_count
    asset.depot_location = guvenli_metin(request.form.get("depo_konumu") or asset.depot_location)
    asset.status = _normalize_status(request.form.get("durum", _display_status(asset.status)))
    asset.maintenance_state = guvenli_metin(request.form.get("bakim_durumu") or asset.maintenance_state)
    asset.last_maintenance_date = _parse_date(request.form.get("son_bakim_tarihi")) or asset.last_maintenance_date
    asset.next_maintenance_date = _parse_date(request.form.get("sonraki_bakim_tarihi")) or asset.next_maintenance_date
    asset.notes = guvenli_metin(request.form.get("notlar") or asset.notes)

    new_parent_id = request.form.get("parent_asset_id", type=int)
    if new_parent_id == asset.id:
        flash("Bir ekipman kendisine bağlanamaz.", "danger")
        return redirect(url_for("inventory.envanter"))
    if new_parent_id:
        parent_candidate = _asset_scope().filter(InventoryAsset.id == new_parent_id).first()
        if not parent_candidate:
            flash("Üst ekipman seçimi geçersiz.", "danger")
            return redirect(url_for("inventory.envanter"))
        asset.parent_asset_id = parent_candidate.id
    elif request.form.get("parent_asset_id") == "":
        asset.parent_asset_id = None

    if asset.legacy_material:
        asset.legacy_material.seri_no = asset.serial_no
        asset.legacy_material.stok_miktari = asset.unit_count
        asset.legacy_material.durum = _display_status(asset.status)
        asset.legacy_material.son_bakim_tarihi = asset.last_maintenance_date
        asset.legacy_material.gelecek_bakim_tarihi = asset.next_maintenance_date
        db.session.commit()
    log_kaydet("Envanter", f"Yerel asset güncellendi: ID {asset.id}")
    if asset.parent_asset_id:
        audit_log(
            "inventory.asset.link_child",
            outcome="success",
            asset_id=asset.id,
            parent_asset_id=asset.parent_asset_id,
        )
    flash("Envanter kaydı güncellendi.", "success")
    return redirect(url_for("inventory.envanter"))


@inventory_bp.route("/bakim-kaydet/<int:id>", methods=["POST"])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
@permission_required("maintenance.edit")
def bakim_kaydet(id):
    malzeme = Malzeme.query.filter_by(id=id, is_deleted=False).first_or_404()
    if not has_permission("settings.manage") and malzeme.havalimani_id != current_user.havalimani_id:
        flash("Farklı bir birimin malzemesine bakım girişi yapamazsınız.", "danger")
        abort(403)

    guvenli_not = guvenli_metin(request.form.get("not"))
    yeni_kayit = BakimKaydi(
        malzeme_id=id,
        yapan_personel_id=current_user.id,
        islem_notu=guvenli_not,
        maliyet=float(request.form.get("maliyet", 0)),
    )

    malzeme.son_bakim_tarihi = get_tr_now().date()
    yeni_gelecek = request.form.get("gelecek_bakim")
    if yeni_gelecek:
        malzeme.gelecek_bakim_tarihi = datetime.strptime(yeni_gelecek, "%Y-%m-%d").date()

    db.session.add(yeni_kayit)

    if malzeme.linked_asset:
        asset = malzeme.linked_asset
        asset.last_maintenance_date = malzeme.son_bakim_tarihi
        if malzeme.gelecek_bakim_tarihi:
            asset.next_maintenance_date = malzeme.gelecek_bakim_tarihi

        history = MaintenanceHistory(
            asset_id=asset.id,
            performed_by_id=current_user.id,
            maintenance_type="bakim",
            result="Bakım kaydı tamamlandı",
            notes=guvenli_not,
            next_maintenance_date=asset.next_maintenance_date,
        )
        db.session.add(history)

    db.session.commit()

    log_kaydet("Bakım", f"{malzeme.ad} için bakım kaydı girildi ({malzeme.havalimani.kodu})")
    flash("Bakım kaydı başarıyla işlendi.", "success")
    return redirect(url_for("inventory.envanter"))


@inventory_bp.route("/envanter/excel")
@login_required
@permission_required("inventory.export")
def envanter_excel():
    malzemeler = havalimani_filtreli_sorgu(Malzeme).all()
    if len(malzemeler) > int(current_app.config.get("MAX_EXPORT_ROWS", 10000)):
        abort(413)
    data = [
        {
            "Birim": m.havalimani.kodu,
            "Kutu": m.kutu.kodu,
            "Malzeme Adı": m.ad,
            "Seri No": m.seri_no,
            "Durum": m.durum,
            "Son Bakım": m.son_bakim_tarihi.strftime("%d.%m.%Y") if m.son_bakim_tarihi else "-",
            "Gelecek Bakım": m.gelecek_bakim_tarihi.strftime("%d.%m.%Y") if m.gelecek_bakim_tarihi else "-",
        }
        for m in malzemeler
    ]

    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)
    output.seek(0)

    log_kaydet("Rapor", f"Envanter Excel raporu oluşturuldu ({current_user.rol})")
    return send_file(
        output,
        download_name=f"SAR_Envanter_{datetime.now(TR_TZ).strftime('%Y%m%d')}.xlsx",
        as_attachment=True,
    )


@inventory_bp.route("/malzeme-sil/<int:id>", methods=["GET"], endpoint="malzeme_sil_legacy")
@login_required
@permission_required("inventory.delete")
def malzeme_sil_legacy(id):
    flash("Bu işlem yalnızca form gönderimi ile yapılabilir.", "warning")
    return redirect(request.referrer or url_for("inventory.dashboard"))


@inventory_bp.route("/malzeme-sil/<int:id>", methods=["POST"])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"), methods=["POST"])
@permission_required("inventory.delete")
def malzeme_sil(id):
    malzeme = db.session.get(Malzeme, id)
    if malzeme and not malzeme.is_deleted:
        malzeme_adi = malzeme.ad
        malzeme.soft_delete()

        if malzeme.linked_asset and not malzeme.linked_asset.is_deleted:
            for child in malzeme.linked_asset.child_assets:
                if not child.is_deleted:
                    child.parent_asset_id = None
            malzeme.linked_asset.soft_delete()

        db.session.commit()

        log_kaydet("Envanter", f"Malzeme arşive gönderildi: {malzeme_adi}")
        flash(f"'{malzeme_adi}' başarıyla silindi ve arşive taşındı.", "info")
    else:
        flash("Hata: Malzeme bulunamadı veya zaten silinmiş.", "danger")

    return redirect(request.referrer or url_for("inventory.dashboard"))


@inventory_bp.route("/envanter/pdf")
@login_required
@permission_required("inventory.export")
def envanter_pdf():
    malzemeler = havalimani_filtreli_sorgu(Malzeme).all()
    if len(malzemeler) > int(current_app.config.get("MAX_EXPORT_ROWS", 10000)):
        abort(413)
    html = render_template("pdf_sablonu.html", malzemeler=malzemeler, tarih=datetime.now(TR_TZ))
    output = io.BytesIO()
    pisa.CreatePDF(html, dest=output)
    output.seek(0)

    log_kaydet("Rapor", f"Envanter PDF raporu oluşturuldu ({current_user.rol})")
    return send_file(
        output,
        download_name=f"SAR_Rapor_{datetime.now(TR_TZ).strftime('%Y%m%d')}.pdf",
        as_attachment=True,
    )


@inventory_bp.route("/zimmetler", methods=["GET", "POST"])
@login_required
@permission_required("assignment.view")
def zimmetler():
    selected_airport = request.args.get("airport_id", type=int)
    selected_status = (request.args.get("status") or "").strip()
    selected_recipient = request.args.get("recipient_id", type=int)

    visible_airports = _visible_operational_airports()
    if not _can_view_all_operational_scope():
        selected_airport = current_user.havalimani_id

    can_create_assignment = has_permission("assignment.create") and _can_issue_assignments(current_user)

    if request.method == "POST":
        if not can_create_assignment:
            abort(403)

        airport_id = request.form.get("airport_id", type=int) or current_user.havalimani_id
        if _can_view_all_operational_scope():
            airport_allowed = any(airport.id == airport_id for airport in visible_airports)
        else:
            airport_allowed = airport_id == current_user.havalimani_id
        if not airport_allowed:
            flash("Seçilen havalimanı için zimmet oluşturma yetkiniz yok.", "danger")
            return redirect(url_for("inventory.zimmetler", airport_id=selected_airport or None))

        delivered_by_name = guvenli_metin(request.form.get("delivered_by_name") or "").strip()
        if not delivered_by_name:
            delivered_by_name = guvenli_metin(getattr(current_user, "tam_ad", "") or "").strip()
        visible_user_ids = {user.id for user in _visible_personnel_query(airport_id).all()}

        recipient_ids = list(dict.fromkeys(_parse_int_list(request.form.getlist("recipient_ids"))))
        recipient_ids = [user_id for user_id in recipient_ids if user_id in visible_user_ids]
        if not recipient_ids:
            flash("En az bir teslim alan personel seçin.", "danger")
            return redirect(url_for("inventory.zimmetler", airport_id=airport_id or None))

        visible_materials = {
            item.id: item
            for item in _visible_material_query(airport_id).order_by(Malzeme.ad.asc()).all()
        }
        selected_item_ids = list(dict.fromkeys(_parse_int_list(request.form.getlist("item_ids"))))
        selected_items = [visible_materials[item_id] for item_id in selected_item_ids if item_id in visible_materials]
        if not selected_items:
            flash("En az bir malzeme seçin.", "danger")
            return redirect(url_for("inventory.zimmetler", airport_id=airport_id or None))

        assignment = AssignmentRecord(
            assignment_no=_next_assignment_no(),
            assignment_date=_parse_date(request.form.get("assignment_date")) or get_tr_now().date(),
            delivered_by_id=current_user.id,
            delivered_by_name=delivered_by_name,
            airport_id=airport_id,
            note=guvenli_metin(request.form.get("note") or ""),
            status="active",
            created_by_id=current_user.id,
        )
        db.session.add(assignment)
        db.session.flush()

        for user_id in recipient_ids:
            db.session.add(AssignmentRecipient(assignment_id=assignment.id, user_id=user_id))

        created_item_count = 0
        for material in selected_items:
            quantity = request.form.get(f"item_qty_{material.id}", type=float) or float(material.stok_miktari or 1)
            quantity = max(quantity, 0)
            if quantity <= 0:
                continue
            db.session.add(
                AssignmentItem(
                    assignment_id=assignment.id,
                    material_id=material.id,
                    asset_id=material.linked_asset.id if material.linked_asset else None,
                    item_name=material.ad,
                    quantity=quantity,
                    unit=guvenli_metin(request.form.get(f"item_unit_{material.id}") or "adet") or "adet",
                    note=guvenli_metin(request.form.get(f"item_note_{material.id}") or ""),
                )
            )
            created_item_count += 1

        if created_item_count == 0:
            db.session.rollback()
            flash("Seçilen malzemeler için geçerli miktar bulunamadı.", "danger")
            return redirect(url_for("inventory.zimmetler", airport_id=airport_id or None))

        _append_assignment_history(assignment, "created", "Zimmet kaydı oluşturuldu.")
        db.session.commit()
        log_kaydet(
            "Zimmet",
            f"Zimmet oluşturuldu: {assignment.assignment_no}",
            event_key="assignment.create",
            target_model="AssignmentRecord",
            target_id=assignment.id,
        )
        audit_log("assignment.create", outcome="success", assignment_id=assignment.id, airport_id=airport_id)
        flash("Zimmet kaydı oluşturuldu.", "success")
        flash("Zimmet formu PDF olarak indirilebilir.", "info")
        return redirect(url_for("inventory.zimmet_detay", assignment_id=assignment.id))

    query = _assignment_scope()
    if selected_status:
        query = query.filter(AssignmentRecord.status == selected_status)
    if selected_recipient:
        query = query.join(AssignmentRecipient).filter(AssignmentRecipient.user_id == selected_recipient)
    if selected_airport:
        query = query.filter(AssignmentRecord.airport_id == selected_airport)
    assignments = query.order_by(AssignmentRecord.assignment_date.desc(), AssignmentRecord.created_at.desc()).all()

    recipient_query = _visible_personnel_query(selected_airport)
    if not can_create_assignment and not has_permission("assignment.manage"):
        recipient_query = recipient_query.filter(Kullanici.id == current_user.id)
    recipient_options = recipient_query.order_by(Kullanici.tam_ad.asc()).all()
    material_options = _visible_material_query(selected_airport).order_by(Malzeme.ad.asc()).limit(250).all()
    recipient_lookup = {user.id: user for user in recipient_options}
    selected_recipient_user = recipient_lookup.get(selected_recipient)
    if not selected_recipient_user and not can_create_assignment and getattr(current_user, "id", None) in recipient_lookup:
        selected_recipient_user = recipient_lookup[current_user.id]

    recipient_active_assignments = []
    if selected_recipient_user:
        recipient_assignment_query = _assignment_scope()
        if can_create_assignment or selected_recipient_user.id != getattr(current_user, "id", None):
            recipient_assignment_query = recipient_assignment_query.join(AssignmentRecipient).filter(
                AssignmentRecipient.user_id == selected_recipient_user.id,
            )
        recipient_active_assignments = (
            recipient_assignment_query
            .filter(AssignmentRecord.status.in_(["active", "partial"]))
            .order_by(AssignmentRecord.assignment_date.desc(), AssignmentRecord.created_at.desc())
            .distinct()
            .all()
        )

    return render_template(
        "zimmetler.html",
        assignments=assignments,
        airports=visible_airports,
        recipient_options=recipient_options,
        material_options=material_options,
        assignment_status_labels=ASSIGNMENT_STATUS_LABELS,
        selected_airport=selected_airport,
        selected_status=selected_status,
        selected_recipient=selected_recipient,
        selected_recipient_user=selected_recipient_user,
        recipient_active_assignments=recipient_active_assignments,
        can_create_assignment=can_create_assignment,
    )


@inventory_bp.route("/zimmetler/<int:assignment_id>")
@login_required
@permission_required("assignment.view")
def zimmet_detay(assignment_id):
    assignment = _assignment_scope().filter(AssignmentRecord.id == assignment_id).first_or_404()
    return render_template(
        "zimmet_detay.html",
        assignment=assignment,
        assignment_status_label=_assignment_status_label,
        can_manage_assignment=has_permission("assignment.manage"),
        can_upload_assignment_document=has_permission("assignment.document.upload"),
        can_download_assignment_pdf=has_permission("assignment.pdf"),
    )


@inventory_bp.route("/zimmetler/<int:assignment_id>/pdf")
@login_required
@permission_required("assignment.pdf")
def zimmet_pdf(assignment_id):
    assignment = _assignment_scope().filter(AssignmentRecord.id == assignment_id).first_or_404()
    font_uris = _assignment_pdf_font_uris()
    html = render_template(
        "zimmet_pdf.html",
        assignment=assignment,
        assignment_status_label=_assignment_status_label,
        generated_at=get_tr_now(),
        pdf_font_regular=font_uris["regular"],
        pdf_font_bold=font_uris["bold"],
    )
    output = io.BytesIO()
    pdf_result = pisa.CreatePDF(
        html,
        dest=output,
        encoding="utf-8",
        link_callback=_pdf_link_callback,
    )
    if pdf_result.err:
        current_app.logger.error("Zimmet PDF olusturulamadi | assignment_id=%s", assignment.id)
        abort(500)
    output.seek(0)
    audit_log("assignment.pdf", outcome="success", assignment_id=assignment.id)
    return send_file(
        output,
        download_name=f"{assignment.assignment_no}.pdf",
        as_attachment=True,
        mimetype="application/pdf",
    )


@inventory_bp.route("/zimmetler/<int:assignment_id>/signed-document", methods=["POST"])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
@permission_required("assignment.document.upload")
def zimmet_imzali_belge_yukle(assignment_id):
    assignment = _assignment_scope().filter(AssignmentRecord.id == assignment_id).first_or_404()
    upload = request.files.get("signed_document")
    safe_name, error = _validate_upload(
        upload,
        SIGNED_ASSIGNMENT_ALLOWED_EXTENSIONS,
        ("application/pdf", "image/"),
    )
    if error:
        flash(error, "danger")
        return redirect(url_for("inventory.zimmet_detay", assignment_id=assignment.id))

    filename = f"{assignment.assignment_no.lower()}_{int(get_tr_now().timestamp())}_{safe_name}"
    stored = get_storage_adapter().save_upload(upload, folder="assignments", filename=filename)
    assignment.signed_document_key = stored.storage_key
    assignment.signed_document_url = stored.public_url
    assignment.signed_document_name = safe_name
    _append_assignment_history(assignment, "signed_upload", "İmzalı belge yüklendi.")
    db.session.commit()

    log_kaydet(
        "Zimmet",
        f"İmzalı belge yüklendi: {assignment.assignment_no}",
        event_key="assignment.document.upload",
        target_model="AssignmentRecord",
        target_id=assignment.id,
    )
    flash("İmzalı zimmet belgesi yüklendi.", "success")
    return redirect(url_for("inventory.zimmet_detay", assignment_id=assignment.id))


@inventory_bp.route("/zimmetler/<int:assignment_id>/signed-document/download")
@login_required
@permission_required("assignment.view")
def zimmet_imzali_belge_indir(assignment_id):
    assignment = _assignment_scope().filter(AssignmentRecord.id == assignment_id).first_or_404()
    if not assignment.signed_document_url:
        flash("Bu zimmet için yüklü imzalı belge bulunmuyor.", "warning")
        return redirect(url_for("inventory.zimmet_detay", assignment_id=assignment.id))
    return redirect(assignment.signed_document_url)


@inventory_bp.route("/zimmetler/<int:assignment_id>/iade", methods=["POST"])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
@permission_required("assignment.manage")
def zimmet_iade(assignment_id):
    assignment = _assignment_scope().filter(AssignmentRecord.id == assignment_id).first_or_404()
    processed = 0
    for item in assignment.items:
        returned_amount = request.form.get(f"return_qty_{item.id}", type=float) or 0
        if returned_amount <= 0:
            continue
        item.returned_quantity = min(float(item.quantity or 0), float(item.returned_quantity or 0) + returned_amount)
        item.returned_at = get_tr_now()
        item.returned_by_id = current_user.id
        note = guvenli_metin(request.form.get(f"return_note_{item.id}") or "")
        if note:
            item.return_note = note
        processed += 1

    if processed == 0:
        flash("İade işlemi için en az bir kalemde miktar girin.", "danger")
        return redirect(url_for("inventory.zimmet_detay", assignment_id=assignment.id))

    _recalculate_assignment_status(assignment)
    _append_assignment_history(
        assignment,
        "return",
        f"{processed} kalem için iade işlemi kaydedildi. Durum: {_assignment_status_label(assignment.status)}",
    )
    db.session.commit()
    flash("İade işlemi kaydedildi.", "success")
    return redirect(url_for("inventory.zimmet_detay", assignment_id=assignment.id))


@inventory_bp.route("/zimmetler/<int:assignment_id>/durum", methods=["POST"])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
@permission_required("assignment.manage")
def zimmet_durum_guncelle(assignment_id):
    assignment = _assignment_scope().filter(AssignmentRecord.id == assignment_id).first_or_404()
    new_status = (request.form.get("status") or "").strip()
    if new_status not in ASSIGNMENT_STATUS_LABELS:
        flash("Geçersiz zimmet durumu.", "danger")
        return redirect(url_for("inventory.zimmet_detay", assignment_id=assignment.id))
    assignment.status = new_status
    _append_assignment_history(assignment, "status", f"Durum güncellendi: {_assignment_status_label(new_status)}")
    db.session.commit()
    flash("Zimmet durumu güncellendi.", "success")
    return redirect(url_for("inventory.zimmet_detay", assignment_id=assignment.id))


@inventory_bp.route("/kkd", methods=["GET", "POST"], endpoint="kkd_listesi")
@login_required
@permission_required("ppe.view")
def kkd_listesi():
    selected_status = (request.args.get("status") or "").strip()
    selected_user = request.args.get("user_id", type=int)
    selected_airport = request.args.get("airport_id", type=int)

    visible_airports = _visible_operational_airports()
    if not _can_view_all_operational_scope() and has_permission("ppe.manage"):
        selected_airport = current_user.havalimani_id

    if request.method == "POST":
        if not has_permission("ppe.manage"):
            abort(403)

        visible_users = {item.id: item for item in _visible_personnel_query(selected_airport).all()}
        user_id = request.form.get("user_id", type=int)
        if user_id not in visible_users:
            flash("KKD kaydı için geçerli bir personel seçin.", "danger")
            return redirect(url_for("inventory.kkd_listesi", airport_id=selected_airport or None))

        upload = request.files.get("photo_document")
        photo_key = None
        photo_url = None
        if upload and upload.filename:
            safe_name, error = _validate_upload(
                upload,
                PPE_ALLOWED_EXTENSIONS,
                ("application/pdf", "image/"),
            )
            if error:
                flash(error, "danger")
                return redirect(url_for("inventory.kkd_listesi", airport_id=selected_airport or None))
            filename = f"ppe_{user_id}_{int(get_tr_now().timestamp())}_{safe_name}"
            stored = get_storage_adapter().save_upload(upload, folder="ppe", filename=filename)
            photo_key = stored.storage_key
            photo_url = stored.public_url

        assignment_id = request.form.get("assignment_id", type=int)
        if assignment_id:
            assignment = _assignment_scope().filter(AssignmentRecord.id == assignment_id).first()
            if not assignment:
                assignment_id = None

        record = PPERecord(
            user_id=user_id,
            airport_id=visible_users[user_id].havalimani_id or current_user.havalimani_id,
            assignment_id=assignment_id,
            item_name=guvenli_metin(request.form.get("item_name") or ""),
            brand_model=guvenli_metin(request.form.get("brand_model") or ""),
            size_info=guvenli_metin(request.form.get("size_info") or ""),
            delivered_at=_parse_date(request.form.get("delivered_at")) or get_tr_now().date(),
            quantity=max(request.form.get("quantity", type=int) or 1, 1),
            status=(request.form.get("status") or "aktif").strip(),
            description=guvenli_metin(request.form.get("description") or ""),
            photo_storage_key=photo_key,
            photo_url=photo_url,
            created_by_id=current_user.id,
        )
        if not record.item_name:
            flash("KKD malzeme adı zorunludur.", "danger")
            return redirect(url_for("inventory.kkd_listesi", airport_id=selected_airport or None))

        db.session.add(record)
        db.session.flush()
        db.session.add(
            PPERecordEvent(
                ppe_record_id=record.id,
                event_type="create",
                status_after=record.status,
                event_note="KKD tahsis kaydı oluşturuldu.",
                created_by_id=current_user.id,
            )
        )
        db.session.commit()
        flash("KKD kaydı oluşturuldu.", "success")
        return redirect(url_for("inventory.kkd_listesi", user_id=user_id))

    query = _ppe_scope()
    if selected_status:
        query = query.filter(PPERecord.status == selected_status)
    if selected_user:
        query = query.filter(PPERecord.user_id == selected_user)
    if selected_airport:
        query = query.filter(PPERecord.airport_id == selected_airport)
    records = query.order_by(PPERecord.delivered_at.desc(), PPERecord.created_at.desc()).all()

    visible_user_query = _visible_personnel_query(selected_airport)
    if not has_permission("ppe.manage"):
        visible_user_query = visible_user_query.filter(Kullanici.id == current_user.id)

    return render_template(
        "kkd.html",
        records=records,
        visible_users=visible_user_query.order_by(Kullanici.tam_ad.asc()).all(),
        visible_airports=visible_airports,
        active_assignments=_assignment_scope().filter(AssignmentRecord.status.in_(["active", "partial"])).order_by(AssignmentRecord.assignment_date.desc()).all(),
        ppe_status_labels=PPE_STATUS_LABELS,
        selected_status=selected_status,
        selected_user=selected_user,
        selected_airport=selected_airport,
        can_manage_ppe=has_permission("ppe.manage"),
        can_request_ppe=has_permission("ppe.request"),
    )


@inventory_bp.route("/kkd/<int:record_id>/bildirim", methods=["POST"])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
@permission_required("ppe.request")
def kkd_bildirim(record_id):
    record = _ppe_scope().filter(PPERecord.id == record_id).first_or_404()
    if not has_permission("ppe.manage") and record.user_id != current_user.id:
        abort(403)

    new_status = (request.form.get("status") or "").strip()
    if has_permission("ppe.manage"):
        allowed_statuses = set(PPE_STATUS_LABELS.keys())
    else:
        allowed_statuses = {"eksik", "hasarli", "kayip", "kullanim_disi", "degisim_talebi"}
    if new_status not in allowed_statuses:
        flash("Geçersiz KKD durum bildirimi.", "danger")
        return redirect(url_for("inventory.kkd_listesi"))

    note = guvenli_metin(request.form.get("event_note") or "")
    record.status = new_status
    if note:
        existing = (record.description or "").strip()
        record.description = f"{existing}\n{note}".strip() if existing else note

    db.session.add(
        PPERecordEvent(
            ppe_record_id=record.id,
            event_type="status_update" if has_permission("ppe.manage") else "user_report",
            status_after=new_status,
            event_note=note or "Durum güncellendi.",
            created_by_id=current_user.id,
        )
    )
    db.session.commit()
    flash("KKD bildirimi kaydedildi.", "success")
    return redirect(url_for("inventory.kkd_listesi", user_id=record.user_id if has_permission("ppe.manage") else None))


@inventory_bp.route("/kkd/export/<string:fmt>")
@login_required
@permission_required("ppe.manage")
def kkd_export(fmt):
    selected_status = (request.args.get("status") or "").strip()
    selected_airport = request.args.get("airport_id", type=int)
    selected_user = request.args.get("user_id", type=int)

    query = _ppe_scope()
    if selected_status:
        query = query.filter(PPERecord.status == selected_status)
    if selected_airport:
        query = query.filter(PPERecord.airport_id == selected_airport)
    if selected_user:
        query = query.filter(PPERecord.user_id == selected_user)

    records = query.order_by(PPERecord.delivered_at.desc()).all()
    rows = [
        {
            "Personel": record.user.tam_ad if record.user else "-",
            "Havalimanı": record.airport.ad if record.airport else "-",
            "KKD": record.item_name,
            "Marka/Model": record.brand_model or "-",
            "Beden": record.size_info or "-",
            "Teslim Tarihi": record.delivered_at.strftime("%d.%m.%Y") if record.delivered_at else "-",
            "Miktar": record.quantity,
            "Durum": _ppe_status_label(record.status),
            "Açıklama": record.description or "-",
        }
        for record in records
    ]

    if fmt == "xlsx":
        payload = io.BytesIO()
        with pd.ExcelWriter(payload, engine="openpyxl") as writer:
            pd.DataFrame(rows).to_excel(writer, index=False)
        payload.seek(0)
        return send_file(
            payload,
            as_attachment=True,
            download_name=f"kkd_raporu_{get_tr_now().strftime('%Y%m%d')}.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    if fmt == "pdf":
        html = render_template(
            "kkd_report_pdf.html",
            records=records,
            ppe_status_label=_ppe_status_label,
            generated_at=get_tr_now(),
        )
        payload = io.BytesIO()
        pisa.CreatePDF(html, dest=payload)
        payload.seek(0)
        return send_file(
            payload,
            as_attachment=True,
            download_name=f"kkd_raporu_{get_tr_now().strftime('%Y%m%d')}.pdf",
            mimetype="application/pdf",
        )
    flash("Desteklenmeyen export formatı.", "danger")
    return redirect(url_for("inventory.kkd_listesi"))


@inventory_bp.route("/tatbikatlar")
@login_required
@permission_required("drill.view")
def tatbikat_listesi():
    selected_airport = request.args.get("airport_id", type=int)
    airports = _visible_drill_airports()
    visible_airport_ids = {airport.id for airport in airports}
    if selected_airport and selected_airport not in visible_airport_ids:
        abort(403)
    if not current_user.is_sahip:
        selected_airport = current_user.havalimani_id

    query = _drill_scope().order_by(TatbikatBelgesi.tatbikat_tarihi.desc(), TatbikatBelgesi.created_at.desc())
    if selected_airport:
        query = query.filter(TatbikatBelgesi.havalimani_id == selected_airport)

    documents = query.all()
    drill_airport_select_enabled = bool(current_user.is_sahip)
    can_manage_drills = has_permission("drill.manage") and _can_manage_drills_for_airport(selected_airport or current_user.havalimani_id)
    return render_template(
        "tatbikatlar.html",
        documents=documents,
        airports=airports,
        selected_airport=selected_airport,
        can_manage_drills=can_manage_drills,
        drill_airport_select_enabled=drill_airport_select_enabled,
        format_file_size=_format_drill_file_size,
    )


@inventory_bp.route("/tatbikatlar/yukle", methods=["POST"])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
@permission_required("drill.manage")
def tatbikat_yukle():
    airport_id = request.form.get("airport_id", type=int)
    if not current_user.is_sahip:
        airport_id = current_user.havalimani_id
    if airport_id is None:
        flash("Tatbikat belgesi için havalimanı seçin.", "danger")
        return redirect(url_for("inventory.tatbikat_listesi"))
    if not _can_manage_drills_for_airport(airport_id):
        abort(403)

    airport = apply_platform_demo_scope(
        Havalimani.query.filter_by(id=airport_id, is_deleted=False),
        "Havalimani",
        Havalimani.id,
    ).first_or_404()
    title = guvenli_metin(request.form.get("title") or "")
    description = guvenli_metin(request.form.get("description") or "")
    upload = request.files.get("document")
    safe_name, mime_type, error = _validate_drill_upload(upload)
    if error:
        flash(error, "danger")
        return redirect(url_for("inventory.tatbikat_listesi", airport_id=airport_id))
    drill_date_raw = request.form.get("drill_date")
    drill_date = _parse_date(drill_date_raw)
    if not drill_date:
        flash("Tatbikat tarihi zorunludur. Geçerli bir tarih seçin.", "danger")
        return redirect(url_for("inventory.tatbikat_listesi", airport_id=airport_id))
    try:
        storage_filename = _build_drill_storage_filename(drill_date, safe_name)
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("inventory.tatbikat_listesi", airport_id=airport_id))
    if not title:
        title = Path(storage_filename).stem

    drive_service = get_drill_drive_service()
    try:
        drive_result = drive_service.upload_file(
            airport=airport,
            upload=upload,
            filename=storage_filename,
            mime_type=mime_type,
        )
        record = TatbikatBelgesi(
            havalimani_id=airport.id,
            yukleyen_kullanici_id=current_user.id,
            baslik=title,
            tatbikat_tarihi=drill_date,
            aciklama=description,
            dosya_adi=drive_result["filename"],
            drive_file_id=drive_result["drive_file_id"],
            drive_folder_id=drive_result["drive_folder_id"],
            mime_type=drive_result["mime_type"],
            dosya_boyutu=drive_result["file_size"],
        )
        db.session.add(record)
        db.session.commit()
    except GoogleDriveError as exc:
        db.session.rollback()
        current_app.logger.warning("Tatbikat belgesi Drive'a yuklenemedi: %s", exc)
        flash("Tatbikat belgesi Google Drive'a yüklenemedi.", "danger")
        return redirect(url_for("inventory.tatbikat_listesi", airport_id=airport_id))
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Tatbikat belgesi kaydedilemedi.")
        try:
            if "drive_result" in locals():
                drive_service.delete_file(drive_result["drive_file_id"])
        except Exception:
            current_app.logger.warning("Tatbikat belgesi icin Drive temizleme islemi basarisiz.")
        flash("Tatbikat belgesi kaydedilemedi.", "danger")
        return redirect(url_for("inventory.tatbikat_listesi", airport_id=airport_id))

    log_kaydet(
        "Tatbikat",
        f"Tatbikat belgesi yüklendi: {record.baslik}",
        event_key="drill.upload",
        target_model="TatbikatBelgesi",
        target_id=record.id,
    )
    flash("Tatbikat belgesi Google Drive'a yüklendi.", "success")
    return redirect(url_for("inventory.tatbikat_detay", document_id=record.id))


@inventory_bp.route("/tatbikatlar/<int:document_id>")
@login_required
@permission_required("drill.view")
def tatbikat_detay(document_id):
    document = _get_drill_document_or_403(document_id)
    can_manage_document = has_permission("drill.manage") and _can_manage_drills_for_airport(document.havalimani_id)
    return render_template(
        "tatbikat_detay.html",
        document=document,
        can_manage_document=can_manage_document,
        format_file_size=_format_drill_file_size,
    )


@inventory_bp.route("/tatbikatlar/<int:document_id>/indir")
@login_required
@permission_required("drill.view")
def tatbikat_indir(document_id):
    document = _get_drill_document_or_403(document_id)
    try:
        payload = get_drill_drive_service().download_file(document.drive_file_id)
    except GoogleDriveError:
        current_app.logger.warning("Tatbikat belgesi indirilemedi: %s", document.drive_file_id)
        flash("Tatbikat belgesine şu an erişilemiyor.", "danger")
        return redirect(url_for("inventory.tatbikat_detay", document_id=document.id))

    return send_file(
        io.BytesIO(payload["content"]),
        mimetype=payload["mime_type"],
        as_attachment=True,
        download_name=document.dosya_adi,
    )


@inventory_bp.route("/tatbikatlar/<int:document_id>/goruntule")
@login_required
@permission_required("drill.view")
def tatbikat_goruntule(document_id):
    document = _get_drill_document_or_403(document_id)
    try:
        payload = get_drill_drive_service().download_file(document.drive_file_id)
    except GoogleDriveError:
        current_app.logger.warning("Tatbikat belgesi goruntulenemedi: %s", document.drive_file_id)
        flash("Tatbikat belgesine şu an erişilemiyor.", "danger")
        return redirect(url_for("inventory.tatbikat_detay", document_id=document.id))

    inline_mime = payload["mime_type"].startswith("image/") or payload["mime_type"] == "application/pdf"
    return send_file(
        io.BytesIO(payload["content"]),
        mimetype=payload["mime_type"],
        as_attachment=not inline_mime,
        download_name=document.dosya_adi,
    )


@inventory_bp.route("/tatbikatlar/<int:document_id>/sil", methods=["POST"])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
@permission_required("drill.manage")
def tatbikat_sil(document_id):
    document = _get_drill_document_or_403(document_id)
    if not _can_manage_drills_for_airport(document.havalimani_id):
        abort(403)

    try:
        get_drill_drive_service().delete_file(document.drive_file_id)
    except GoogleDriveError:
        current_app.logger.warning("Tatbikat belgesi Drive'dan silinemedi: %s", document.drive_file_id)
        flash("Tatbikat belgesi Google Drive'dan silinemedi.", "danger")
        return redirect(url_for("inventory.tatbikat_detay", document_id=document.id))

    document.soft_delete()
    db.session.commit()
    log_kaydet(
        "Tatbikat",
        f"Tatbikat belgesi silindi: {document.baslik}",
        event_key="drill.delete",
        target_model="TatbikatBelgesi",
        target_id=document.id,
    )
    flash("Tatbikat belgesi kaldırıldı.", "success")
    return redirect(url_for("inventory.tatbikat_listesi", airport_id=document.havalimani_id))


@inventory_bp.route("/google-drive/oauth/callback")
def google_drive_oauth_callback():
    error_code = str(request.args.get("error") or "").strip()
    if error_code:
        current_app.logger.warning("Google Drive OAuth reddedildi: %s", error_code)
        flash("Google Drive yetkilendirmesi tamamlanamadı.", "warning")
        return _redirect_after_google_oauth()

    code = str(request.args.get("code") or "").strip()
    if not code:
        current_app.logger.warning("Google Drive OAuth callback kod olmadan geldi.")
        flash("Google Drive dönüşünde yetkilendirme kodu alınamadı.", "danger")
        return _redirect_after_google_oauth()

    try:
        token_payload = get_drill_drive_service().exchange_authorization_code(code)
    except GoogleDriveError as exc:
        current_app.logger.warning("Google Drive OAuth callback başarısız: %s", exc)
        flash("Google Drive yetkilendirmesi alınamadı.", "danger")
        return _redirect_after_google_oauth()

    if token_payload.get("refresh_token"):
        current_app.logger.info("Google Drive OAuth callback başarıyla tamamlandı.")
        flash("Google Drive yetkilendirmesi başarıyla alındı.", "success")
    else:
        current_app.logger.warning("Google Drive OAuth callback refresh token dönmedi.")
        flash("Google Drive yetkilendirmesi tamamlandı ancak kalıcı refresh token dönmedi.", "warning")
    return _redirect_after_google_oauth()


@inventory_bp.route("/asset/<int:asset_id>/hiyerarsi")
@login_required
@permission_required("inventory.view")
def asset_hierarchy_detail(asset_id):
    asset = _asset_scope().filter(InventoryAsset.id == asset_id).first_or_404()
    siblings = []
    if asset.parent_asset_id:
        siblings = _asset_scope().filter(
            InventoryAsset.parent_asset_id == asset.parent_asset_id,
            InventoryAsset.id != asset.id,
        ).all()
    return render_template(
        "asset_hierarchy_detail.html",
        asset=asset,
        parent_asset=asset.parent_asset,
        child_assets=asset.child_assets,
        sibling_assets=siblings,
    )


@inventory_bp.route("/asset/<int:asset_id>/quick", methods=["GET", "POST"])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"), methods=["POST"])
@permission_required("inventory.view")
def quick_asset_view(asset_id):
    return _asset_detail_view(asset_id, detail_mode=False)


@inventory_bp.route("/asset/<int:asset_id>/detay", methods=["GET", "POST"])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"), methods=["POST"])
@permission_required("inventory.view")
def asset_detail(asset_id):
    return _asset_detail_view(asset_id, detail_mode=True)


def _asset_maintenance_summary(asset):
    today = get_tr_now().date()
    next_maintenance = asset.next_maintenance_date
    if not next_maintenance:
        return "Planlanmadı"
    if next_maintenance < today:
        return "Gecikmiş"
    if next_maintenance <= today + timedelta(days=15):
        return "Yaklaşan"
    return "Planlı"


def _asset_detail_view(asset_id, detail_mode=False):
    asset = _asset_scope().filter(InventoryAsset.id == asset_id).first_or_404()

    if request.method == "POST":
        if not has_permission("inventory.edit"):
            abort(403)

        quick_status = (request.form.get("status") or "").strip()
        quick_state = (request.form.get("maintenance_state") or "").strip()
        note = guvenli_metin(request.form.get("note") or "").strip()
        last_maintenance = _parse_date(request.form.get("last_maintenance_date"))

        if quick_status in {"aktif", "bakimda", "arizali", "hurda", "pasif"}:
            asset.status = quick_status
        if quick_state in {"normal", "yaklasan", "gecikmis", "ariza", "bakimda"}:
            asset.maintenance_state = quick_state
        if last_maintenance:
            asset.last_maintenance_date = last_maintenance
        if note:
            existing = (asset.notes or "").strip()
            asset.notes = f"{existing}\n{note}".strip() if existing else note

        if asset.legacy_material:
            asset.legacy_material.durum = _display_status(asset.status)
            asset.legacy_material.son_bakim_tarihi = asset.last_maintenance_date

        db.session.commit()
        log_kaydet("Saha Hızlı Güncelleme", f"Asset hızlı güncellendi: ID {asset.id} / durum={asset.status}")
        flash("Hızlı ekipman güncellemesi kaydedildi.", "success")
        target_endpoint = "inventory.asset_detail" if detail_mode else "inventory.quick_asset_view"
        return redirect(url_for(target_endpoint, asset_id=asset.id))

    related_work_orders = (
        WorkOrder.query.filter_by(asset_id=asset.id, is_deleted=False)
        .order_by(WorkOrder.opened_at.desc())
        .limit(10)
        .all()
    )
    assignment_history = (
        AssignmentItem.query.join(AssignmentRecord)
        .filter(
            AssignmentItem.asset_id == asset.id,
            AssignmentRecord.is_deleted.is_(False),
        )
        .order_by(AssignmentRecord.assignment_date.desc(), AssignmentRecord.created_at.desc())
        .limit(8)
        .all()
    )
    open_work_order = next((order for order in related_work_orders if order.status in {"acik", "atandi", "islemde", "beklemede_parca", "beklemede_onay"}), None)
    linked_box = asset.legacy_material.kutu if asset.legacy_material else None
    return render_template(
        "quick_asset_view.html",
        asset=asset,
        related_work_orders=related_work_orders,
        assignment_history=assignment_history,
        maintenance_instruction=asset.equipment_template.maintenance_instruction if asset.equipment_template else None,
        assignment_status_label=_assignment_status_label,
        qr_context=_asset_qr_context(asset),
        open_work_order=open_work_order,
        detail_mode=detail_mode,
        linked_box=linked_box,
        maintenance_summary=_asset_maintenance_summary(asset),
    )


@inventory_bp.route("/kutu/<string:kodu>")
@login_required
@permission_required("inventory.view")
def kutu_detay(kodu):
    kutu = _box_scope().filter(Kutu.kodu == kodu).first()
    if not kutu:
        flash("Biriminizde böyle bir kutu bulunamadı veya yetkiniz yok.", "danger")
        return redirect(url_for("inventory.dashboard"))

    available_materials = havalimani_filtreli_sorgu(Malzeme).filter(
        Malzeme.kutu_id != kutu.id,
    ).order_by(Malzeme.ad.asc()).limit(250).all()
    return render_template(
        "kutu_detay.html",
        kutu=kutu,
        materials=kutu.active_materials,
        available_materials=available_materials,
        qr_context=_box_qr_context(kutu),
        can_manage_box=_can_manage_box_airport(kutu.havalimani_id),
    )


@inventory_bp.route("/kutular")
@login_required
@permission_required("inventory.view")
def kutular():
    selected_airport = request.args.get("havalimani_id", type=int)
    selected_brand = guvenli_metin(request.args.get("marka") or "").strip()
    if current_user.is_sahip:
        havalimanlari = _visible_operational_airports()
    elif current_user.havalimani:
        havalimanlari = [current_user.havalimani]
    else:
        havalimanlari = []
    visible_airport_ids = {airport.id for airport in havalimanlari}
    if selected_airport and selected_airport not in visible_airport_ids:
        abort(403)

    query = _box_scope()
    if selected_airport:
        query = query.filter(Kutu.havalimani_id == selected_airport)
    if selected_brand:
        query = query.filter(Kutu.marka.ilike(f"%{selected_brand}%"))

    kutular_listesi = query.order_by(Kutu.kodu.asc()).all()
    manageable_box_ids = {box.id for box in kutular_listesi if _can_manage_box_airport(box.havalimani_id)}
    can_create_box = bool(has_permission("inventory.create") and (current_user.is_sahip or current_user.is_airport_manager))
    return render_template(
        "kutular.html",
        kutular=kutular_listesi,
        havalimanlari=havalimanlari,
        selected_airport=selected_airport,
        selected_brand=selected_brand,
        manageable_box_ids=manageable_box_ids,
        can_create_box=can_create_box,
    )


@inventory_bp.route("/kutular/yeni", methods=["POST"])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"), methods=["POST"])
@permission_required("inventory.create")
def kutu_olustur():
    if current_user.is_sahip:
        airport_id = request.form.get("havalimani_id", type=int) or current_user.havalimani_id
    else:
        airport_id = current_user.havalimani_id
    if not airport_id:
        flash("Kutu oluşturmak için geçerli bir havalimanı seçilmelidir.", "danger")
        return redirect(url_for("inventory.kutular"))
    _validate_box_write_access(airport_id)

    marka = request.form.get("marka")
    try:
        kutu = _create_box_with_generated_code(
            airport_id=airport_id,
            marka=marka,
        )
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("inventory.kutular"))

    db.session.commit()
    log_kaydet("Kutu", f"Yeni kutu oluşturuldu: {kutu.kodu}", event_key="box.create", target_model="Kutu", target_id=kutu.id)
    audit_log("box.create", outcome="success", box_id=kutu.id, airport_id=kutu.havalimani_id, box_code=kutu.kodu)
    flash(f"Yeni kutu oluşturuldu: {kutu.kodu}", "success")
    return redirect(url_for("inventory.kutu_detay", kodu=kutu.kodu))


@inventory_bp.route("/kutu/<string:kodu>/guncelle", methods=["POST"])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"), methods=["POST"])
@permission_required("inventory.edit")
def kutu_guncelle(kodu):
    kutu = _box_scope().filter(Kutu.kodu == kodu).first_or_404()
    _validate_box_write_access(kutu.havalimani_id)

    kutu.marka = guvenli_metin(request.form.get("marka") or "").strip() or None
    db.session.commit()
    log_kaydet("Kutu", f"Kutu bilgisi güncellendi: {kutu.kodu}", event_key="box.update", target_model="Kutu", target_id=kutu.id)
    audit_log("box.update", outcome="success", box_id=kutu.id, airport_id=kutu.havalimani_id)
    flash("Kutu bilgileri güncellendi.", "success")
    return redirect(url_for("inventory.kutu_detay", kodu=kutu.kodu))


@inventory_bp.route("/kutu/<string:kodu>/arsivle", methods=["POST"])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"), methods=["POST"])
@permission_required("inventory.delete")
def kutu_arsivle(kodu):
    kutu = _box_scope().filter(Kutu.kodu == kodu).first_or_404()
    _validate_box_write_access(kutu.havalimani_id)
    if kutu.active_materials:
        flash("İçinde aktif malzeme bulunan kutu arşivlenemez.", "danger")
        return redirect(url_for("inventory.kutu_detay", kodu=kodu))
    kutu.soft_delete()
    db.session.commit()
    log_kaydet("Kutu", f"Kutu arşivlendi: {kutu.kodu}", event_key="box.archive", target_model="Kutu", target_id=kutu.id)
    audit_log("box.archive", outcome="success", box_id=kutu.id, airport_id=kutu.havalimani_id)
    flash("Kutu arşive alındı.", "success")
    return redirect(url_for("inventory.kutular"))


@inventory_bp.route("/kutu/<string:kodu>/sil", methods=["POST"])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"), methods=["POST"])
@permission_required("inventory.delete")
def kutu_sil(kodu):
    kutu = _box_scope().filter(Kutu.kodu == kodu).first_or_404()
    _validate_box_write_access(kutu.havalimani_id)
    if kutu.active_materials:
        flash("İçinde aktif malzeme bulunan kutu silinemez. Önce içeriği taşıyın.", "danger")
        return redirect(url_for("inventory.kutu_detay", kodu=kodu))
    db.session.delete(kutu)
    db.session.commit()
    log_kaydet("Kutu", f"Kutu kalıcı silindi: {kodu}", event_key="box.delete", target_model="Kutu")
    audit_log("box.delete", outcome="success", box_code=kodu)
    flash("Kutu kalıcı olarak silindi.", "warning")
    return redirect(url_for("inventory.kutular"))


@inventory_bp.route("/sarf-malzemeler", methods=["GET", "POST"])
@login_required
@permission_required("inventory.view")
def consumables():
    if request.method == "POST":
        if not has_permission("inventory.edit"):
            abort(403)
        item_id = request.form.get("item_id", type=int)
        if item_id:
            item = db.session.get(ConsumableItem, item_id)
        else:
            item = ConsumableItem(
                code=guvenli_metin(request.form.get("code") or "").upper(),
                title=guvenli_metin(request.form.get("title") or ""),
                category=guvenli_metin(request.form.get("category") or ""),
                unit=guvenli_metin(request.form.get("unit") or "adet"),
                min_stock_level=float(request.form.get("min_stock_level") or 0),
                critical_level=float(request.form.get("critical_level") or 0),
                description=guvenli_metin(request.form.get("description") or ""),
                is_active=True,
            )
            db.session.add(item)
            db.session.flush()
        quantity = float(request.form.get("quantity") or 0)
        movement_type = (request.form.get("movement_type") or "in").strip()
        movement = ConsumableStockMovement(
            consumable_id=item.id,
            airport_id=current_user.havalimani_id or request.form.get("airport_id", type=int) or 1,
            kutu_id=request.form.get("kutu_id", type=int),
            movement_type=movement_type,
            quantity=abs(quantity),
            reference_note=guvenli_metin(request.form.get("reference_note") or ""),
            performed_by_id=current_user.id,
        )
        db.session.add(movement)
        db.session.commit()
        balance = _consumable_balance(item.id, movement.airport_id)
        if balance <= float(item.critical_level or 0):
            create_notification_once(current_user.id, "consumable_critical_stock", "Kritik sarf stoğu", f"{item.title} kritik stok seviyesine indi.", link_url=url_for("inventory.consumables"), severity="danger")
        elif balance <= float(item.min_stock_level or 0):
            create_notification_once(current_user.id, "consumable_low_stock", "Düşük sarf stoğu", f"{item.title} minimum stok seviyesine yaklaştı.", link_url=url_for("inventory.consumables"), severity="warning")
        log_kaydet("Sarf", f"Sarf hareketi işlendi: {item.title} / {movement_type} / {quantity}", event_key="consumable.movement", target_model="ConsumableItem", target_id=item.id)
        audit_log("consumable.movement", outcome="success", consumable_id=item.id, movement_type=movement_type, quantity=quantity)
        flash("Sarf hareketi işlendi.", "success")
        return redirect(url_for("inventory.consumables"))

    consumables_list = _consumable_scope().all() if table_exists("consumable_item") else []
    balances = {item.id: _consumable_balance(item.id, current_user.havalimani_id) if current_user.havalimani_id else 0 for item in consumables_list}
    kutular_listesi = _box_scope().order_by(Kutu.kodu.asc()).all()
    return render_template("consumables.html", consumables=consumables_list, balances=balances, kutular=kutular_listesi)


@inventory_bp.route("/kalibrasyon", methods=["GET", "POST"])
@login_required
@permission_required("maintenance.view")
def calibration_records():
    if request.method == "POST":
        if not has_permission("maintenance.edit"):
            abort(403)
        asset = _asset_scope().filter(InventoryAsset.id == request.form.get("asset_id", type=int)).first_or_404()
        schedule = CalibrationSchedule.query.filter_by(asset_id=asset.id, is_deleted=False, is_active=True).first()
        if not schedule:
            schedule = CalibrationSchedule(
                asset_id=asset.id,
                period_days=request.form.get("period_days", type=int) or 180,
                warning_days=request.form.get("warning_days", type=int) or 15,
                provider=guvenli_metin(request.form.get("provider") or ""),
                is_active=True,
                note=guvenli_metin(request.form.get("note") or ""),
            )
            db.session.add(schedule)
            db.session.flush()
        calibration_date = _parse_date(request.form.get("calibration_date")) or get_tr_now().date()
        next_calibration_date = _parse_date(request.form.get("next_calibration_date")) or (calibration_date + timedelta(days=schedule.period_days or 180))
        record = CalibrationRecord(
            asset_id=asset.id,
            calibration_schedule_id=schedule.id,
            calibration_date=calibration_date,
            next_calibration_date=next_calibration_date,
            calibrated_by_id=current_user.id,
            provider=guvenli_metin(request.form.get("provider") or schedule.provider),
            certificate_no=guvenli_metin(request.form.get("certificate_no") or ""),
            result_status=guvenli_metin(request.form.get("result_status") or "passed"),
            note=guvenli_metin(request.form.get("note") or ""),
        )
        asset.last_calibration_date = calibration_date
        asset.next_calibration_date = next_calibration_date
        db.session.add(record)
        db.session.commit()
        log_kaydet("Kalibrasyon", f"Kalibrasyon kaydı işlendi: {asset.asset_code}", event_key="calibration.record", target_model="InventoryAsset", target_id=asset.id)
        flash("Kalibrasyon kaydı kaydedildi.", "success")
        return redirect(url_for("inventory.calibration_records"))

    assets = _asset_scope().order_by(InventoryAsset.created_at.desc()).all()
    schedules = CalibrationSchedule.query.filter_by(is_deleted=False, is_active=True).all() if table_exists("calibration_schedule") else []
    records = CalibrationRecord.query.filter_by(is_deleted=False).order_by(CalibrationRecord.calibration_date.desc()).all() if table_exists("calibration_record") else []
    return render_template("calibration_records.html", assets=assets, schedules=schedules, records=records, today=get_tr_now().date())


@inventory_bp.route("/asset-lifecycle", methods=["GET", "POST"])
@login_required
@permission_required("inventory.view")
def asset_lifecycle():
    if request.method == "POST":
        if not has_permission("inventory.edit"):
            abort(403)
        asset = _asset_scope().filter(InventoryAsset.id == request.form.get("asset_id", type=int)).first_or_404()
        lifecycle_status = (request.form.get("lifecycle_status") or "active").strip()
        target_airport_id = request.form.get("target_airport_id", type=int)
        note = guvenli_metin(request.form.get("lifecycle_note") or "")
        approval_needed = lifecycle_status in {"disposed", "decommissioned", "transferred"} and not has_permission("workorder.approve")
        if approval_needed:
            payload = json.dumps({"asset_id": asset.id, "lifecycle_status": lifecycle_status, "target_airport_id": target_airport_id, "note": note}, ensure_ascii=False)
            approval = create_approval_request("asset_lifecycle", "InventoryAsset", asset.id, current_user.id, payload, commit=False)
            if approval:
                create_notification_once(current_user.id, "lifecycle_pending", "Lifecycle değişimi onay bekliyor", f"{asset.asset_code} için lifecycle değişimi onaya gönderildi.", link_url=url_for("admin.approvals"), severity="warning", commit=False)
                db.session.commit()
                flash("Lifecycle değişimi onaya gönderildi.", "warning")
                return redirect(url_for("inventory.asset_lifecycle"))

        state = _ensure_operational_state(asset)
        state.lifecycle_status = lifecycle_status
        state.lifecycle_note = note
        state.last_service_date = _parse_date(request.form.get("last_service_date")) or state.last_service_date
        state.warranty_start = _parse_date(request.form.get("warranty_start")) or state.warranty_start
        state.service_provider = guvenli_metin(request.form.get("service_provider") or state.service_provider or "")
        state.service_note = guvenli_metin(request.form.get("service_note") or state.service_note or "")
        asset.status = _lifecycle_to_status(lifecycle_status)
        if request.form.get("warranty_end"):
            asset.warranty_end_date = _parse_date(request.form.get("warranty_end"))
        if lifecycle_status == "transferred" and target_airport_id:
            asset.havalimani_id = target_airport_id
            if asset.legacy_material:
                asset.legacy_material.havalimani_id = target_airport_id
        db.session.commit()
        log_kaydet("Lifecycle", f"Lifecycle güncellendi: {asset.asset_code} -> {lifecycle_status}", event_key="asset.lifecycle.change", target_model="InventoryAsset", target_id=asset.id)
        audit_log("asset.lifecycle.change", outcome="success", asset_id=asset.id, lifecycle_status=lifecycle_status)
        flash("Lifecycle bilgisi güncellendi.", "success")
        return redirect(url_for("inventory.asset_lifecycle"))

    assets = [asset for asset in _asset_scope().order_by(InventoryAsset.created_at.desc()).all()]
    airports = _visible_operational_airports()
    return render_template("asset_lifecycle.html", assets=assets, airports=airports, lifecycle_statuses=["planned", "received", "active", "in_maintenance", "calibration_due", "out_of_service", "decommissioned", "disposed", "transferred"])


@inventory_bp.route("/kutu-bul", methods=["POST"])
@login_required
@permission_required("inventory.view")
def kutu_bul():
    kodu = request.form.get("kutu_kodu", "").strip().upper()
    if kodu:
        kutu = _box_scope().filter(Kutu.kodu == kodu).first()
        if kutu:
            return redirect(url_for("inventory.kutu_detay", kodu=kutu.kodu))
        flash(f"'{kodu}' koduna ait bir ünite bulunamadı veya erişim yetkiniz yok.", "danger")
    return redirect(url_for("inventory.dashboard"))


@inventory_bp.route("/kutu/<string:kodu>/malzeme-ekle", methods=["POST"])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
@permission_required("inventory.edit")
def kutu_malzeme_ekle(kodu):
    kutu = _box_scope().filter(Kutu.kodu == kodu).first_or_404()
    material_id = request.form.get("material_id", type=int)
    material = havalimani_filtreli_sorgu(Malzeme).filter(Malzeme.id == material_id).first()
    if not material:
        flash("Seçilen malzeme bulunamadı.", "danger")
        return redirect(url_for("inventory.kutu_detay", kodu=kutu.kodu))

    material.kutu_id = kutu.id
    material.havalimani_id = kutu.havalimani_id
    _sync_asset_location(material)
    db.session.commit()
    log_kaydet(
        "Kutu",
        f"Malzeme kutuya eklendi: {material.ad} -> {kutu.kodu}",
        event_key="box.content.add",
        target_model="Kutu",
        target_id=kutu.id,
    )
    flash("Malzeme kutuya eklendi.", "success")
    return redirect(url_for("inventory.kutu_detay", kodu=kutu.kodu))


@inventory_bp.route("/kutu/<string:kodu>/icerik-guncelle/<int:malzeme_id>", methods=["POST"])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
@permission_required("inventory.edit")
def kutu_icerik_guncelle(kodu, malzeme_id):
    kutu = _box_scope().filter(Kutu.kodu == kodu).first_or_404()
    material = Malzeme.query.filter_by(id=malzeme_id, kutu_id=kutu.id, is_deleted=False).first_or_404()
    new_quantity = _parse_positive_int(request.form.get("stok_miktari"), material.stok_miktari or 1)
    new_box_id = request.form.get("target_kutu_id", type=int)
    material.stok_miktari = new_quantity
    if new_box_id and new_box_id != kutu.id:
        target_box = _box_scope().filter(Kutu.id == new_box_id).first()
        if target_box:
            material.stok_miktari = new_quantity
            material.kutu_id = target_box.id
            material.havalimani_id = target_box.havalimani_id
            _sync_asset_location(material)
            Malzeme.query.filter_by(id=material.id).update(
                {
                    "stok_miktari": new_quantity,
                    "kutu_id": target_box.id,
                    "havalimani_id": target_box.havalimani_id,
                },
                synchronize_session=False,
            )
            db.session.commit()
            log_kaydet(
                "Kutu",
                f"Malzeme kutular arasında taşındı: {material.ad} -> {target_box.kodu}",
                event_key="box.content.move",
                target_model="Kutu",
                target_id=target_box.id,
            )
            flash("Malzeme hedef kutuya taşındı.", "success")
            return redirect(url_for("inventory.kutu_detay", kodu=target_box.kodu))

    _sync_asset_location(material)
    Malzeme.query.filter_by(id=material.id).update(
        {"stok_miktari": new_quantity},
        synchronize_session=False,
    )
    db.session.commit()
    log_kaydet(
        "Kutu",
        f"Kutu içeriği güncellendi: {material.ad} / miktar={material.stok_miktari}",
        event_key="box.content.update",
        target_model="Kutu",
        target_id=kutu.id,
    )
    flash("Kutu içeriği güncellendi.", "success")
    return redirect(url_for("inventory.kutu_detay", kodu=kutu.kodu))


@inventory_bp.route("/kutu/<string:kodu>/malzeme-cikar/<int:malzeme_id>", methods=["POST"])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
@permission_required("inventory.edit")
def kutu_malzeme_cikar(kodu, malzeme_id):
    kutu = _box_scope().filter(Kutu.kodu == kodu).first_or_404()
    material = Malzeme.query.filter_by(id=malzeme_id, kutu_id=kutu.id, is_deleted=False).first_or_404()
    fallback_box = _ensure_box(f"{kutu.havalimani.kodu}-ATANMADI", kutu.havalimani_id)
    material.kutu_id = fallback_box.id
    if material.linked_asset:
        material.linked_asset.depot_location = fallback_box.kodu
    db.session.commit()
    log_kaydet(
        "Kutu",
        f"Malzeme kutudan çıkarıldı: {material.ad} / {kutu.kodu}",
        event_key="box.content.remove",
        target_model="Kutu",
        target_id=kutu.id,
    )
    flash("Malzeme kutudan çıkarıldı.", "warning")
    return redirect(url_for("inventory.kutu_detay", kodu=kutu.kodu))


@inventory_bp.route("/qr-uret/asset/<int:asset_id>")
@login_required
@permission_required("qr.generate")
def qr_uret(asset_id):
    asset = _asset_scope().filter(InventoryAsset.id == asset_id).first_or_404()
    log_kaydet("QR", f"QR etiketi goruntulendi: {asset.asset_code}")
    audit_log("inventory.qr.render", outcome="success", asset_id=asset.id, asset_code=asset.asset_code)
    return render_template("qr_yazdir.html", asset=asset, qr_context=_asset_qr_context(asset))


@inventory_bp.route("/qr-yenile/asset/<int:asset_id>", methods=["POST"])
@login_required
@permission_required("qr.generate")
def qr_yenile(asset_id):
    asset = _asset_scope().filter(InventoryAsset.id == asset_id).first_or_404()
    payload = json.dumps(
        {"asset_id": asset.id, "requested_by_id": current_user.id},
        ensure_ascii=False,
    )
    approval = create_approval_request(
        approval_type="qr_regenerate",
        target_model="InventoryAsset",
        target_id=asset.id,
        requested_by_id=current_user.id,
        request_payload=payload,
        commit=False,
    )
    if approval:
        log_kaydet(
            "QR",
            f"QR yeniden üretim talebi açıldı: {asset.asset_code}",
            event_key="inventory.qr.regenerate.pending",
            target_model="InventoryAsset",
            target_id=asset.id,
            commit=False,
        )
        create_notification(
            current_user.id,
            "approval_pending",
            "QR yeniden üretimi onay bekliyor",
            f"{asset.asset_code} için QR yeniden üretim talebi oluşturuldu.",
            link_url=url_for("admin.approvals"),
            severity="warning",
            commit=False,
        )
        db.session.commit()
        flash("QR yeniden üretimi onaya gönderildi.", "warning")
    else:
        flash("QR yeniden üretim talebi oluşturulamadı.", "danger")
    return redirect(url_for("inventory.quick_asset_view", asset_id=asset.id))


@inventory_bp.route("/qr-uret/kutu/<int:box_id>")
@login_required
@permission_required("qr.generate")
def kutu_qr_uret(box_id):
    kutu = _box_scope().filter(Kutu.id == box_id).first_or_404()
    log_kaydet("QR", f"Kutu QR etiketi görüntülendi: {kutu.qr_code_label}", event_key="box.qr.render", target_model="Kutu", target_id=kutu.id)
    audit_log("box.qr.render", outcome="success", box_id=kutu.id, box_code=kutu.qr_code_label)
    return render_template("kutu_qr_yazdir.html", kutu=kutu, qr_context=_box_qr_context(kutu))


@inventory_bp.route("/api/qr-img/kutu/<int:box_id>")
@login_required
@permission_required("qr.generate")
def kutu_qr_img(box_id):
    kutu = _box_scope().filter(Kutu.id == box_id).first_or_404()
    img_io = generate_qr_data(kutu.qr_payload)
    return send_file(img_io, mimetype="image/png") if img_io else ("QR Hatası", 500)


@inventory_bp.route("/kutu/<string:kodu>/etiket")
@login_required
@permission_required("qr.generate")
def kutu_etiket(kodu):
    kutu = _box_scope().filter(Kutu.kodu == kodu).first_or_404()
    log_kaydet("QR", f"Kutu etiketi görüntülendi: {kutu.qr_code_label}", event_key="box.label.view", target_model="Kutu", target_id=kutu.id)
    return render_template("kutu_etiket.html", kutu=kutu, materials=kutu.active_materials, qr_context=_box_qr_context(kutu))


@inventory_bp.route("/kutu/<string:kodu>/etiket/pdf")
@login_required
@permission_required("qr.generate")
def kutu_etiket_pdf(kodu):
    kutu = _box_scope().filter(Kutu.kodu == kodu).first_or_404()
    qr_img = generate_qr_data(kutu.qr_payload)
    qr_data_uri = None
    if qr_img:
        qr_data_uri = "data:image/png;base64," + base64.b64encode(qr_img.getvalue()).decode("ascii")
    html = render_template(
        "kutu_export_pdf.html",
        kutu=kutu,
        materials=kutu.active_materials,
        qr_context=_box_qr_context(kutu),
        qr_data_uri=qr_data_uri,
    )
    output = io.BytesIO()
    pisa.CreatePDF(html, dest=output)
    output.seek(0)
    log_kaydet("Rapor", f"Kutu etiketi PDF oluşturuldu: {kutu.qr_code_label}", event_key="box.label.export", target_model="Kutu", target_id=kutu.id)
    return send_file(
        output,
        download_name=f"{kutu.qr_code_label}_etiket.pdf",
        as_attachment=True,
    )


@inventory_bp.route("/api/qr-img/asset/<int:asset_id>")
@login_required
@permission_required("qr.generate")
def qr_img(asset_id):
    asset = _asset_scope().filter(InventoryAsset.id == asset_id).first_or_404()
    img_io = generate_qr_data(_asset_qr_payload(asset))
    return send_file(img_io, mimetype="image/png") if img_io else ("QR Hatası", 500)


@inventory_bp.route("/api/qr-img/<string:kodu>")
@login_required
@permission_required("qr.generate")
def qr_img_legacy(kodu):
    normalized_code = (kodu or "").strip().upper()
    if not normalized_code:
        abort(404)

    kutu = _box_scope().filter(Kutu.kodu == normalized_code).first()
    if kutu:
        img_io = generate_qr_data(kutu.qr_payload)
        return send_file(img_io, mimetype="image/png") if img_io else ("QR Hatası", 500)

    asset = _asset_scope().filter(InventoryAsset.qr_code == normalized_code).first()
    if not asset and normalized_code.startswith("ARFF-SAR-"):
        serial = normalized_code.replace("ARFF-SAR-", "", 1)
        if serial.isdigit():
            asset = _asset_scope().filter(InventoryAsset.id == int(serial)).first()

    if not asset:
        abort(404)

    img_io = generate_qr_data(_asset_qr_payload(asset))
    return send_file(img_io, mimetype="image/png") if img_io else ("QR Hatası", 500)
