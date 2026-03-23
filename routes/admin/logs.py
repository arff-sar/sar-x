from types import SimpleNamespace

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from error_handling import get_error_spec, mask_sensitive_text
from extensions import column_exists, db
from models import IslemLog, Kullanici
from . import admin_bp
from decorators import permission_required


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
    "Kutu": "Kutu / Ünite",
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


def _build_options(values, labeler):
    cleaned_values = sorted({value for value in values if value}, key=lambda item: labeler(item).lower())
    return [{"key": value, "label": labeler(value)} for value in cleaned_values]


def _serialize_log_row(log):
    outcome_key = ((getattr(log, "outcome", None) or "legacy").strip().lower() or "legacy")
    outcome_meta = OUTCOME_META.get(outcome_key, OUTCOME_META["info"])
    target_model = getattr(log, "target_model", None)
    target_id = getattr(log, "target_id", None)

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
        zaman=log.zaman,
        user_label=log.yapan_kullanici.tam_ad if getattr(log, "yapan_kullanici", None) else "Sistem",
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
    request_id = str(getattr(log, "request_id", "") or "").strip()
    user_email = str(getattr(log, "user_email", "") or "").strip()
    actor = getattr(log, "yapan_kullanici", None)
    user_label = actor.tam_ad if actor else (user_email or "Sistem")
    summary = str(getattr(log, "user_message", None) or getattr(log, "detay", None) or "Açıklama bulunmuyor.").strip()
    module = str(getattr(log, "module", None) or "SYSTEM").strip().upper()
    severity = str(getattr(log, "severity", None) or "error").strip().lower()
    spec = get_error_spec(str(getattr(log, "error_code", "") or "SAR-X-SYSTEM-5101"))
    return SimpleNamespace(
        id=log.id,
        created_at=getattr(log, "created_at", None) or getattr(log, "zaman", None),
        status_label="Çözüldü" if getattr(log, "resolved", False) else "Açık",
        status_class="status-aktif" if getattr(log, "resolved", False) else "status-ariza",
        module=module,
        error_code=spec.error_code,
        title=str(getattr(log, "title", None) or spec.title or "Hata kaydı").strip(),
        user_message=spec.user_message if not getattr(log, "user_message", None) else str(log.user_message).strip(),
        owner_message=str(getattr(log, "owner_message", None) or spec.owner_message or "").strip(),
        possible_cause=spec.possible_cause,
        severity=severity,
        severity_label={
            "warning": "Uyarı",
            "error": "Hata",
            "critical": "Kritik",
            "info": "Bilgi",
        }.get(severity, severity.title()),
        user_label=user_label,
        user_email=user_email,
        route=str(getattr(log, "route", None) or "-").strip() or "-",
        method=str(getattr(log, "method", None) or "-").strip() or "-",
        request_id=request_id or "-",
        summary=summary,
        can_view_detail=bool(current_user.is_authenticated and current_user.is_sahip),
        detail_url=url_for("admin.hata_kaydi_detay", log_id=log.id),
    )


@admin_bp.route('/islem-loglari')
@login_required
@permission_required('logs.view')
def loglari_gor():
    has_event_key = column_exists("islem_log", "event_key")
    has_target_model = column_exists("islem_log", "target_model")
    has_target_id = column_exists("islem_log", "target_id")
    has_outcome = column_exists("islem_log", "outcome")

    user_id = request.args.get("user_id", type=int)
    event_type = (request.args.get("event_type") or "").strip()
    legacy_event_key = (request.args.get("event_key") or "").strip()
    target_model = (request.args.get("target_model") or "").strip()
    outcome = (request.args.get("outcome") or "").strip()
    date_from = (request.args.get("date_from") or "").strip()
    date_to = (request.args.get("date_to") or "").strip()
    active_filters = []

    event_type_values = [
        row[0]
        for row in IslemLog.query.with_entities(IslemLog.islem_tipi)
        .filter(IslemLog.islem_tipi.isnot(None))
        .distinct()
        .all()
    ]
    event_type_options = _build_options(event_type_values, _label_event_type)
    valid_event_types = {item["key"] for item in event_type_options}
    if event_type not in valid_event_types:
        event_type = ""

    target_model_values = []
    if has_target_model:
        target_model_values = [
            row[0]
            for row in IslemLog.query.with_entities(IslemLog.target_model)
            .filter(IslemLog.target_model.isnot(None))
            .distinct()
            .all()
        ]
    target_model_options = _build_options(target_model_values, _label_target_model)
    valid_target_models = {item["key"] for item in target_model_options}
    if target_model not in valid_target_models:
        target_model = ""

    valid_outcomes = {item["key"] for item in OUTCOME_OPTIONS}
    if outcome not in valid_outcomes:
        outcome = ""

    if has_event_key and has_target_model and has_target_id and has_outcome:
        query = IslemLog.query.order_by(IslemLog.zaman.desc())
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
            active_filters.append(
                ("Sonuç", next((item["label"] for item in OUTCOME_OPTIONS if item["key"] == outcome), outcome))
            )
        if date_from:
            query = query.filter(IslemLog.zaman >= f"{date_from} 00:00:00")
            active_filters.append(("Başlangıç", date_from))
        if date_to:
            query = query.filter(IslemLog.zaman <= f"{date_to} 23:59:59")
            active_filters.append(("Bitiş", date_to))
        raw_logs = query.limit(500).all()
    else:
        query = IslemLog.query.with_entities(
            IslemLog.id,
            IslemLog.kullanici_id,
            IslemLog.islem_tipi,
            IslemLog.detay,
            IslemLog.ip_adresi,
            IslemLog.user_agent,
            IslemLog.zaman,
        ).order_by(IslemLog.zaman.desc())
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
            for row in query.limit(500).all()
        ]
    users = Kullanici.query.filter_by(is_deleted=False).order_by(Kullanici.tam_ad.asc()).all()
    user_lookup = {user.id: user.tam_ad for user in users}
    active_filters = [
        ("Kullanıcı", user_lookup.get(user_id, "Sistem")) if key == "Kullanıcı" else (key, value)
        for key, value in active_filters
    ]

    return render_template(
        'admin/islem_loglari.html',
        loglar=[_serialize_log_row(log) for log in raw_logs],
        users=users,
        event_type_options=event_type_options,
        target_model_options=target_model_options,
        outcome_options=OUTCOME_OPTIONS,
        selected_user_id=user_id,
        selected_event_type=event_type,
        selected_target_model=target_model,
        selected_outcome=outcome,
        selected_date_from=date_from,
        selected_date_to=date_to,
        has_target_model=has_target_model and bool(target_model_options),
        has_active_filters=bool(active_filters),
        active_filters=active_filters,
        filtered_count=len(raw_logs),
    )


