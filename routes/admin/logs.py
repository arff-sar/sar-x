import io
import json
import re
from datetime import datetime
from types import SimpleNamespace
from urllib.parse import urlsplit

import pandas as pd
from flask import abort, current_app, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import joinedload

from decorators import permission_required
from error_handling import get_error_spec, mask_sensitive_text
from extensions import TR_TZ, column_exists, db, log_kaydet, table_exists
from models import ErrorReport, IslemLog, IslemLogArchive, Kullanici
from . import admin_bp


LOGS_PER_PAGE = 20
AUDIT_EXPORT_COLUMNS = ["Tarih", "Kullanıcı", "İşlem", "İlgili Kayıt", "Sonuç", "Açıklama"]
ERROR_EXPORT_COLUMNS = [
    "Durum",
    "Tarih",
    "Modül",
    "Hata Kodu",
    "Başlık",
    "Kısa Açıklama",
    "Kullanıcı",
    "Sayfa",
    "Request ID",
]
DEFAULT_ERROR_CODE = "SAR-X-SYSTEM-5101"
ERROR_CODE_RE = re.compile(r"^SAR-X-([A-Z0-9_]+)-(\d{4})$")

EVENT_TYPE_LABELS = {
    "Giriş": "Giriş",
    "Çıkış": "Çıkış",
    "Güvenlik": "Güvenlik",
    "Sistem": "Sistem",
    "Yetki": "Yetki ve Roller",
    "Rapor": "Rapor ve Dışa Aktarma",
    "Bakım": "Bakım",
    "Bakım İş Emri": "İş Emirleri",
    "Bakım Formu": "Bakım Formları",
    "Envanter": "Envanter",
    "QR": "QR ve Etiket",
    "Sarf": "Sarf Malzemesi",
    "Kalibrasyon": "Kalibrasyon",
    "Lifecycle": "Yaşam Döngüsü",
    "Yedek Parça": "Yedek Parça",
    "Parça Stok": "Parça Stoku",
    "Anasayfa İçerik": "Web İçeriği",
    "İçerik": "İçerik Yönetimi",
    "Inspection": "Saha Kontrolü",
    "Saha Hızlı Kapanış": "Saha Hızlı Kapanış",
    "Saha Hızlı Güncelleme": "Saha Hızlı Güncelleme",
    "Merkezi Şablon": "Merkezi Şablon",
    "Arşiv": "Arşiv",
    "Demo Veri": "Demo Veri",
    "Şifre Sıfırlama": "Şifre Sıfırlama",
    "Şifre Yenileme": "Şifre Yenileme",
}

TARGET_MODEL_LABELS = {
    "Kullanici": "Kullanıcı",
    "Role": "Rol",
    "Permission": "Yetki",
    "InventoryAsset": "Envanter Varlığı",
    "Kutu": "Kutu",
    "ConsumableItem": "Sarf Kalemi",
    "WorkOrder": "İş Emri",
    "MaintenancePlan": "Bakım Planı",
    "MaintenanceHistory": "Bakım Geçmişi",
    "MaintenanceFormTemplate": "Bakım Formu",
    "HomeSlider": "Slider",
    "HomeSection": "Anasayfa Bölümü",
    "Announcement": "Duyuru",
    "DocumentResource": "Doküman",
    "HomeStatCard": "Sayısal Özet Kartı",
    "HomeQuickLink": "Hızlı Bağlantı",
    "manager_summary": "Yönetici Özeti",
    "demo_seed": "Demo Veri",
}

ERROR_MODULE_LABELS = {
    "AUTH": "Kimlik Doğrulama",
    "SYSTEM": "Sistem",
    "MAIL": "E-posta",
    "DB": "Veritabanı",
    "CMS": "İçerik",
    "PUBLIC": "Açık Sayfa",
    "ADMIN": "Yönetim",
    "MEDIA": "Dosya ve Medya",
}

ERROR_SEVERITY_LABELS = {
    "warning": "Uyarı",
    "error": "Hata",
    "critical": "Kritik",
    "info": "Bilgi",
}

ROLE_LABELS = {
    "sahip": "Site sahibi",
    "yetkili": "Havalimanı yetkilisi",
    "ekip_sorumlusu": "Ekip sorumlusu",
    "ekip_uyesi": "Ekip üyesi",
    "personel": "Personel",
    "readonly": "Salt okunur kullanıcı",
}

OUTCOME_OPTIONS = [
    {"key": "success", "label": "Başarılı"},
    {"key": "failed", "label": "Başarısız"},
    {"key": "warning", "label": "Uyarı"},
    {"key": "info", "label": "Bilgi"},
    {"key": "legacy", "label": "Eski kayıt"},
]

OUTCOME_META = {
    "success": {"label": "Başarılı", "class_name": "status-aktif"},
    "failed": {"label": "Başarısız", "class_name": "status-ariza"},
    "warning": {"label": "Uyarı", "class_name": "status-bakim"},
    "info": {"label": "Bilgi", "class_name": "status-pasif"},
    "legacy": {"label": "Eski kayıt", "class_name": "status-pasif"},
}


def _label_event_type(value):
    if not value:
        return "Genel işlem"
    return EVENT_TYPE_LABELS.get(value, value)


def _label_target_model(value):
    if not value:
        return "Genel işlem"
    return TARGET_MODEL_LABELS.get(value, value)


