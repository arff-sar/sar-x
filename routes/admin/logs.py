from types import SimpleNamespace

from flask import render_template, request
from flask_login import login_required
from sqlalchemy import func

from extensions import column_exists
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
        .order_by(func.lower(IslemLog.islem_tipi).asc())
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
            .order_by(func.lower(IslemLog.target_model).asc())
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