@admin_bp.route('/hata-kayitlari')
@login_required
@permission_required('logs.view')
def hata_kayitlari():
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
        return render_template(
            "admin/hata_kayitlari.html",
            hata_kayitlari=[],
            module_options=[],
            severity_options=[],
            selected_module="",
            selected_severity="",
            selected_status="",
            search_query="",
            has_schema_support=False,
        )

    search_query = (request.args.get("q") or "").strip()
    selected_module = (request.args.get("module") or "").strip().upper()
    selected_severity = (request.args.get("severity") or "").strip().lower()
    selected_status = (request.args.get("status") or "").strip().lower()

    query = IslemLog.query.filter(IslemLog.error_code.isnot(None)).order_by(IslemLog.zaman.desc(), IslemLog.id.desc())
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

    raw_logs = query.limit(300).all()
    module_options = [
        row[0]
        for row in IslemLog.query.with_entities(IslemLog.module)
        .filter(IslemLog.error_code.isnot(None), IslemLog.module.isnot(None))
        .distinct()
        .order_by(IslemLog.module.asc())
        .all()
    ]
    severity_options = [
        row[0]
        for row in IslemLog.query.with_entities(IslemLog.severity)
        .filter(IslemLog.error_code.isnot(None), IslemLog.severity.isnot(None))
        .distinct()
        .order_by(IslemLog.severity.asc())
        .all()
    ]

    return render_template(
        "admin/hata_kayitlari.html",
        hata_kayitlari=[_serialize_error_row(log) for log in raw_logs],
        module_options=[item for item in module_options if item],
        severity_options=[item for item in severity_options if item],
        selected_module=selected_module,
        selected_severity=selected_severity,
        selected_status=selected_status,
        search_query=search_query,
        has_schema_support=True,
    )


@admin_bp.route('/hata-kayitlari/<int:log_id>')
@login_required
@permission_required('logs.view')
def hata_kaydi_detay(log_id):
    if not current_user.is_sahip:
        abort(403)

    log = IslemLog.query.get_or_404(log_id)
    if not getattr(log, "error_code", None):
        abort(404)

    spec = get_error_spec(str(log.error_code))
    detail = SimpleNamespace(
        id=log.id,
        error_code=spec.error_code,
        title=str(getattr(log, "title", None) or spec.title or "").strip(),
        user_message=str(getattr(log, "user_message", None) or spec.user_message or "").strip(),
        owner_message=str(getattr(log, "owner_message", None) or spec.owner_message or "").strip(),
        module=str(getattr(log, "module", None) or spec.module or "").strip(),
        severity=str(getattr(log, "severity", None) or spec.severity or "").strip(),
        exception_type=str(getattr(log, "exception_type", None) or "-").strip() or "-",
        exception_message=mask_sensitive_text(getattr(log, "exception_message", None) or "-", limit=2400),
        traceback_summary=mask_sensitive_text(getattr(log, "traceback_summary", None) or "-", limit=5000),
        route=str(getattr(log, "route", None) or "-").strip() or "-",
        method=str(getattr(log, "method", None) or "-").strip() or "-",
        request_id=str(getattr(log, "request_id", None) or "-").strip() or "-",
        user_id=getattr(log, "kullanici_id", None),
        user_label=(getattr(log, "yapan_kullanici", None).tam_ad if getattr(log, "yapan_kullanici", None) else "-"),
        user_email=str(getattr(log, "user_email", None) or "-").strip() or "-",
        ip_address=str(getattr(log, "ip_address", None) or getattr(log, "ip_adresi", None) or "-").strip() or "-",
        user_agent=mask_sensitive_text(getattr(log, "user_agent", None) or "-", limit=280),
        created_at=getattr(log, "created_at", None) or getattr(log, "zaman", None),
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

    log = IslemLog.query.get_or_404(log_id)
    if not getattr(log, "error_code", None):
        abort(404)

    log.resolved = request.form.get("resolved") == "1"
    log.resolution_note = (request.form.get("resolution_note") or "").strip() or None
    db.session.commit()
    flash("Hata kaydı güncellendi.", "success")
    return redirect(url_for("admin.hata_kaydi_detay", log_id=log.id))