def _label_error_module(value):
    cleaned = str(value or "").strip().upper()
    if not cleaned:
        return "Sistem"
    return ERROR_MODULE_LABELS.get(cleaned, cleaned.replace("_", " ").title())


def _label_error_severity(value):
    cleaned = str(value or "").strip().lower()
    if not cleaned:
        return "Hata"
    return ERROR_SEVERITY_LABELS.get(cleaned, cleaned.title())


def _label_role(value):
    cleaned = str(value or "").strip().lower()
    if not cleaned:
        return "Kullanıcı"
    return ROLE_LABELS.get(cleaned, cleaned.replace("_", " "))


def _build_options(values, labeler):
    cleaned_values = sorted({value for value in values if value}, key=lambda item: labeler(item).lower())
    return [{"key": value, "label": labeler(value)} for value in cleaned_values]


def _sentence(text, fallback=""):
    value = str(text or fallback or "").strip()
    if not value:
        return ""
    if value[-1] not in ".!?":
        value += "."
    return value


def _clean_error_code(value):
    return str(value or "").strip().upper()


def _extract_error_module_from_code(error_code):
    match = ERROR_CODE_RE.match(_clean_error_code(error_code))
    if not match:
        return ""
    return str(match.group(1) or "").strip().upper()


def _resolve_error_identity(log):
    raw_code = _clean_error_code(getattr(log, "error_code", None))
    spec = get_error_spec(raw_code or DEFAULT_ERROR_CODE)
    resolved_code = raw_code or _clean_error_code(spec.error_code) or DEFAULT_ERROR_CODE
    is_fallback = bool(raw_code) and resolved_code != _clean_error_code(spec.error_code)

    module = str(getattr(log, "module", None) or "").strip().upper()
    if not module:
        module = _extract_error_module_from_code(resolved_code) or str(spec.module or "SYSTEM").strip().upper() or "SYSTEM"

    severity = str(getattr(log, "severity", None) or spec.severity or "error").strip().lower() or "error"
    return SimpleNamespace(code=resolved_code, spec=spec, module=module, severity=severity, is_fallback=is_fallback)


def _normalize_http_method(value):
    cleaned = str(value or "").replace("\x00", "").strip().upper()
    if not cleaned or cleaned == "-":
        return "-"
    return cleaned[:12]


def _normalize_error_route(value):
    cleaned = str(value or "").replace("\x00", "").strip()
    if not cleaned or cleaned == "-":
        return "-"
    cleaned = " ".join(cleaned.split())
    if "://" in cleaned:
        try:
            parsed = urlsplit(cleaned)
            cleaned = parsed.path or "/"
        except Exception:
            pass
    if cleaned.startswith("/"):
        cleaned = cleaned.split("?", 1)[0].split("#", 1)[0] or "/"
    if len(cleaned) > 180:
        cleaned = f"{cleaned[:177]}..."
    return cleaned or "-"


def _normalize_request_id(value):
    cleaned = str(value or "").replace("\x00", "")
    cleaned = " ".join(cleaned.split())
    if not cleaned or cleaned == "-":
        return "-"
    return cleaned[:64]


def _compose_error_page_label(method, route):
    if method == "-" and route == "-":
        return "Sistem içi işlem"
    if route == "-":
        return f"{method} (rota bilgisi yok)" if method != "-" else "Sistem içi işlem"
    if method == "-":
        return route
    return f"{method} {route}"


def _normalize_datetime(value):
    if value is None:
        return None

    parsed = None
    if isinstance(value, datetime):
        parsed = value
    else:
        raw_value = str(value).strip()
        if not raw_value:
            return None
        normalized = raw_value.replace("Z", "+00:00")
        for parser in (
            lambda item: datetime.fromisoformat(item),
            lambda item: datetime.strptime(item, "%Y-%m-%d %H:%M:%S"),
            lambda item: datetime.strptime(item, "%Y-%m-%d %H:%M:%S.%f"),
        ):
            try:
                parsed = parser(normalized)
                break
            except Exception:
                continue
        if parsed is None:
            return None

    try:
        if parsed.tzinfo is not None:
            return parsed.astimezone(TR_TZ)
        return TR_TZ.localize(parsed)
    except Exception:
        return parsed


def _format_timestamp_label(value, empty_label="-"):
    parsed = _normalize_datetime(value)
    if parsed is not None:
        try:
            return parsed.strftime("%d.%m.%Y %H:%M:%S")
        except Exception:
            return empty_label
    raw_value = str(value or "").strip()
    return raw_value or empty_label


def _resolve_actor(log):
    actor = getattr(log, "yapan_kullanici", None)
    if actor and getattr(actor, "tam_ad", None):
        return actor

    user_id = getattr(log, "kullanici_id", None)
    if user_id is not None:
        try:
            actor = db.session.get(Kullanici, user_id)
        except Exception:
            db.session.rollback()
            actor = None
        if actor and getattr(actor, "tam_ad", None):
            return actor

    user_email = str(getattr(log, "user_email", "") or "").strip()
    if user_email:
        try:
            actor = (
                Kullanici.query.filter(func.lower(func.trim(Kullanici.kullanici_adi)) == user_email.lower())
                .order_by(Kullanici.id.asc())
                .first()
            )
        except Exception:
            db.session.rollback()
            actor = None
        if actor and getattr(actor, "tam_ad", None):
            return actor

    return None


def _resolve_actor_label(log):
    actor = _resolve_actor(log)
    if actor and getattr(actor, "tam_ad", None):
        return actor.tam_ad
    user_email = str(getattr(log, "user_email", "") or "").strip()
    return user_email or "Sistem"


def _build_error_summary(log, spec):
    actor = _resolve_actor(log)
    role_prefix = ""
    if actor and getattr(actor, "rol", None):
        role_prefix = f"{_label_role(actor.rol)} hesabında "

    route = str(getattr(log, "route", None) or "").strip().lower()
    error_code = _clean_error_code(getattr(log, "error_code", None)) or _clean_error_code(spec.error_code)
    module = str(getattr(log, "module", None) or "").strip().upper()
    if not module:
        module = _extract_error_module_from_code(error_code) or str(spec.module or "SYSTEM").strip().upper()
    safe_message = _sentence(getattr(log, "user_message", None) or spec.user_message or spec.title or "İşlem tamamlanamadı")

    summary_prefix = {
        "AUTH": "giriş, captcha veya yetki adımı tamamlanamadı",
        "DB": "veri erişimi veya kayıt işlemi tamamlanamadı",
        "MAIL": "bildirim ve e-posta akışı tamamlanamadı",
        "CMS": "içerik veya belge verisi yüklenemedi",
        "PUBLIC": "açık sayfa içeriği yüklenemedi",
        "ADMIN": "yönetim ekranı isteği işlenemedi",
        "MEDIA": "dosya yükleme veya medya doğrulaması tamamlanamadı",
        "SYSTEM": "sistem işlemi beklenen şekilde tamamlanamadı",
    }.get(module, "ilgili işlem tamamlanamadı")

    if error_code == "SAR-X-SYSTEM-5103":
        summary_prefix = "istek güvenlik sınırına takıldı"
    elif route.startswith("/login/passkey") or "passkey" in route:
        summary_prefix = "passkey giriş adımı tamamlanamadı"
    elif route.startswith("/login"):
        summary_prefix = "giriş ve güvenlik doğrulama adımı tamamlanamadı"

    lead = _sentence(f"{role_prefix}{summary_prefix}")
    if safe_message.lower() == lead.lower():
        return lead
    return f"{lead} {safe_message}".strip()


def _serialize_log_row(log):
    outcome_key = ((getattr(log, "outcome", None) or "legacy").strip().lower() or "legacy")
    outcome_meta = OUTCOME_META.get(outcome_key, OUTCOME_META["info"])
    target_model = getattr(log, "target_model", None)
    target_id = getattr(log, "target_id", None)
    event_timestamp = getattr(log, "zaman", None) or getattr(log, "created_at", None)

    if target_model:
        record_label = _label_target_model(target_model)
        record_note = f"Kayıt No: {target_id}" if target_id else "İlgili kayıt türü"
    elif outcome_key == "legacy":
        record_label = "Eski kayıt yapısı"
        record_note = "Önceki sistem kaydı"
    else:
        record_label = "Genel işlem"
        record_note = "Sistem genelinde işlendi"

    return SimpleNamespace(
        id=log.id,
        zaman=event_timestamp,
        zaman_label=_format_timestamp_label(event_timestamp, empty_label="Tarih bilgisi yok"),
        user_label=_resolve_actor_label(log),
        operation_label=_label_event_type(getattr(log, "islem_tipi", None)),
        operation_note="Önceki sistem işlemi" if outcome_key == "legacy" else "İşlem kategorisi",
        record_label=record_label,
        record_note=record_note,
        outcome_label=outcome_meta["label"],
        outcome_class=outcome_meta["class_name"],
        detail=(getattr(log, "detay", None) or "Ek açıklama bulunmuyor.").strip(),
        is_legacy=outcome_key == "legacy",
        technical_key=getattr(log, "event_key", None),
    )


def _serialize_error_row(log):
    identity = _resolve_error_identity(log)
    spec = identity.spec
    request_id = _normalize_request_id(getattr(log, "request_id", ""))
    user_email = str(getattr(log, "user_email", "") or "").strip()
    method = _normalize_http_method(getattr(log, "method", None))
    route = _normalize_error_route(getattr(log, "route", None))
    title = str(getattr(log, "title", None) or "").strip()
    if not title:
        title = "Tanımsız Hata Kaydı" if identity.is_fallback else str(spec.title or "Hata kaydı").strip()
    owner_message = str(getattr(log, "owner_message", None) or "").strip()
    if not owner_message:
        owner_message = (
            "Bu hata kodu için merkezi açıklama şablonu bulunamadı; ham kayıt bilgisi gösteriliyor."
            if identity.is_fallback
            else str(spec.owner_message or "").strip()
        )
    possible_cause = (
        "Hata kodu merkezi şablon dışında üretildi. İlgili akış için kod sözlüğü güncellenmelidir."
        if identity.is_fallback
        else spec.possible_cause
    )
    return SimpleNamespace(
        id=log.id,
        created_at=getattr(log, "created_at", None) or getattr(log, "zaman", None),
        created_at_label=_format_timestamp_label(
            getattr(log, "created_at", None) or getattr(log, "zaman", None),
            empty_label="Tarih bilgisi yok",
        ),
        status_label="Çözüldü" if getattr(log, "resolved", False) else "Açık",
        status_class="status-aktif" if getattr(log, "resolved", False) else "status-ariza",
        module=_label_error_module(identity.module),
        error_code=identity.code,
        title=title,
        user_message=spec.user_message if not getattr(log, "user_message", None) else str(log.user_message).strip(),
        owner_message=owner_message,
        possible_cause=possible_cause,
        severity=identity.severity,
        severity_label=_label_error_severity(identity.severity),
        user_label=_resolve_actor_label(log),
        user_email=user_email,
        route=route,
        method=method,
        page_label=_compose_error_page_label(method, route),
        request_id=request_id,
        summary=_build_error_summary(log, spec),
        can_view_detail=bool(current_user.is_authenticated and current_user.is_sahip),
        detail_url=url_for("admin.hata_kaydi_detay", log_id=log.id),
    )


def _serialize_error_report_row(report):
    actor = getattr(report, "user", None)
    airport = getattr(report, "havalimani", None)
    return SimpleNamespace(
        id=report.id,
        created_at_label=_format_timestamp_label(getattr(report, "created_at", None), empty_label="Tarih bilgisi yok"),
        user_label=getattr(actor, "tam_ad", None) or getattr(actor, "kullanici_adi", None) or "Bilinmiyor",
        role_label=_label_role(getattr(report, "role_key", None)),
        airport_label=getattr(airport, "ad", None) or "Tanımsız",
        path=str(getattr(report, "path", None) or "-").strip() or "-",
        error_code=str(getattr(report, "error_code", None) or "-").strip() or "-",
        request_id=str(getattr(report, "request_id", None) or "-").strip() or "-",
        summary=str(getattr(report, "error_summary", None) or "Hata bildirimi").strip(),
    )


def _serialize_audit_export_row(log):
    row = _serialize_log_row(log)
    return {
        "Tarih": row.zaman_label,
        "Kullanıcı": row.user_label,
        "İşlem": row.operation_label,
        "İlgili Kayıt": row.record_label,
        "Sonuç": row.outcome_label,
        "Açıklama": row.detail,
    }


def _serialize_error_export_row(log):
    row = _serialize_error_row(log)
    return {
        "Durum": row.status_label,
        "Tarih": row.created_at_label,
        "Modül": row.module,
        "Hata Kodu": row.error_code,
        "Başlık": row.title,
        "Kısa Açıklama": row.summary,
        "Kullanıcı": row.user_label,
        "Sayfa": row.page_label,
        "Request ID": row.request_id,
    }


def _scope_logs_query(query):
    if current_user.is_sahip:
        return query
    airport_id = getattr(current_user, "havalimani_id", None)
    query = query.outerjoin(Kullanici, IslemLog.kullanici_id == Kullanici.id)
    return query.filter(
        or_(
            IslemLog.havalimani_id == airport_id,
            and_(
                IslemLog.havalimani_id.is_(None),
                Kullanici.havalimani_id == airport_id,
            ),
        )
    )


def _scoped_log_option_query(column):
    return _scope_logs_query(IslemLog.query.with_entities(column)).filter(column.isnot(None))


def _parse_page_arg(raw_value):
    try:
        page = int(raw_value)
    except (TypeError, ValueError):
        return 1
    return page if page > 0 else 1


def _count_query_rows(query):
    return query.order_by(None).count()


def _paginate_query(query, page, per_page=LOGS_PER_PAGE):
    total_count = _count_query_rows(query)
    total_pages = max(((total_count - 1) // per_page) + 1, 1) if total_count else 1
    page = min(page, total_pages)
    if total_count == 0:
        return [], 0, page, total_pages
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    return items, total_count, page, total_pages


def _query_args_without(*excluded_keys):
    excluded = set(excluded_keys)
    payload = {}
    for key in request.args:
        if key in excluded:
            continue
        value = request.args.get(key)
        if value in (None, ""):
            continue
        payload[key] = value
    return payload


def _build_pagination(endpoint, page, total_pages, params):
    def _page_url(target_page):
        payload = dict(params)
        if target_page > 1:
            payload["page"] = target_page
        else:
            payload.pop("page", None)
        return url_for(endpoint, **payload)

    start_page = max(1, page - 2)
    end_page = min(total_pages, page + 2)
    items = [
        SimpleNamespace(number=page_number, url=_page_url(page_number), is_current=(page_number == page))
        for page_number in range(start_page, end_page + 1)
    ]
    return SimpleNamespace(
        page=page,
        total_pages=total_pages,
        has_prev=page > 1,
        has_next=page < total_pages,
        prev_url=_page_url(page - 1) if page > 1 else None,
        next_url=_page_url(page + 1) if page < total_pages else None,
        items=items,
    )


def _prepare_audit_log_listing():
    has_event_key = column_exists("islem_log", "event_key")
    has_target_model = column_exists("islem_log", "target_model")
    has_target_id = column_exists("islem_log", "target_id")
    has_outcome = column_exists("islem_log", "outcome")

    page = _parse_page_arg(request.args.get("page"))
    user_id = request.args.get("user_id", type=int)
    event_type = (request.args.get("event_type") or "").strip()
    legacy_event_key = (request.args.get("event_key") or "").strip()
    target_model = (request.args.get("target_model") or "").strip()
    outcome = (request.args.get("outcome") or "").strip()
    date_from = (request.args.get("date_from") or "").strip()
    date_to = (request.args.get("date_to") or "").strip()
    active_filters = []

    event_type_values = [row[0] for row in _scoped_log_option_query(IslemLog.islem_tipi).distinct().all()]
    event_type_options = _build_options(event_type_values, _label_event_type)
    valid_event_types = {item["key"] for item in event_type_options}
    if event_type not in valid_event_types:
        event_type = ""

    target_model_values = []
    if has_target_model:
        target_model_values = [row[0] for row in _scoped_log_option_query(IslemLog.target_model).distinct().all()]
    target_model_options = _build_options(target_model_values, _label_target_model)
    valid_target_models = {item["key"] for item in target_model_options}
    if target_model not in valid_target_models:
        target_model = ""

    valid_outcomes = {item["key"] for item in OUTCOME_OPTIONS}
    if outcome not in valid_outcomes:
        outcome = ""

    if has_event_key and has_target_model and has_target_id and has_outcome:
        query = _scope_logs_query(IslemLog.query.options(joinedload(IslemLog.yapan_kullanici))).order_by(
            IslemLog.zaman.desc(), IslemLog.id.desc()
        )
        if user_id:
            query = query.filter_by(kullanici_id=user_id)
            active_filters.append(("Kullanıcı", str(user_id)))
        if event_type:
            query = query.filter(IslemLog.islem_tipi == event_type)
            active_filters.append(("Olay Tipi", _label_event_type(event_type)))
        if legacy_event_key:
            query = query.filter(IslemLog.event_key.ilike(f"%{legacy_event_key}%"))
            active_filters.append(("İşlem anahtarı", legacy_event_key))
        if target_model:
            query = query.filter(IslemLog.target_model == target_model)
            active_filters.append(("İlgili Kayıt Türü", _label_target_model(target_model)))
        if outcome:
            query = query.filter(IslemLog.outcome == outcome)
            active_filters.append(("Sonuç", next((item["label"] for item in OUTCOME_OPTIONS if item["key"] == outcome), outcome)))
        if date_from:
            query = query.filter(IslemLog.zaman >= f"{date_from} 00:00:00")
            active_filters.append(("Başlangıç", date_from))
        if date_to:
            query = query.filter(IslemLog.zaman <= f"{date_to} 23:59:59")
            active_filters.append(("Bitiş", date_to))
    else:
        query = _scope_logs_query(
            IslemLog.query.with_entities(
                IslemLog.id,
                IslemLog.kullanici_id,
                IslemLog.islem_tipi,
                IslemLog.detay,
                IslemLog.ip_adresi,
                IslemLog.user_agent,
                IslemLog.zaman,
            )
        ).order_by(IslemLog.zaman.desc(), IslemLog.id.desc())
        if user_id:
            query = query.filter(IslemLog.kullanici_id == user_id)
            active_filters.append(("Kullanıcı", str(user_id)))
        if event_type:
            query = query.filter(IslemLog.islem_tipi == event_type)
            active_filters.append(("Olay Tipi", _label_event_type(event_type)))
        if date_from:
            query = query.filter(IslemLog.zaman >= f"{date_from} 00:00:00")
            active_filters.append(("Başlangıç", date_from))
        if date_to:
            query = query.filter(IslemLog.zaman <= f"{date_to} 23:59:59")
            active_filters.append(("Bitiş", date_to))

    users_query = Kullanici.query.filter_by(is_deleted=False)
    if not current_user.is_sahip:
        users_query = users_query.filter(Kullanici.havalimani_id == getattr(current_user, "havalimani_id", None))
    users = users_query.order_by(Kullanici.tam_ad.asc()).all()
    user_lookup = {user.id: user.tam_ad for user in users}
    active_filters = [
        ("Kullanıcı", user_lookup.get(user_id, "Sistem")) if key == "Kullanıcı" else (key, value)
        for key, value in active_filters
    ]

    return SimpleNamespace(
        query=query,
        users=users,
        event_type_options=event_type_options,
        target_model_options=target_model_options,
        selected_user_id=user_id,
        selected_event_type=event_type,
        selected_target_model=target_model,
        selected_outcome=outcome,
        selected_date_from=date_from,
        selected_date_to=date_to,
        has_target_model=has_target_model and bool(target_model_options),
        has_active_filters=bool(active_filters),
        active_filters=active_filters,
        page=page,
        export_query=_query_args_without("page"),
        clear_url=url_for("admin.loglari_gor"),
    )


def _load_error_log_listing_data(search_query, selected_module, selected_severity, selected_status):
    module_values = [
        row[0]
        for row in IslemLog.query.with_entities(IslemLog.module)
        .filter(IslemLog.error_code.isnot(None), IslemLog.module.isnot(None))
        .distinct()
        .order_by(IslemLog.module.asc())
        .all()
    ]
    severity_values = [
        row[0]
        for row in IslemLog.query.with_entities(IslemLog.severity)
        .filter(IslemLog.error_code.isnot(None), IslemLog.severity.isnot(None))
        .distinct()
        .order_by(IslemLog.severity.asc())
        .all()
    ]
    module_options = _build_options(module_values, _label_error_module)
    severity_options = _build_options(severity_values, _label_error_severity)

    valid_modules = {item["key"] for item in module_options}
    valid_severities = {item["key"] for item in severity_options}
    if selected_module not in valid_modules:
        selected_module = ""
    if selected_severity not in valid_severities:
        selected_severity = ""
    if selected_status not in {"", "open", "resolved"}:
        selected_status = ""

    query = (
        IslemLog.query.options(joinedload(IslemLog.yapan_kullanici))
        .filter(IslemLog.error_code.isnot(None))
        .order_by(IslemLog.zaman.desc(), IslemLog.id.desc())
    )
    if search_query:
        like_value = f"%{search_query}%"
        query = query.filter(
            or_(
                IslemLog.error_code.ilike(like_value),
                IslemLog.title.ilike(like_value),
                IslemLog.user_message.ilike(like_value),
                IslemLog.request_id.ilike(like_value),
                IslemLog.route.ilike(like_value),
            )
        )
    if selected_module:
        query = query.filter(IslemLog.module == selected_module)
    if selected_severity:
        query = query.filter(IslemLog.severity == selected_severity)
    if selected_status == "resolved":
        query = query.filter(IslemLog.resolved.is_(True))
    elif selected_status == "open":
        query = query.filter(IslemLog.resolved.is_(False))

    return query, module_options, severity_options, selected_module, selected_severity, selected_status


def _prepare_error_log_listing():
    required_columns = (
        "error_code",
        "title",
        "user_message",
        "module",
        "severity",
        "request_id",
        "resolved",
    )
    if any(not column_exists("islem_log", column_name) for column_name in required_columns):
        return SimpleNamespace(
            has_schema_support=False,
            hata_kayitlari=[],
            module_options=[],
            severity_options=[],
            selected_module="",
            selected_severity="",
            selected_status="",
            search_query="",
            has_active_filters=False,
            page=1,
            clear_url=url_for("admin.hata_kayitlari"),
            export_query={},
            query=None,
        )

    search_query = (request.args.get("q") or "").strip()
    selected_module = (request.args.get("module") or "").strip().upper()
    selected_severity = (request.args.get("severity") or "").strip().lower()
    selected_status = (request.args.get("status") or "").strip().lower()
    page = _parse_page_arg(request.args.get("page"))

    query, module_options, severity_options, selected_module, selected_severity, selected_status = _load_error_log_listing_data(
        search_query,
        selected_module,
        selected_severity,
        selected_status,
    )

    return SimpleNamespace(
        has_schema_support=True,
        query=query,
        module_options=module_options,
        severity_options=severity_options,
        selected_module=selected_module,
        selected_severity=selected_severity,
        selected_status=selected_status,
        search_query=search_query,
        has_active_filters=bool(search_query or selected_module or selected_severity or selected_status),
        page=page,
        clear_url=url_for("admin.hata_kayitlari"),
        export_query=_query_args_without("page"),
    )


def _prepare_error_report_listing():
    if not table_exists("error_report"):
        return SimpleNamespace(rows=[], pagination=_build_pagination("admin.hata_kayitlari", 1, 1, _query_args_without("report_page")))

    report_page = _parse_page_arg(request.args.get("report_page"))
    query = (
        ErrorReport.query.options(joinedload(ErrorReport.user), joinedload(ErrorReport.havalimani))
        .order_by(ErrorReport.created_at.desc(), ErrorReport.id.desc())
    )
    rows, _, page, total_pages = _paginate_query(query, report_page)
    pagination = _build_pagination("admin.hata_kayitlari", page, total_pages, _query_args_without("report_page"))
    return SimpleNamespace(rows=[_serialize_error_report_row(row) for row in rows], pagination=pagination)


def _archive_payload(log):
    return {
        "source_log_id": log.id,
        "kullanici_id": log.kullanici_id,
        "havalimani_id": log.havalimani_id,
        "islem_tipi": log.islem_tipi,
        "event_key": getattr(log, "event_key", None),
        "detay": log.detay,
        "target_model": getattr(log, "target_model", None),
        "target_id": getattr(log, "target_id", None),
        "outcome": getattr(log, "outcome", None),
        "error_code": getattr(log, "error_code", None),
        "title": getattr(log, "title", None),
        "user_message": getattr(log, "user_message", None),
        "owner_message": getattr(log, "owner_message", None),
        "module": getattr(log, "module", None),
        "severity": getattr(log, "severity", None),
        "exception_type": getattr(log, "exception_type", None),
        "exception_message": getattr(log, "exception_message", None),
        "traceback_summary": getattr(log, "traceback_summary", None),
        "route": getattr(log, "route", None),
        "method": getattr(log, "method", None),
        "request_id": getattr(log, "request_id", None),
        "user_email": getattr(log, "user_email", None),
        "resolved": getattr(log, "resolved", False),
        "resolution_note": getattr(log, "resolution_note", None),
        "ip_adresi": getattr(log, "ip_adresi", None),
        "user_agent": getattr(log, "user_agent", None),
        "ip_address": getattr(log, "ip_address", None),
        "zaman": _format_timestamp_label(getattr(log, "zaman", None)),
    }


def _archive_and_delete_logs(scope):
    if not current_user.is_sahip:
        abort(403)
    if not table_exists("islem_log_archive"):
        flash("Arşiv tablosu hazır olmadığı için temizlik yapılamadı.", "danger")
        return False

    confirmation = (request.form.get("cleanup_confirmation") or "").strip().upper()
    if confirmation != "ONAYLA":
        flash("Temizlik için onay alanına ONAYLA yazın.", "warning")
        return False

    query = IslemLog.query
    if scope == "audit":
        query = query.filter(IslemLog.error_code.is_(None))
    else:
        query = query.filter(IslemLog.error_code.isnot(None))

    rows = query.order_by(IslemLog.id.asc()).all()
    if not rows:
        flash("Temizlenecek kayıt bulunamadı.", "info")
        return False

    archive_rows = [
        IslemLogArchive(
            source_log_id=row.id,
            archive_scope=scope,
            payload_json=json.dumps(_archive_payload(row), ensure_ascii=False),
            archived_by_user_id=current_user.id,
        )
        for row in rows
    ]
    try:
        db.session.add_all(archive_rows)
        for row in rows:
            db.session.delete(row)
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash("Kayıtlar yedeklenemediği için silme yapılmadı.", "danger")
        return False

    cleaned_label = "işlem kayıtları" if scope == "audit" else "hata kayıtları"
    log_kaydet(
        "Arşiv",
        f"{len(rows)} {cleaned_label} yedeklenip temizlendi.",
        event_key=f"logs.{scope}.archive_cleanup",
        target_model="IslemLog",
        outcome="success",
    )
    flash(f"{len(rows)} {cleaned_label} yedeklenip temizlendi.", "success")
    return True


def _write_excel_response(rows, columns, filename_prefix):
    frame = pd.DataFrame(rows, columns=columns)
    payload = io.BytesIO()
    with pd.ExcelWriter(payload, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False)
    payload.seek(0)
    return send_file(
        payload,
        as_attachment=True,
        download_name=f"{filename_prefix}_{datetime.now(TR_TZ).strftime('%Y%m%d_%H%M')}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@admin_bp.route('/islem-loglari')
@login_required
@permission_required('logs.view')
def loglari_gor():
    state = _prepare_audit_log_listing()
    raw_logs, filtered_count, page, total_pages = _paginate_query(state.query, state.page)
    pagination = _build_pagination("admin.loglari_gor", page, total_pages, state.export_query)

    if state.has_target_model:
        raw_logs = raw_logs
    else:
        raw_logs = [
            SimpleNamespace(
                id=row.id,
                kullanici_id=row.kullanici_id,
                islem_tipi=row.islem_tipi,
                detay=row.detay,
                ip_adresi=row.ip_adresi,
                user_agent=row.user_agent,
                zaman=row.zaman,
                event_key=None,
                target_model=None,
                target_id=None,
                outcome="legacy",
            )
            for row in raw_logs
        ]

    return render_template(
        'admin/islem_loglari.html',
        loglar=[_serialize_log_row(log) for log in raw_logs],
        users=state.users,
        event_type_options=state.event_type_options,
        target_model_options=state.target_model_options,
        outcome_options=OUTCOME_OPTIONS,
        selected_user_id=state.selected_user_id,
        selected_event_type=state.selected_event_type,
        selected_target_model=state.selected_target_model,
        selected_outcome=state.selected_outcome,
        selected_date_from=state.selected_date_from,
        selected_date_to=state.selected_date_to,
        has_target_model=state.has_target_model,
        has_active_filters=state.has_active_filters,
        active_filters=state.active_filters,
        filtered_count=filtered_count,
        pagination=pagination,
        export_query=state.export_query,
        clear_url=state.clear_url,
        can_cleanup=current_user.is_sahip,
    )


@admin_bp.route('/islem-loglari/excel')
@login_required
@permission_required('logs.view')
def loglari_excel():
    state = _prepare_audit_log_listing()
    limit = int(current_app.config.get("MAX_EXPORT_ROWS", 10000))
    total_count = _count_query_rows(state.query)
    if total_count > limit:
        abort(413)

    raw_logs = state.query.limit(limit).all()
    if not state.has_target_model:
        raw_logs = [
            SimpleNamespace(
                id=row.id,
                kullanici_id=row.kullanici_id,
                islem_tipi=row.islem_tipi,
                detay=row.detay,
                ip_adresi=row.ip_adresi,
                user_agent=row.user_agent,
                zaman=row.zaman,
                event_key=None,
                target_model=None,
                target_id=None,
                outcome="legacy",
            )
            for row in raw_logs
        ]

    log_kaydet("Rapor", f"İşlem kayıtları Excel dışa aktarıldı ({current_user.rol})")
    return _write_excel_response([_serialize_audit_export_row(log) for log in raw_logs], AUDIT_EXPORT_COLUMNS, "islem_kayitlari")


@admin_bp.route('/hata-kayitlari')
@login_required
@permission_required('logs.view')
def hata_kayitlari():
    if not current_user.is_sahip:
        abort(403)

    try:
        state = _prepare_error_log_listing()
        report_state = _prepare_error_report_listing()
        if not state.has_schema_support:
            pagination = _build_pagination("admin.hata_kayitlari", 1, 1, {})
            return render_template(
                "admin/hata_kayitlari.html",
                hata_kayitlari=[],
                error_reports=report_state.rows,
                report_pagination=report_state.pagination,
                module_options=[],
                severity_options=[],
                selected_module="",
                selected_severity="",
                selected_status="",
                search_query="",
                has_schema_support=False,
                has_active_filters=False,
                pagination=pagination,
                export_query={},
                clear_url=url_for("admin.hata_kayitlari"),
                can_cleanup=current_user.is_sahip,
            )

        raw_logs, _, page, total_pages = _paginate_query(state.query, state.page)
        pagination = _build_pagination("admin.hata_kayitlari", page, total_pages, state.export_query)
    except Exception:
        db.session.rollback()
        state = SimpleNamespace(
            has_schema_support=True,
            module_options=[],
            severity_options=[],
            selected_module="",
            selected_severity="",
            selected_status="",
            search_query="",
            has_active_filters=False,
            export_query={},
            clear_url=url_for("admin.hata_kayitlari"),
        )
        raw_logs = []
        pagination = _build_pagination("admin.hata_kayitlari", 1, 1, {})
        report_state = SimpleNamespace(rows=[], pagination=_build_pagination("admin.hata_kayitlari", 1, 1, {}))

    return render_template(
        "admin/hata_kayitlari.html",
        hata_kayitlari=[_serialize_error_row(log) for log in raw_logs],
        error_reports=report_state.rows,
        report_pagination=report_state.pagination,
        module_options=state.module_options,
        severity_options=state.severity_options,
        selected_module=state.selected_module,
        selected_severity=state.selected_severity,
        selected_status=state.selected_status,
        search_query=state.search_query,
        has_schema_support=True,
        has_active_filters=state.has_active_filters,
        pagination=pagination,
        export_query=state.export_query,
        clear_url=state.clear_url,
        can_cleanup=current_user.is_sahip,
    )


@admin_bp.route('/hata-kayitlari/excel')
@login_required
@permission_required('logs.view')
def hata_kayitlari_excel():
    if not current_user.is_sahip:
        abort(403)

    state = _prepare_error_log_listing()
    if not state.has_schema_support:
        flash("Hata kayıtları dışa aktarma için hazır değil.", "warning")
        return redirect(url_for("admin.hata_kayitlari"))

    limit = int(current_app.config.get("MAX_EXPORT_ROWS", 10000))
    total_count = _count_query_rows(state.query)
    if total_count > limit:
        abort(413)

    raw_logs = state.query.limit(limit).all()
    log_kaydet("Rapor", "Hata kayıtları Excel dışa aktarıldı")
    return _write_excel_response([_serialize_error_export_row(log) for log in raw_logs], ERROR_EXPORT_COLUMNS, "hata_kayitlari")


@admin_bp.route('/hata-kayitlari/<int:log_id>')
@login_required
@permission_required('logs.view')
def hata_kaydi_detay(log_id):
    if not current_user.is_sahip:
        abort(403)

    log = db.get_or_404(IslemLog, log_id)
    if not getattr(log, "error_code", None):
        abort(404)

    identity = _resolve_error_identity(log)
    spec = identity.spec
    method = _normalize_http_method(getattr(log, "method", None))
    route = _normalize_error_route(getattr(log, "route", None))
    request_id = _normalize_request_id(getattr(log, "request_id", None))
    title = str(getattr(log, "title", None) or "").strip()
    if not title:
        title = "Tanımsız Hata Kaydı" if identity.is_fallback else str(spec.title or "").strip()
    detail = SimpleNamespace(
        id=log.id,
        error_code=identity.code,
        title=title,
        user_message=str(getattr(log, "user_message", None) or spec.user_message or "").strip(),
        owner_message=str(getattr(log, "owner_message", None) or spec.owner_message or "").strip(),
        module=_label_error_module(identity.module),
        severity=_label_error_severity(identity.severity),
        exception_type=str(getattr(log, "exception_type", None) or "-").strip() or "-",
        exception_message=mask_sensitive_text(getattr(log, "exception_message", None) or "-", limit=2400),
        traceback_summary=mask_sensitive_text(getattr(log, "traceback_summary", None) or "-", limit=5000),
        route=route,
        method=method,
        page_label=_compose_error_page_label(method, route),
        request_id=request_id,
        user_id=getattr(log, "kullanici_id", None),
        user_label=(getattr(log, "yapan_kullanici", None).tam_ad if getattr(log, "yapan_kullanici", None) else "-"),
        user_email=str(getattr(log, "user_email", None) or "-").strip() or "-",
        ip_address=str(getattr(log, "ip_address", None) or getattr(log, "ip_adresi", None) or "-").strip() or "-",
        user_agent=mask_sensitive_text(getattr(log, "user_agent", None) or "-", limit=280),
        created_at=getattr(log, "created_at", None) or getattr(log, "zaman", None),
        created_at_label=_format_timestamp_label(
            getattr(log, "created_at", None) or getattr(log, "zaman", None),
            empty_label="Tarih bilgisi yok",
        ),
        resolved=bool(getattr(log, "resolved", False)),
        resolution_note=str(getattr(log, "resolution_note", None) or "").strip(),
    )
    return render_template("admin/hata_kaydi_detay.html", kayit=detail)


@admin_bp.route('/hata-kayitlari/<int:log_id>/durum', methods=['POST'])
@login_required
@permission_required('logs.view')
def hata_kaydi_durum(log_id):
    if not current_user.is_sahip:
        abort(403)

    log = db.get_or_404(IslemLog, log_id)
    if not getattr(log, "error_code", None):
        abort(404)

    log.resolved = request.form.get("resolved") == "1"
    log.resolution_note = (request.form.get("resolution_note") or "").strip() or None
    db.session.commit()
    flash("Hata kaydı güncellendi.", "success")
    return redirect(url_for("admin.hata_kaydi_detay", log_id=log.id))


@admin_bp.route('/islem-loglari/arsivle-temizle', methods=['POST'])
@login_required
@permission_required('logs.view')
def loglari_arsivle_temizle():
    _archive_and_delete_logs("audit")
    return redirect(url_for("admin.loglari_gor"))


@admin_bp.route('/hata-kayitlari/arsivle-temizle', methods=['POST'])
@login_required
@permission_required('logs.view')
def hata_kayitlarini_arsivle_temizle():
    _archive_and_delete_logs("error")
    return redirect(url_for("admin.hata_kayitlari"))
