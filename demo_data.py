import random
import json
import re
from html import unescape
from pathlib import Path
from datetime import timedelta

from flask import current_app, g, has_request_context
from sqlalchemy import false, inspect, or_, text
from sqlalchemy.exc import SQLAlchemyError

from decorators import ROLE_ADMIN, ROLE_AIRPORT_MANAGER, ROLE_EDITOR, ROLE_MAINTENANCE, ROLE_MANAGER, ROLE_OWNER, ROLE_PERSONNEL, ROLE_READONLY, ROLE_WAREHOUSE
from extensions import column_exists, db, log_kaydet, table_exists
from models import (
    AssetOperationalState,
    AssignmentHistoryEntry,
    AssignmentItem,
    AssignmentRecipient,
    AssignmentRecord,
    CalibrationRecord,
    CalibrationSchedule,
    ConsumableItem,
    ConsumableStockMovement,
    DemoSeedRecord,
    EquipmentTemplate,
    Havalimani,
    InventoryAsset,
    Kutu,
    Kullanici,
    MaintenanceFormField,
    MaintenanceFormTemplate,
    MaintenanceInstruction,
    MaintenancePlan,
    MaintenanceTriggerRule,
    Malzeme,
    MeterDefinition,
    PPEAssignmentItem,
    PPEAssignmentRecord,
    PPERecord,
    PPERecordEvent,
    SiteAyarlari,
    AssetSparePartLink,
    SparePart,
    SparePartStock,
    Supplier,
    WorkOrder,
    WorkOrderPartUsage,
    get_tr_now,
)

DEMO_SEED_TAG = "demo_seed"
DEMO_PASSWORD = "Demo.SARx.2026!"
PLATFORM_DEMO_STATE_KEY = "platform_demo_state"
AIRPORTS = [
    ("Erzurum Havalimanı", "ERZ"),
    ("Balıkesir Koca Seyit Havalimanı", "EDO"),
    ("Kocaeli Cengiz Topel Havalimanı", "KCO"),
]
AIRPORT_PERSONNEL_COUNT = 20
USAR_HTML_CANDIDATES = [
    Path("/Users/mehmetcinocevi/Downloads/usar_envanter_tablo_html.html"),
]
USAR_HTML_MAX_BYTES = 2 * 1024 * 1024
USAR_FALLBACK_ROWS = [
    {
        "category": "Kentsel Arama/Kurtarma",
        "name": "Gaz Ölçüm Cihazı",
        "brand": "Dräger",
        "model": "X-am 2500",
        "quantity": 1,
        "function": "Çoklu gaz tespiti ve kapalı alan atmosfer güvenliği",
        "manual_url": "https://www.draeger.com/Content/Documents/Products/x-am-2500-ifu-9033366-en.pdf",
    },
    {
        "category": "Kentsel Arama/Kurtarma",
        "name": "Radyasyon Ölçüm Cihazı",
        "brand": "TENMAK",
        "model": "NEB 250 D1",
        "quantity": 1,
        "function": "Radyasyon ölçümü ile güvenli alan tayini",
        "manual_url": "https://www.thermofisher.com/order/catalog/product/4250670#/4250670",
    },
    {
        "category": "Kentsel Arama/Kurtarma",
        "name": "GPS Cihazı",
        "brand": "Garmin",
        "model": "Montana 760i",
        "quantity": 1,
        "function": "Saha koordinasyonunda konum/navigasyon desteği",
        "manual_url": "https://support.garmin.com/en-GB/?partNumber=010-02964-11&tab=manuals",
    },
    {
        "category": "Kentsel Arama/Kurtarma",
        "name": "Sismik Dinleme Seti",
        "brand": "Scorpe",
        "model": "ASB10",
        "quantity": 1,
        "function": "Enkaz altında ses/titreşim ile canlı tespiti",
        "manual_url": "https://scorpe.net/download/",
    },
    {
        "category": "Kentsel Arama/Kurtarma",
        "name": "Görüntüleme Cihazı",
        "brand": "Scorpe",
        "model": "BVA7",
        "quantity": 1,
        "function": "Dar boşluklarda fiber optik görüntüleme",
        "manual_url": "https://scorpe.net/app/uploads/2025/03/EN-Manuel-Vibrascope%C2%AE-BVA7.pdf",
    },
]


def demo_tools_enabled():
    if not current_app.config.get("DEMO_TOOLS_ENABLED", False):
        return False
    return str(current_app.config.get("ENV") or "").strip().lower() != "production"


def _guard_demo_tools():
    if not demo_tools_enabled():
        raise RuntimeError("Demo veri araçları bu ortamda kapalı.")
    if not table_exists("demo_seed_record"):
        if current_app.config.get("AUTO_CREATE_TABLES", False):
            db.create_all()
        else:
            raise RuntimeError("Demo seed tablosu eksik. Önce migration çalıştırın.")


def _ensure_demo_ppe_schema_ready():
    missing_parts = []
    if not table_exists("ppe_record"):
        missing_parts.append("ppe_record tablosu")
    elif not column_exists("ppe_record", "ppe_assignment_id"):
        missing_parts.append("ppe_record.ppe_assignment_id kolonu")
    if not table_exists("ppe_assignment_record"):
        missing_parts.append("ppe_assignment_record tablosu")
    if not table_exists("ppe_assignment_item"):
        missing_parts.append("ppe_assignment_item tablosu")

    if not missing_parts:
        return
    detail = ", ".join(missing_parts)
    raise RuntimeError(
        f"KKD demo şeması güncel değil ({detail}). Lütfen `flask db upgrade` çalıştırın."
    )


def _register_record(instance, label=None):
    existing = DemoSeedRecord.query.filter_by(
        seed_tag=DEMO_SEED_TAG,
        model_name=instance.__class__.__name__,
        record_id=instance.id,
    ).first()
    if existing:
        return existing
    row = DemoSeedRecord(
        seed_tag=DEMO_SEED_TAG,
        model_name=instance.__class__.__name__,
        record_id=instance.id,
        record_label=label,
    )
    db.session.add(row)
    return row


def _summary():
    return {
        "havalimani": DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG, model_name="Havalimani").count(),
        "kullanici": DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG, model_name="Kullanici").count(),
        "ekipman_sablonu": DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG, model_name="EquipmentTemplate").count(),
        "asset": DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG, model_name="InventoryAsset").count(),
        "kutu": DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG, model_name="Kutu").count(),
        "bakim_formu": DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG, model_name="MaintenanceFormTemplate").count(),
        "bakim_plani": DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG, model_name="MaintenancePlan").count(),
        "is_emri": DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG, model_name="WorkOrder").count(),
        "yedek_parca": DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG, model_name="SparePart").count(),
        "operasyon_durumu": DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG, model_name="AssetOperationalState").count(),
        "bakim_talimati": DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG, model_name="MaintenanceInstruction").count(),
        "kkd": DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG, model_name="PPERecord").count(),
        "kkd_olay": DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG, model_name="PPERecordEvent").count(),
        "kkd_tahsis": DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG, model_name="PPEAssignmentRecord").count(),
        "kkd_tahsis_kalem": DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG, model_name="PPEAssignmentItem").count(),
    }


def format_demo_summary(summary):
    return "\n".join(
        [
            f"Havalimanı: {summary['havalimani']}",
            f"Kullanıcı: {summary['kullanici']}",
            f"Ekipman Şablonu: {summary['ekipman_sablonu']}",
            f"Asset: {summary['asset']}",
            f"Kutu/Ünite: {summary['kutu']}",
            f"Bakım Formu: {summary['bakim_formu']}",
            f"Bakım Planı: {summary['bakim_plani']}",
            f"İş Emri: {summary['is_emri']}",
            f"Yedek Parça: {summary['yedek_parca']}",
            f"Operasyon Durumu: {summary['operasyon_durumu']}",
            f"Bakım Talimatı: {summary['bakim_talimati']}",
            f"KKD Kaydı: {summary['kkd']}",
            f"KKD Olayı: {summary['kkd_olay']}",
            f"KKD Tahsis: {summary['kkd_tahsis']}",
            f"KKD Tahsis Kalemi: {summary['kkd_tahsis_kalem']}",
        ]
    )


def _load_site_meta(ayarlar):
    if not ayarlar or not ayarlar.iletisim_notu:
        return {}
    try:
        parsed = json.loads(ayarlar.iletisim_notu)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        legacy = str(ayarlar.iletisim_notu).strip()
        return {"site_notu": legacy} if legacy else {}


def _save_site_meta(ayarlar, meta):
    ayarlar.iletisim_notu = json.dumps(meta, ensure_ascii=False)


def _ensure_site_settings():
    ayarlar = SiteAyarlari.query.first()
    if ayarlar:
        return ayarlar
    ayarlar = SiteAyarlari()
    db.session.add(ayarlar)
    db.session.flush()
    return ayarlar


def _set_platform_demo_state(active, action, summary=None):
    if not table_exists("site_ayarlari"):
        return
    ayarlar = _ensure_site_settings()
    meta = _load_site_meta(ayarlar)
    state = {
        "active": bool(active),
        "action": action,
        "updated_at": get_tr_now().strftime("%d.%m.%Y %H:%M"),
        "summary": summary or {},
    }
    if state["active"]:
        state["batch_id"] = f"demo-{get_tr_now().strftime('%Y%m%d%H%M%S')}"
    meta[PLATFORM_DEMO_STATE_KEY] = state
    _save_site_meta(ayarlar, meta)


def _demo_request_cache():
    if not has_request_context():
        return None
    cache = getattr(g, "_demo_data_cache", None)
    if cache is None:
        cache = {}
        g._demo_data_cache = cache
    return cache


def _platform_demo_state_only():
    if not table_exists("site_ayarlari") or not table_exists("demo_seed_record"):
        return {"active": False, "updated_at": "-", "action": "unavailable"}
    ayarlar = SiteAyarlari.query.first()
    meta = _load_site_meta(ayarlar)
    state = meta.get(PLATFORM_DEMO_STATE_KEY, {}) if isinstance(meta.get(PLATFORM_DEMO_STATE_KEY), dict) else {}
    return {
        "active": bool(state.get("active")),
        "updated_at": state.get("updated_at", "-"),
        "action": state.get("action", "idle"),
    }


def _ensure_calibration_record_schema_for_demo_cleanup():
    _ensure_table_schema_for_demo_cleanup(
        "calibration_record",
        {
            "certificate_drive_file_id": "ALTER TABLE calibration_record ADD COLUMN certificate_drive_file_id VARCHAR(255)",
            "certificate_drive_folder_id": "ALTER TABLE calibration_record ADD COLUMN certificate_drive_folder_id VARCHAR(255)",
            "certificate_mime_type": "ALTER TABLE calibration_record ADD COLUMN certificate_mime_type VARCHAR(120)",
            "certificate_size_bytes": "ALTER TABLE calibration_record ADD COLUMN certificate_size_bytes INTEGER",
        },
    )


def _ensure_islem_log_schema_for_demo_cleanup():
    _ensure_table_schema_for_demo_cleanup(
        "islem_log",
        {
            "event_key": "ALTER TABLE islem_log ADD COLUMN event_key VARCHAR(120)",
            "target_model": "ALTER TABLE islem_log ADD COLUMN target_model VARCHAR(80)",
            "target_id": "ALTER TABLE islem_log ADD COLUMN target_id INTEGER",
            "outcome": "ALTER TABLE islem_log ADD COLUMN outcome VARCHAR(20) DEFAULT 'success'",
            "error_code": "ALTER TABLE islem_log ADD COLUMN error_code VARCHAR(32)",
            "title": "ALTER TABLE islem_log ADD COLUMN title VARCHAR(180)",
            "user_message": "ALTER TABLE islem_log ADD COLUMN user_message VARCHAR(255)",
            "owner_message": "ALTER TABLE islem_log ADD COLUMN owner_message TEXT",
            "module": "ALTER TABLE islem_log ADD COLUMN module VARCHAR(24)",
            "severity": "ALTER TABLE islem_log ADD COLUMN severity VARCHAR(20)",
            "exception_type": "ALTER TABLE islem_log ADD COLUMN exception_type VARCHAR(120)",
            "exception_message": "ALTER TABLE islem_log ADD COLUMN exception_message TEXT",
            "traceback_summary": "ALTER TABLE islem_log ADD COLUMN traceback_summary TEXT",
            "route": "ALTER TABLE islem_log ADD COLUMN route VARCHAR(255)",
            "method": "ALTER TABLE islem_log ADD COLUMN method VARCHAR(12)",
            "request_id": "ALTER TABLE islem_log ADD COLUMN request_id VARCHAR(64)",
            "user_email": "ALTER TABLE islem_log ADD COLUMN user_email VARCHAR(150)",
            "resolved": "ALTER TABLE islem_log ADD COLUMN resolved BOOLEAN DEFAULT 0",
            "resolution_note": "ALTER TABLE islem_log ADD COLUMN resolution_note TEXT",
            "ip_address": "ALTER TABLE islem_log ADD COLUMN ip_address VARCHAR(45)",
            "havalimani_id": "ALTER TABLE islem_log ADD COLUMN havalimani_id INTEGER",
        },
    )


def _ensure_table_schema_for_demo_cleanup(table_name, required_columns):
    if not table_exists(table_name):
        return

    bind = db.session.get_bind()
    try:
        existing_columns = {
            item["name"]
            for item in inspect(bind).get_columns(table_name)
            if item.get("name")
        }
    except SQLAlchemyError:
        current_app.logger.exception("%s kolonları okunamadı.", table_name)
        raise RuntimeError("Veritabanı şema kontrolü yapılamadı. Migration/şema doğrulaması gerekli.")

    missing = [name for name in required_columns if name not in existing_columns]
    if not missing:
        return

    dialect_name = str(getattr(bind.dialect, "name", "") or "").lower()
    if dialect_name != "sqlite":
        raise RuntimeError(
            f"{table_name} şeması güncel değil. "
            "Eksik kolonlar: " + ", ".join(missing) + ". Lütfen migration çalıştırın."
        )

    for column_name in missing:
        db.session.execute(text(required_columns[column_name]))
    db.session.commit()
    current_app.logger.warning(
        "Demo cleanup öncesi %s legacy şeması güncellendi. Eklenen kolonlar: %s",
        table_name,
        ", ".join(missing),
    )


def get_platform_demo_status():
    cache = _demo_request_cache()
    if cache is not None and "platform_demo_status" in cache:
        return dict(cache["platform_demo_status"])

    state = _platform_demo_state_only()
    summary = _summary() if table_exists("demo_seed_record") else {}
    status = {
        "active": bool(state.get("active")),
        "summary": summary,
        "updated_at": state.get("updated_at", "-"),
        "action": state.get("action", "idle"),
    }
    if cache is not None:
        cache["platform_demo_status"] = dict(status)
    return status


def platform_demo_is_active():
    cache = _demo_request_cache()
    if cache is not None and "platform_demo_active" in cache:
        return bool(cache["platform_demo_active"])
    active = bool(_platform_demo_state_only().get("active"))
    if cache is not None:
        cache["platform_demo_active"] = active
    return active


def demo_record_ids(model_name):
    cache = _demo_request_cache()
    cache_key = f"demo_ids:{model_name}"
    if cache is not None and cache_key in cache:
        return set(cache[cache_key])
    if not table_exists("demo_seed_record"):
        return set()
    record_ids = {
        int(row.record_id)
        for row in DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG, model_name=model_name).all()
        if row.record_id is not None
    }
    if cache is not None:
        cache[cache_key] = set(record_ids)
    return record_ids


def apply_platform_demo_scope(query, model_name, id_column):
    if not platform_demo_is_active():
        return query
    ids = demo_record_ids(model_name)
    if not ids:
        return query.filter(false())
    return query.filter(id_column.in_(ids))


def _strip_html(value):
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_quantity(raw_quantity):
    match = re.search(r"(\d+)", str(raw_quantity or ""))
    if not match:
        return 1
    try:
        return max(int(match.group(1)), 1)
    except ValueError:
        return 1


def _load_usar_rows():
    if current_app.config.get("TESTING"):
        return list(USAR_FALLBACK_ROWS)
    for candidate in USAR_HTML_CANDIDATES:
        if str(candidate).startswith("/mnt/data"):
            continue
        if not candidate.exists() or not candidate.is_file():
            continue
        try:
            if candidate.stat().st_size > USAR_HTML_MAX_BYTES:
                continue
        except OSError:
            continue
        try:
            html = candidate.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        row_blocks = re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.IGNORECASE | re.DOTALL)
        parsed_rows = []
        for row_html in row_blocks:
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row_html, flags=re.IGNORECASE | re.DOTALL)
            if len(cells) < 7:
                continue
            manual_match = re.search(
                r'href=["\']([^"\']+)["\']',
                row_html,
                flags=re.IGNORECASE,
            )
            parsed_rows.append(
                {
                    "category": _strip_html(cells[1]),
                    "name": _strip_html(cells[2]),
                    "brand": _strip_html(cells[3]),
                    "model": _strip_html(cells[4]),
                    "quantity": _parse_quantity(_strip_html(cells[5])),
                    "function": _strip_html(cells[6]),
                    "manual_url": (manual_match.group(1).strip() if manual_match else ""),
                }
            )
        if parsed_rows:
            return parsed_rows
    return list(USAR_FALLBACK_ROWS)


def _criticality_from_name(name):
    normalized = str(name or "").lower()
    critical_keywords = ["gaz", "solunum", "radyasyon", "termal", "sismik", "kamera", "jenerator"]
    return "kritik" if any(keyword in normalized for keyword in critical_keywords) else "normal"


def _maintenance_period_from_name(name):
    normalized = str(name or "").lower()
    if any(keyword in normalized for keyword in ["gaz", "solunum", "radyasyon"]):
        return 30
    if any(keyword in normalized for keyword in ["jenerator", "beton", "testere", "kesme"]):
        return 60
    return 90


def _normalize_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _clip_text(value, max_len, fallback=""):
    text = _normalize_text(value)
    if not text:
        text = _normalize_text(fallback)
    if max_len <= 0:
        return ""
    if len(text) <= max_len:
        return text
    return text[:max_len].rstrip()


def _shorten_label(value, max_len):
    text = _normalize_text(value)
    if max_len <= 0:
        return ""
    if len(text) <= max_len:
        return text
    if max_len == 1:
        return "…"

    tokens = text.split(" ")
    compact = []
    limit = max_len - 1
    for token in tokens:
        candidate = token if not compact else f"{' '.join(compact)} {token}"
        if len(candidate) > limit:
            break
        compact.append(token)

    if compact:
        return f"{' '.join(compact)}…"
    return f"{text[:limit].rstrip()}…"


def _build_demo_box_location(airport_name, airport_code, equipment_name, function_text, max_len=100):
    airport_name = _normalize_text(airport_name)
    airport_code = _normalize_text(airport_code).upper()
    equipment_name = _normalize_text(equipment_name) or "USAR"
    function_text = _normalize_text(function_text)

    airport_without_suffix = airport_name.replace(" Havalimanı", "").strip()
    airport_candidates = [airport_name]
    if airport_without_suffix and airport_without_suffix != airport_name:
        airport_candidates.append(airport_without_suffix)
    if airport_without_suffix and airport_code:
        airport_candidates.append(f"{airport_without_suffix} ({airport_code})")
    if airport_code:
        airport_candidates.append(airport_code)

    seen = set()
    for airport_label in airport_candidates:
        if not airport_label:
            continue
        airport_label = _normalize_text(airport_label)
        if airport_label in seen:
            continue
        seen.add(airport_label)

        core = f"{airport_label} / {equipment_name}"
        if len(core) > max_len:
            remaining_for_equipment = max_len - len(airport_label) - 3
            if remaining_for_equipment < 4:
                continue
            core = f"{airport_label} / {_shorten_label(equipment_name, remaining_for_equipment)}"
            if len(core) > max_len:
                continue

        if function_text:
            remaining_for_hint = max_len - len(core) - 3
            if remaining_for_hint >= 12:
                hint = _shorten_label(function_text, remaining_for_hint)
                candidate = f"{core} / {hint}"
                if len(candidate) <= max_len:
                    return candidate

        if len(core) <= max_len:
            return core

    fallback_airport = airport_code or _shorten_label(airport_without_suffix or airport_name, 24)
    remaining_for_equipment = max(max_len - len(fallback_airport) - 3, 4)
    fallback = f"{fallback_airport} / {_shorten_label(equipment_name, remaining_for_equipment)}"
    return _shorten_label(fallback, max_len)


def _seed_homepage_demo_if_available():
    if not demo_tools_enabled():
        return None
    if not table_exists("home_slider") or not table_exists("home_section") or not table_exists("announcement"):
        return None
    try:
        from homepage_demo import seed_homepage_demo_data

        return seed_homepage_demo_data()
    except RuntimeError:
        return None
    except Exception:
        db.session.rollback()
        return None


def _clear_homepage_demo_if_available():
    if not demo_tools_enabled():
        return {"attempted": False, "deleted": 0}
    if not table_exists("demo_seed_record"):
        return {"attempted": False, "deleted": 0}
    try:
        from homepage_demo import clear_homepage_demo_data

        result = clear_homepage_demo_data() or {}
        return {
            "attempted": True,
            "deleted": int(result.get("deleted") or 0),
            "message": str(result.get("message") or ""),
        }
    except RuntimeError as exc:
        return {"attempted": True, "deleted": 0, "error": str(exc)}
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Platform demo temizliği sırasında anasayfa demo temizliği hata verdi.")
        return {
            "attempted": True,
            "deleted": 0,
            "error": "Anasayfa demo temizliği beklenmeyen bir hatayla tamamlanamadı.",
        }


def clear_demo_data():
    _guard_demo_tools()
    _ensure_demo_ppe_schema_ready()
    _ensure_calibration_record_schema_for_demo_cleanup()
    _ensure_islem_log_schema_for_demo_cleanup()
    if not table_exists("demo_seed_record"):
        return {"deleted": 0, "homepage_deleted": 0, "warnings": []}

    warnings = []
    seed_row_count = DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG).count()
    platform_state = _platform_demo_state_only()
    if seed_row_count == 0 and platform_state.get("active"):
        warnings.append(
            "Platform demo aktif görünüyor ancak demo iz kayıtları bulunamadı. "
            "Bu nedenle yalnızca izlenebilir kayıtlar temizlenebildi."
        )

    demo_template_ids = demo_record_ids("EquipmentTemplate")
    demo_form_ids = demo_record_ids("MaintenanceFormTemplate")
    demo_airport_ids = demo_record_ids("Havalimani")
    demo_asset_ids = demo_record_ids("InventoryAsset")
    demo_material_ids = demo_record_ids("Malzeme")
    demo_box_ids = demo_record_ids("Kutu")
    demo_user_ids = demo_record_ids("Kullanici")
    demo_spare_part_ids = demo_record_ids("SparePart")
    demo_work_order_ids = demo_record_ids("WorkOrder")
    demo_stock_ids = demo_record_ids("SparePartStock")
    demo_ppe_record_ids = demo_record_ids("PPERecord")
    demo_ppe_assignment_ids = demo_record_ids("PPEAssignmentRecord")
    demo_ppe_item_ids = demo_record_ids("PPEAssignmentItem")

    with db.session.no_autoflush:
        dependent_asset_ids = set()
        dependent_work_order_ids = set()

        # Demo havalimanlarına bağlı seed dışı kayıtları parent siliminden önce temizle.
        # Böylece ORM'nin kutu.havalimani_id alanını NULL'a çekmeye çalıştığı yol kapanır.
        if demo_airport_ids:
            dependent_assets_query = InventoryAsset.query.filter(
                InventoryAsset.havalimani_id.in_(sorted(demo_airport_ids))
            )
            if demo_asset_ids:
                dependent_assets_query = dependent_assets_query.filter(~InventoryAsset.id.in_(sorted(demo_asset_ids)))
            dependent_asset_ids = {row.id for row in dependent_assets_query.with_entities(InventoryAsset.id).all()}

            dependent_materials_query = Malzeme.query.filter(
                Malzeme.havalimani_id.in_(sorted(demo_airport_ids))
            )
            if demo_material_ids:
                dependent_materials_query = dependent_materials_query.filter(~Malzeme.id.in_(sorted(demo_material_ids)))

            dependent_boxes_query = Kutu.query.filter(
                Kutu.havalimani_id.in_(sorted(demo_airport_ids))
            )
            if demo_box_ids:
                dependent_boxes_query = dependent_boxes_query.filter(~Kutu.id.in_(sorted(demo_box_ids)))

            dependent_work_orders_query = WorkOrder.query.join(
                InventoryAsset, WorkOrder.asset_id == InventoryAsset.id
            ).filter(
                InventoryAsset.havalimani_id.in_(sorted(demo_airport_ids))
            )
            if demo_work_order_ids:
                dependent_work_orders_query = dependent_work_orders_query.filter(~WorkOrder.id.in_(sorted(demo_work_order_ids)))
            dependent_work_order_ids = {row.id for row in dependent_work_orders_query.with_entities(WorkOrder.id).all()}

        # Demo bakım formuna referans veren, fakat seed kaydı olmayan şablonlar
        # maintenance_form_template silinirken FK hatasına neden olabiliyor.
        # Demo dışı şablonları silmeyiz; sadece form referansını kaldırırız.
        if demo_form_ids:
            extra_templates = EquipmentTemplate.query.filter(
                EquipmentTemplate.default_maintenance_form_id.in_(sorted(demo_form_ids))
            )
            if demo_template_ids:
                extra_templates = extra_templates.filter(~EquipmentTemplate.id.in_(sorted(demo_template_ids)))
            extra_template_ids = [tpl.id for tpl in extra_templates.all()]
            if extra_template_ids:
                EquipmentTemplate.query.filter(EquipmentTemplate.id.in_(extra_template_ids)).update(
                    {EquipmentTemplate.default_maintenance_form_id: None},
                    synchronize_session=False,
                )

        # Demo şablonuna bağlı fakat seed tablosunda olmayan asset kayıtları,
        # template silinirken equipment_template_id alanını NULL'a düşürüp
        # NOT NULL/FK hatasına neden olabiliyor. Önce bu bağımlı kayıtları temizle.
        if demo_template_ids:
            dependent_assets_query = InventoryAsset.query.filter(
                InventoryAsset.equipment_template_id.in_(sorted(demo_template_ids))
            )
            if demo_asset_ids:
                dependent_assets_query = dependent_assets_query.filter(~InventoryAsset.id.in_(sorted(demo_asset_ids)))
            for dependent_asset in dependent_assets_query.all():
                db.session.delete(dependent_asset)

        # Assignment recipient satırları kullanıcı silme sırasından önce temizlenmezse
        # ORM user_id alanını NULL'a çekmeye çalışabiliyor.
        if demo_user_ids and table_exists("assignment_recipient"):
            AssignmentRecipient.query.filter(
                AssignmentRecipient.user_id.in_(sorted(demo_user_ids))
            ).delete(synchronize_session=False)

        if table_exists("ppe_assignment_record") and demo_user_ids:
            dependent_ppe_assignment_query = PPEAssignmentRecord.query.filter(
                or_(
                    PPEAssignmentRecord.recipient_user_id.in_(sorted(demo_user_ids)),
                    PPEAssignmentRecord.delivered_by_id.in_(sorted(demo_user_ids)),
                    PPEAssignmentRecord.created_by_id.in_(sorted(demo_user_ids)),
                )
            )
            if demo_ppe_assignment_ids:
                dependent_ppe_assignment_query = dependent_ppe_assignment_query.filter(
                    ~PPEAssignmentRecord.id.in_(sorted(demo_ppe_assignment_ids))
                )
            dependent_ppe_assignment_ids = {
                row.id
                for row in dependent_ppe_assignment_query.with_entities(PPEAssignmentRecord.id).all()
            }
            if dependent_ppe_assignment_ids and table_exists("ppe_assignment_item"):
                PPEAssignmentItem.query.filter(
                    PPEAssignmentItem.assignment_id.in_(sorted(dependent_ppe_assignment_ids))
                ).delete(synchronize_session=False)
            if dependent_ppe_assignment_ids:
                PPEAssignmentRecord.query.filter(
                    PPEAssignmentRecord.id.in_(sorted(dependent_ppe_assignment_ids))
                ).delete(synchronize_session=False)

        if table_exists("ppe_assignment_item") and demo_ppe_record_ids:
            dependent_ppe_items = PPEAssignmentItem.query.filter(
                PPEAssignmentItem.ppe_record_id.in_(sorted(demo_ppe_record_ids))
            )
            if demo_ppe_item_ids:
                dependent_ppe_items = dependent_ppe_items.filter(
                    ~PPEAssignmentItem.id.in_(sorted(demo_ppe_item_ids))
                )
            dependent_ppe_items.delete(synchronize_session=False)

        # Bridge/usage kayıtları DemoSeedRecord dışında kalabiliyor.
        # Demo varlıklara/parçalara bağlı bağımlılıkları önce temizle.
        if table_exists("asset_spare_part_link") and (demo_asset_ids or demo_spare_part_ids):
            clauses = []
            if demo_asset_ids:
                clauses.append(AssetSparePartLink.asset_id.in_(sorted(demo_asset_ids)))
            if dependent_asset_ids:
                clauses.append(AssetSparePartLink.asset_id.in_(sorted(dependent_asset_ids)))
            if demo_spare_part_ids:
                clauses.append(AssetSparePartLink.spare_part_id.in_(sorted(demo_spare_part_ids)))
            AssetSparePartLink.query.filter(or_(*clauses)).delete(synchronize_session=False)

        if table_exists("work_order_part_usage") and (demo_work_order_ids or dependent_work_order_ids or demo_spare_part_ids or demo_stock_ids):
            clauses = []
            if demo_work_order_ids:
                clauses.append(WorkOrderPartUsage.work_order_id.in_(sorted(demo_work_order_ids)))
            if dependent_work_order_ids:
                clauses.append(WorkOrderPartUsage.work_order_id.in_(sorted(dependent_work_order_ids)))
            if demo_spare_part_ids:
                clauses.append(WorkOrderPartUsage.spare_part_id.in_(sorted(demo_spare_part_ids)))
            if demo_stock_ids:
                clauses.append(WorkOrderPartUsage.consumed_from_stock_id.in_(sorted(demo_stock_ids)))
            WorkOrderPartUsage.query.filter(or_(*clauses)).delete(synchronize_session=False)

        if dependent_work_order_ids:
            WorkOrder.query.filter(WorkOrder.id.in_(sorted(dependent_work_order_ids))).delete(synchronize_session=False)

        if dependent_asset_ids:
            InventoryAsset.query.filter(InventoryAsset.id.in_(sorted(dependent_asset_ids))).delete(synchronize_session=False)

        if demo_airport_ids:
            dependent_materials_query.delete(synchronize_session=False)
            dependent_boxes_query.delete(synchronize_session=False)

    # Şablon siliminden önce bağımlı asset silimlerini flush ederek
    # ORM'nin FK alanını NULL'a çekme yolunu kapatır.
    db.session.flush()

    model_map = {
        "AssignmentHistoryEntry": AssignmentHistoryEntry,
        "AssignmentItem": AssignmentItem,
        "AssignmentRecipient": AssignmentRecipient,
        "AssignmentRecord": AssignmentRecord,
        "PPEAssignmentItem": PPEAssignmentItem,
        "PPEAssignmentRecord": PPEAssignmentRecord,
        "PPERecordEvent": PPERecordEvent,
        "PPERecord": PPERecord,
        "CalibrationRecord": CalibrationRecord,
        "CalibrationSchedule": CalibrationSchedule,
        "ConsumableStockMovement": ConsumableStockMovement,
        "ConsumableItem": ConsumableItem,
        "MaintenanceTriggerRule": MaintenanceTriggerRule,
        "MeterDefinition": MeterDefinition,
        "MaintenancePlan": MaintenancePlan,
        "WorkOrder": WorkOrder,
        "AssetOperationalState": AssetOperationalState,
        "InventoryAsset": InventoryAsset,
        "Malzeme": Malzeme,
        "Kutu": Kutu,
        "SparePartStock": SparePartStock,
        "SparePart": SparePart,
        "Supplier": Supplier,
        "MaintenanceInstruction": MaintenanceInstruction,
        "MaintenanceFormField": MaintenanceFormField,
        "MaintenanceFormTemplate": MaintenanceFormTemplate,
        "EquipmentTemplate": EquipmentTemplate,
        "Kullanici": Kullanici,
        "Havalimani": Havalimani,
    }
    delete_order = [
        "AssignmentHistoryEntry",
        "AssignmentItem",
        "AssignmentRecipient",
        "AssignmentRecord",
        "PPEAssignmentItem",
        "PPEAssignmentRecord",
        "PPERecordEvent",
        "PPERecord",
        "CalibrationRecord",
        "CalibrationSchedule",
        "ConsumableStockMovement",
        "ConsumableItem",
        "MaintenanceTriggerRule",
        "MeterDefinition",
        "MaintenancePlan",
        "WorkOrder",
        "AssetOperationalState",
        "InventoryAsset",
        "Malzeme",
        "Kutu",
        "SparePartStock",
        "SparePart",
        "Supplier",
        "MaintenanceInstruction",
        "EquipmentTemplate",
        "MaintenanceFormTemplate",
        "MaintenanceFormField",
        "Kullanici",
        "Havalimani",
    ]
    deleted = 0
    with db.session.no_autoflush:
        for model_name in delete_order:
            rows = DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG, model_name=model_name).order_by(DemoSeedRecord.id.desc()).all()
            model = model_map[model_name]
            if model_name == "EquipmentTemplate":
                template_ids = sorted({int(row.record_id) for row in rows if row.record_id is not None})
                if template_ids:
                    # Şablona bağlı kalmış seed dışı asset kayıtları template silimi sırasında
                    # FK/NOT NULL çakışması üretmesin diye son bir güvenli temizleme geçişi.
                    remaining_assets = InventoryAsset.query.filter(
                        InventoryAsset.equipment_template_id.in_(template_ids)
                    ).all()
                    for remaining_asset in remaining_assets:
                        db.session.delete(remaining_asset)
                    if remaining_assets:
                        db.session.flush()
            for row in rows:
                obj = db.session.get(model, row.record_id)
                if obj is not None:
                    db.session.delete(obj)
                    deleted += 1
    with db.session.no_autoflush:
        DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG).delete(synchronize_session=False)
    _set_platform_demo_state(False, "cleared", summary={"deleted": deleted})
    db.session.commit()
    homepage_result = _clear_homepage_demo_if_available()
    homepage_deleted = int(homepage_result.get("deleted") or 0)
    if homepage_result.get("error"):
        warnings.append(str(homepage_result.get("error")))
    if deleted == 0 and homepage_deleted == 0 and seed_row_count == 0 and not warnings:
        warnings.append("Temizlenecek demo kaydı bulunamadı.")
    return {
        "deleted": deleted,
        "homepage_deleted": homepage_deleted,
        "warnings": warnings,
        "partial_success": bool(warnings),
    }


def seed_demo_data(reset=False):
    _guard_demo_tools()
    _ensure_demo_ppe_schema_ready()
    if reset:
        clear_demo_data()
        db.session.expire_all()
    elif DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG).first():
        summary = _summary()
        _set_platform_demo_state(True, "reused", summary=summary)
        db.session.commit()
        _seed_homepage_demo_if_available()
        return summary

    rng = random.Random(20260318)
    today = get_tr_now().date()

    first_names = [
        "Ahmet", "Mehmet", "Ayse", "Fatma", "Mustafa", "Emre", "Burak", "Can", "Seda", "Zeynep",
        "Merve", "Tolga", "Okan", "Sinem", "Berk", "Yasin", "Ece", "Serkan", "Derya", "Gizem",
    ]
    last_names = [
        "Yilmaz", "Demir", "Kaya", "Sahin", "Aydin", "Arslan", "Cetin", "Koc", "Ozdemir", "Kaplan",
        "Aslan", "Kurt", "Polat", "Gunes", "Kilic", "Bulut", "Tas", "Kara", "Avci", "Eren",
    ]
    usar_rows = _load_usar_rows()
    equipment_specs = []
    for row in usar_rows:
        equipment_specs.append(
            {
                "name": _clip_text(row["name"], 120, "USAR Ekipman"),
                "category": _clip_text(row["category"] or "Kentsel Arama/Kurtarma", 80, "Kentsel Arama/Kurtarma"),
                "period_days": _maintenance_period_from_name(row["name"]),
                "criticality": _criticality_from_name(row["name"]),
                "brand": _clip_text(row["brand"] or "USAR", 80, "USAR"),
                "model": _clip_text(row["model"] or "STD", 80, "STD"),
                "description": _normalize_text(row["function"] or f"{row['name']} demo ekipman kaydı"),
                "manual_url": _normalize_text(row["manual_url"] or ""),
                "unit_count": max(int(row.get("quantity") or 1), 1),
            }
        )
    equipment_specs.extend(
        [
            {
                "name": "Hidrolik Kesici",
                "category": "Kurtarma",
                "period_days": 90,
                "criticality": "kritik",
                "brand": "Holmatro",
                "model": "HCT-300",
                "description": "Yüksek basınçlı kesici seti",
                "manual_url": "",
                "unit_count": 1,
            },
            {
                "name": "Hidrolik Ayırıcı",
                "category": "Kurtarma",
                "period_days": 90,
                "criticality": "kritik",
                "brand": "Holmatro",
                "model": "SP-5240",
                "description": "Sıkışmış bölgelere erişim için ayırıcı set",
                "manual_url": "",
                "unit_count": 1,
            },
            {
                "name": "Termal Kamera",
                "category": "Gözlem",
                "period_days": 90,
                "criticality": "kritik",
                "brand": "FLIR",
                "model": "K55",
                "description": "Isı izi tabanlı saha tarama kamerası",
                "manual_url": "",
                "unit_count": 1,
            },
            {
                "name": "Portatif Jeneratör",
                "category": "Enerji",
                "period_days": 30,
                "criticality": "kritik",
                "brand": "AKSA",
                "model": "AAP-8000",
                "description": "Saha enerji beslemesi için jeneratör",
                "manual_url": "",
                "unit_count": 1,
            },
            {
                "name": "Aydınlatma Kulesi",
                "category": "Aydınlatma",
                "period_days": 60,
                "criticality": "normal",
                "brand": "Will-Burt",
                "model": "Solaris Pro",
                "description": "Gece operasyonu saha aydınlatması",
                "manual_url": "",
                "unit_count": 1,
            },
        ]
    )
    form_specs = [
        (
            "Jenerator Bakim Formu",
            "Jenerator periyodik kontrol formu",
            [
                ("physical_damage", "Fiziksel hasar kontrolü", "checkbox"),
                ("battery_level", "Batarya seviyesi uygun mu", "yes_no"),
                ("cable_check", "Kablo bağlantıları sağlam mı", "yes_no"),
                ("run_test", "Çalıştırma testi geçti mi", "pass_fail"),
                ("oil_level", "Yağ seviyesi", "numeric_reading"),
                ("notes", "Saha notu", "text"),
            ],
        ),
        (
            "Gaz Olcum Cihazi Kontrol Formu",
            "Gaz olcum ve kalibrasyon checklisti",
            [
                ("physical_damage", "Fiziksel hasar kontrolü", "checkbox"),
                ("sensor_test", "Sensör testi başarılı mı", "pass_fail"),
                ("calibration_label", "Kalibrasyon etiketi güncel mi", "yes_no"),
                ("battery_level", "Batarya seviyesi uygun mu", "yes_no"),
                ("ppm_reading", "Ölçüm değeri (ppm)", "numeric_reading"),
                ("notes", "Saha notu", "text"),
            ],
        ),
        (
            "Termal Kamera Kontrol Formu",
            "Lens, batarya ve ekran kontrol listesi",
            [
                ("lens_clean", "Lens temizliği tamam mı", "yes_no"),
                ("screen_check", "Ekran görüntüsü net mi", "pass_fail"),
                ("battery_level", "Batarya seviyesi uygun mu", "yes_no"),
                ("startup_test", "Açılış testi geçti mi", "pass_fail"),
                ("notes", "Saha notu", "text"),
            ],
        ),
        (
            "Hidrolik Set Kontrol Formu",
            "Kesici ve ayirici operasyon oncesi kontrol formu",
            [
                ("physical_damage", "Fiziksel hasar kontrolü", "checkbox"),
                ("hose_integrity", "Kablo / hortum sağlam mı", "yes_no"),
                ("pressure_test", "Basınç testi geçti mi", "pass_fail"),
                ("cleaning_done", "Temizlik yapıldı mı", "yes_no"),
                ("notes", "Saha notu", "text"),
            ],
        ),
        (
            "Yangin Sondurucu Kontrol Formu",
            "Basinc ve etiket kontrol formu",
            [
                ("physical_damage", "Fiziksel hasar kontrolü", "checkbox"),
                ("pressure_ok", "Basınç göstergesi uygun mu", "yes_no"),
                ("label_current", "Kontrol etiketi güncel mi", "yes_no"),
                ("seal_ok", "Mühür ve pim sağlam mı", "pass_fail"),
                ("notes", "Saha notu", "text"),
            ],
        ),
        (
            "Batarya Saglik Formu",
            "Batarya dongu ve sarj sagligi formu",
            [
                ("physical_damage", "Fiziksel hasar kontrolü", "checkbox"),
                ("charge_level", "Şarj seviyesi", "numeric_reading"),
                ("adapter_check", "Şarj adaptörü sağlam mı", "yes_no"),
                ("health_test", "Batarya sağlık testi geçti mi", "pass_fail"),
                ("notes", "Saha notu", "text"),
            ],
        ),
        (
            "Telsiz Operasyon Formu",
            "Telsiz haberlesme kontrol formu",
            [
                ("physical_damage", "Fiziksel hasar kontrolü", "checkbox"),
                ("channel_test", "Kanal testi başarılı mı", "pass_fail"),
                ("audio_quality", "Ses kalitesi yeterli mi", "yes_no"),
                ("battery_level", "Batarya seviyesi uygun mu", "yes_no"),
                ("notes", "Saha notu", "text"),
            ],
        ),
        (
            "Projektor Kontrol Formu",
            "Projektör ve aydınlatma saha uygunluk formu",
            [
                ("physical_damage", "Fiziksel hasar kontrolü", "checkbox"),
                ("light_output", "Işık çıkışı yeterli mi", "pass_fail"),
                ("tripod_check", "Tripod bağlantısı sağlam mı", "yes_no"),
                ("cable_check", "Kablo / fiş sağlam mı", "yes_no"),
                ("notes", "Saha notu", "text"),
            ],
        ),
        (
            "Solunum Seti Kontrol Formu",
            "Solunum seti saha uygunluk formu",
            [
                ("physical_damage", "Fiziksel hasar kontrolü", "checkbox"),
                ("mask_check", "Maske ve bağlantılar sağlam mı", "yes_no"),
                ("pressure_test", "Basınç testi başarılı mı", "pass_fail"),
                ("cleaning_done", "Temizlik yapıldı mı", "yes_no"),
                ("notes", "Saha notu", "text"),
            ],
        ),
    ]
    part_specs = [
        ("BAT-001", "Batarya Paketi", "Enerji"),
        ("HRT-002", "Hortum Seti", "Hidrolik"),
        ("NZL-003", "Nozul", "Yangin"),
        ("FLT-004", "Filtre", "Motor"),
        ("SNS-005", "Sensor Modulu", "Elektronik"),
        ("BCK-006", "Bicak Ucu", "Kesici"),
        ("CHR-007", "Sarj Adaptoru", "Enerji"),
        ("CNT-008", "Conta", "Hidrolik"),
        ("KBL-009", "Kablo Demeti", "Elektrik"),
        ("BAG-010", "Baglanti Aparati", "Montaj"),
        ("LNS-011", "Lens Koruyucu", "Optik"),
        ("FAN-012", "Sogutma Fani", "Motor"),
        ("VAL-013", "Valf", "Hidrolik"),
        ("SIG-014", "Sigorta", "Elektrik"),
        ("BTN-015", "Kontrol Butonu", "Elektronik"),
        ("BTR-016", "Yedek Batarya", "Enerji"),
        ("CHG-017", "Sarj Kablosu", "Enerji"),
        ("MSK-018", "Maske Filtresi", "KKD"),
        ("LCK-019", "Kilitleme Pimi", "Montaj"),
        ("OIL-020", "Bakim Yagi", "Motor"),
    ]
    consumable_specs = [
        ("CON-001", "Eldiven", "KKD", "kutu"),
        ("CON-002", "Maske", "KKD", "adet"),
        ("CON-003", "Pil", "Enerji", "adet"),
        ("CON-004", "Temizlik Malzemesi", "Hijyen", "adet"),
        ("CON-005", "Etiket Kağıdı", "Ofis", "rulo"),
    ]

    airports = []
    for name, code in AIRPORTS:
        airport = Havalimani(ad=name, kodu=code)
        db.session.add(airport)
        db.session.flush()
        _register_record(airport, name)
        airports.append(airport)

    boxes_by_airport = {}
    box_seed_rows = (usar_rows[:5] if usar_rows else USAR_FALLBACK_ROWS[:5]) or USAR_FALLBACK_ROWS[:5]
    box_brands = ["Pelican", "Peli", "Zarges", "SKB", "Explorer", "Nanuk"]
    for airport in airports:
        boxes = []
        for index, row in enumerate(box_seed_rows, start=1):
            code = f"{airport.kodu}-SAR-{index:02d}"
            box = Kutu(
                kodu=code,
                marka=box_brands[(index - 1) % len(box_brands)],
                konum=None,
                havalimani_id=airport.id,
            )
            db.session.add(box)
            db.session.flush()
            _register_record(box, box.kodu)
            boxes.append(box)
        boxes_by_airport[airport.id] = boxes

    users = []
    global_roles = [
        (ROLE_OWNER, "sistem.sahibi@demo.sarx.local", "Demo Sistem Sahibi"),
        (ROLE_ADMIN, "sistem.admin@demo.sarx.local", "Demo Sistem Yöneticisi"),
    ]
    for role, username, full_name in global_roles:
        user = Kullanici(
            kullanici_adi=_clip_text(username, 50, username),
            tam_ad=_clip_text(full_name, 100, "Demo Kullanıcı"),
            rol=role,
            havalimani_id=None,
            telefon_numarasi=f"+90 530 900 {rng.randint(10, 99)} {rng.randint(10, 99)}",
            uzmanlik_alani=_clip_text(rng.choice(["Koordinasyon", "Operasyon", "Bakım", "Lojistik"]), 100),
        )
        user.sifre_set(DEMO_PASSWORD)
        db.session.add(user)
        db.session.flush()
        _register_record(user, username)
        users.append(user)

    airport_role_pattern = (
        [ROLE_MANAGER]
        + [ROLE_MAINTENANCE] * 4
        + [ROLE_WAREHOUSE] * 2
        + [ROLE_PERSONNEL] * 11
        + [ROLE_EDITOR]
        + [ROLE_READONLY]
    )
    for airport in airports:
        for person_index in range(1, AIRPORT_PERSONNEL_COUNT + 1):
            role = airport_role_pattern[(person_index - 1) % len(airport_role_pattern)]
            name_seed = (airport.id * 100) + person_index
            first_name = first_names[name_seed % len(first_names)]
            last_name = last_names[(name_seed * 3) % len(last_names)]
            username = f"demo.{airport.kodu.lower()}.{person_index:02d}@demo.sarx.local"
            phone = f"+90 5{rng.randint(10, 99)} {rng.randint(100, 999)} {rng.randint(10, 99)} {rng.randint(10, 99)}"
            user = Kullanici(
                kullanici_adi=_clip_text(username, 50, username),
                tam_ad=_clip_text(f"{first_name} {last_name}", 100, "Demo Personel"),
                rol=role,
                havalimani_id=airport.id,
                telefon_numarasi=phone,
                uzmanlik_alani=_clip_text(
                    rng.choice(["Operasyon", "Bakım", "Lojistik", "İletişim", "Arama Kurtarma"]),
                    100,
                ),
            )
            user.sifre_set(DEMO_PASSWORD)
            db.session.add(user)
            db.session.flush()
            _register_record(user, username)
            users.append(user)

    forms = []
    for name, description, field_specs in form_specs:
        form_name = _clip_text(name, 120, "Bakım Formu")
        form = MaintenanceFormTemplate(name=form_name, description=_normalize_text(description), is_active=True)
        db.session.add(form)
        db.session.flush()
        _register_record(form, form_name)
        for order_index, (field_key, label, field_type) in enumerate(field_specs, start=1):
            field = MaintenanceFormField(
                form_template_id=form.id,
                field_key=_clip_text(f"{form.id}_{field_key}", 100, f"field_{order_index}"),
                label=_clip_text(label, 150, f"Alan {order_index}"),
                field_type=_clip_text(field_type, 30, "text"),
                is_required=field_key != "notes",
                order_index=order_index,
                options_json=None,
            )
            db.session.add(field)
            db.session.flush()
            _register_record(field, field.field_key)
        forms.append(form)

    def pick_form_for_template(template_name):
        normalized = (template_name or "").lower()
        if "jenerator" in normalized:
            return forms[0]
        if "gaz" in normalized:
            return forms[1]
        if "termal" in normalized or "arama kamerasi" in normalized:
            return forms[2]
        if "hidrolik" in normalized or "kesici" in normalized or "ayirici" in normalized:
            return forms[3]
        if "yangin sondurucu" in normalized:
            return forms[4]
        if "batarya" in normalized:
            return forms[5]
        if "telsiz" in normalized or "gps" in normalized:
            return forms[6]
        if "projektor" in normalized or "aydinlatma" in normalized:
            return forms[7]
        if "solunum" in normalized:
            return forms[8]
        return forms[3]

    templates = []
    template_default_units = {}
    for index, spec in enumerate(equipment_specs, start=1):
        name = spec["name"]
        category = spec["category"]
        period_days = spec["period_days"]
        criticality = spec["criticality"]
        description = spec.get("description") or f"{name} saha operasyonlari icin demo kaydi"
        manual_url = spec.get("manual_url") or ""
        template = EquipmentTemplate(
            name=_clip_text(name, 120, f"Ekipman {index}"),
            category=_clip_text(category, 80, "Genel"),
            brand=_clip_text(
                spec.get("brand") or rng.choice(["Holmatro", "Drager", "Flir", "Milwaukee", "Motorola", "Rosenbauer"]),
                80,
            ),
            model_code=_clip_text(spec.get("model") or f"MDL-{index:03d}", 80, f"MDL-{index:03d}"),
            description=_normalize_text(description),
            technical_specs=f"{category} segmenti icin demo teknik ozellik seti. Kilavuz: {manual_url}" if manual_url else f"{category} segmenti icin demo teknik ozellik seti",
            manufacturer=_clip_text(rng.choice(["ARFFTech", "RescuePro", "Opsline"]), 120),
            maintenance_period_days=period_days,
            criticality_level=criticality,
            default_maintenance_form_id=pick_form_for_template(name).id,
            is_active=True,
        )
        db.session.add(template)
        db.session.flush()
        _register_record(template, name)
        templates.append(template)
        template_default_units[template.id] = max(int(spec.get("unit_count") or 1), 1)

        instruction = MaintenanceInstruction(
            equipment_template_id=template.id,
            title=_clip_text(f"{template.name} Kullanım ve Bakım Talimatı", 180, "Bakım Talimatı"),
            description=_clip_text(
                f"{template.name} için saha güvenliği, kontrol adımları ve bakım sırası demo talimatı.",
                2000,
                "Demo bakım talimatı",
            ),
            manual_url=_clip_text(manual_url, 500),
            visual_url="",
            revision_no="R1",
            revision_date=today - timedelta(days=rng.randint(10, 90)),
            notes="Demo set içerisinde otomatik oluşturulan talimat kaydı.",
            is_active=True,
        )
        db.session.add(instruction)
        db.session.flush()
        _register_record(instruction, template.name)

    suppliers = []
    for supplier_index in range(1, 6):
        supplier = Supplier(
            name=_clip_text(f"Demo Tedarikci {supplier_index}", 150),
            contact_name=_clip_text(f"Tedarik Yetkilisi {supplier_index}", 120),
            phone=_clip_text(f"444 10{supplier_index:02d}", 50),
            email=_clip_text(f"tedarik{supplier_index}@demo.local", 150),
            is_active=True,
        )
        db.session.add(supplier)
        db.session.flush()
        _register_record(supplier, supplier.name)
        suppliers.append(supplier)

    spare_parts = []
    for index, (code, title, category) in enumerate(part_specs, start=1):
        part = SparePart(
            part_code=_clip_text(code, 80, f"PART-{index:03d}"),
            title=_clip_text(title, 180, f"Parca {index}"),
            category=_clip_text(category, 80, "Genel"),
            manufacturer=_clip_text(rng.choice(["RescuePro", "Opsline", "TechSAR"]), 120),
            model_code=_clip_text(f"PRT-{index:03d}", 120),
            description=_normalize_text(f"{title} demo yedek parca kaydi"),
            unit=_clip_text("adet", 20, "adet"),
            min_stock_level=4,
            critical_level=2,
            supplier_id=suppliers[index % len(suppliers)].id,
            is_active=True,
        )
        db.session.add(part)
        db.session.flush()
        _register_record(part, code)
        spare_parts.append(part)
        for airport in airports:
            if index % 5 == 0:
                quantity = 1
            elif index % 3 == 0:
                quantity = 3
            else:
                quantity = rng.randint(7, 18)
            stock = SparePartStock(
                spare_part_id=part.id,
                airport_id=airport.id,
                quantity_on_hand=quantity,
                quantity_reserved=rng.randint(0, 2),
                reorder_point=4,
                shelf_location=f"{airport.kodu}-RAF-{(index % 4) + 1}",
                is_active=True,
            )
            db.session.add(stock)
            db.session.flush()
            _register_record(stock, f"{code}-{airport.kodu}")

    consumables = []
    for code, title, category, unit in consumable_specs:
        item = ConsumableItem(
            code=_clip_text(code, 80, code),
            title=_clip_text(title, 180, title),
            category=_clip_text(category, 80, "Genel"),
            unit=_clip_text(unit, 20, "adet"),
            min_stock_level=5,
            critical_level=2,
            description=_normalize_text(f"{title} demo sarf kaydı"),
            is_active=True,
        )
        db.session.add(item)
        db.session.flush()
        _register_record(item, code)
        consumables.append(item)
        for airport in airports:
            movement = ConsumableStockMovement(
                consumable_id=item.id,
                airport_id=airport.id,
                movement_type="in",
                quantity=rng.randint(2, 16),
                reference_note="Demo başlangıç stoğu",
                performed_by_id=users[0].id if users else None,
            )
            db.session.add(movement)
            db.session.flush()
            _register_record(movement, f"{code}-{airport.kodu}")

    assets = []
    statuses = ["aktif", "aktif", "aktif", "bakimda", "arizali", "pasif"]
    work_order_statuses = ["acik", "atandi", "islemde", "beklemede_parca", "tamamlandi"]
    work_order_types = ["preventive", "corrective", "inspection", "calibration", "emergency"]
    for airport in airports:
        for asset_index in range(1, 25):
            template = templates[(asset_index + airport.id) % len(templates)]
            box = boxes_by_airport[airport.id][asset_index % len(boxes_by_airport[airport.id])]
            status = statuses[(asset_index + airport.id) % len(statuses)]
            default_units = template_default_units.get(template.id, 1)
            serial = _clip_text(
                f"{airport.kodu}-{template.id:03d}-{asset_index:03d}-{rng.randint(100, 999)}",
                100,
            )
            asset_tag = _clip_text(f"USAR-{airport.kodu}-{template.id:03d}-{asset_index:03d}", 120)
            last_maintenance = today - timedelta(days=rng.randint(5, 160))
            next_maintenance = last_maintenance + timedelta(days=template.maintenance_period_days or 90)
            if asset_index % 6 == 0:
                next_maintenance = today - timedelta(days=rng.randint(1, 20))
            elif asset_index % 4 == 0:
                next_maintenance = today + timedelta(days=rng.randint(1, 12))
            material = Malzeme(
                ad=_clip_text(f"{template.name} / {template.brand} {template.model_code}", 100, "Demo Ekipman"),
                seri_no=serial,
                teknik_ozellikler=template.technical_specs,
                stok_miktari=default_units,
                durum={"aktif": "Aktif", "bakimda": "Bakımda", "arizali": "Arızalı", "pasif": "Pasif"}[status],
                kritik_mi=template.criticality_level == "kritik",
                son_bakim_tarihi=last_maintenance,
                gelecek_bakim_tarihi=next_maintenance,
                kutu_id=box.id,
                havalimani_id=airport.id,
            )
            db.session.add(material)
            db.session.flush()
            _register_record(material, material.seri_no)

            asset = InventoryAsset(
                equipment_template_id=template.id,
                havalimani_id=airport.id,
                legacy_material_id=material.id,
                serial_no=serial,
                qr_code="pending",
                asset_tag=asset_tag,
                unit_count=default_units,
                depot_location=_clip_text(box.kodu, 150, box.kodu),
                status=status,
                maintenance_state="gecikmis" if next_maintenance < today else "normal",
                last_maintenance_date=last_maintenance,
                next_maintenance_date=next_maintenance,
                next_calibration_date=today + timedelta(days=rng.randint(-25, 40)),
                acquired_date=today - timedelta(days=rng.randint(180, 720)),
                warranty_end_date=today + timedelta(days=rng.randint(60, 540)),
                notes=f"Demo seed kaydi - {airport.kodu}",
                maintenance_period_days=template.maintenance_period_days,
                is_critical=template.criticality_level == "kritik",
            )
            db.session.add(asset)
            db.session.flush()
            asset.qr_code = f"/demo/asset/{asset.id}"
            _register_record(asset, asset.serial_no)
            assets.append(asset)

            operational_state = AssetOperationalState(
                asset_id=asset.id,
                lifecycle_status=(
                    "in_maintenance"
                    if status == "bakimda"
                    else "decommissioned"
                    if status == "pasif"
                    else "active"
                ),
                warranty_start=(asset.acquired_date or today) + timedelta(days=1),
                service_provider="Demo Teknik Servis",
                service_note="Demo operasyon durumu kaydı",
                last_service_date=last_maintenance,
                lifecycle_note=f"{airport.kodu} demo varlık izleme kaydı",
                transfer_reference=f"TRN-{airport.kodu}-{asset.id:05d}",
            )
            db.session.add(operational_state)
            db.session.flush()
            _register_record(operational_state, asset.serial_no)

            plan = MaintenancePlan(
                name=_clip_text(f"{template.name} Planı", 120, "Demo Bakım Planı"),
                equipment_template_id=template.id,
                asset_id=asset.id,
                owner_airport_id=airport.id,
                period_days=rng.choice([30, 90, 180]),
                start_date=today - timedelta(days=rng.randint(30, 180)),
                last_maintenance_date=last_maintenance,
                is_active=True,
                notes="Demo bakım planı",
            )
            plan.recalculate_next_due_date(last_maintenance)
            if asset_index % 6 == 0:
                plan.next_due_date = today - timedelta(days=rng.randint(1, 20))
            elif asset_index % 4 == 0:
                plan.next_due_date = today + timedelta(days=rng.randint(1, 10))
            db.session.add(plan)
            db.session.flush()
            _register_record(plan, plan.name)

            if asset_index % 3 == 0:
                meter = MeterDefinition(
                    name="Çalışma Saati",
                    meter_type="hours",
                    unit="h",
                    asset_id=asset.id,
                    is_active=True,
                )
                db.session.add(meter)
                db.session.flush()
                _register_record(meter, f"meter-{asset.id}")

                rule = MaintenanceTriggerRule(
                    name="Saat Bazli Bakim",
                    trigger_type="hours",
                    asset_id=asset.id,
                    meter_definition_id=meter.id,
                    threshold_value=500,
                    warning_lead_value=25,
                    auto_create_work_order=asset_index % 2 == 0,
                    is_active=True,
                )
                db.session.add(rule)
                db.session.flush()
                _register_record(rule, f"trigger-{asset.id}")

            if template.name in {"Gaz Olcum Cihazi", "Termal Kamera"} or "Gaz" in template.name or "Kamera" in template.name:
                calibration_schedule = CalibrationSchedule(
                    asset_id=asset.id,
                    period_days=180,
                    warning_days=15,
                    provider="Demo Kalibrasyon Servisi",
                    is_active=True,
                    note="Demo kalibrasyon planı",
                )
                db.session.add(calibration_schedule)
                db.session.flush()
                _register_record(calibration_schedule, f"calibration-schedule-{asset.id}")
                calibration_date = today - timedelta(days=rng.randint(20, 140))
                next_calibration_date = calibration_date + timedelta(days=180)
                asset.last_calibration_date = calibration_date
                asset.next_calibration_date = next_calibration_date
                calibration_record = CalibrationRecord(
                    asset_id=asset.id,
                    calibration_schedule_id=calibration_schedule.id,
                    calibration_date=calibration_date,
                    next_calibration_date=next_calibration_date,
                    calibrated_by_id=users[0].id if users else None,
                    provider="Demo Kalibrasyon Servisi",
                    certificate_no=f"CAL-{asset.id:05d}",
                    result_status="passed",
                    note="Demo kalibrasyon kaydı",
                )
                db.session.add(calibration_record)
                db.session.flush()
                _register_record(calibration_record, f"calibration-record-{asset.id}")

    technicians = [user for user in users if user.rol in {ROLE_AIRPORT_MANAGER, ROLE_MAINTENANCE, ROLE_PERSONNEL, ROLE_ADMIN}]
    work_orders = []
    for index, asset in enumerate(assets[:45], start=1):
        creator = technicians[index % len(technicians)]
        assignee = technicians[(index + 3) % len(technicians)]
        status = work_order_statuses[index % len(work_order_statuses)]
        order = WorkOrder(
            work_order_no=f"WO-DEMO-{index:04d}",
            asset_id=asset.id,
            maintenance_type="bakim" if index % 2 else "ariza",
            work_order_type=work_order_types[index % len(work_order_types)],
            source_type="meter_trigger" if index % 4 == 0 else "manual",
            description=f"{asset.equipment_template.name if asset.equipment_template else 'Asset'} için demo iş emri",
            target_date=today + timedelta(days=rng.randint(-5, 20)),
            assigned_user_id=assignee.id,
            created_user_id=creator.id,
            status=status,
            priority=rng.choice(["dusuk", "orta", "yuksek", "kritik"]),
            completed_at=get_tr_now() if status == "tamamlandi" else None,
            verification_status="beklemede" if status != "tamamlandi" else "dogrulandi",
            checklist_template_id=(asset.equipment_template.default_maintenance_form_id if asset.equipment_template else forms[index % len(forms)].id),
        )
        db.session.add(order)
        db.session.flush()
        _register_record(order, order.work_order_no)
        work_orders.append(order)

    if assets and spare_parts:
        for index, asset in enumerate(assets[:36], start=1):
            part = spare_parts[(index * 3) % len(spare_parts)]
            link = AssetSparePartLink(
                asset_id=asset.id,
                spare_part_id=part.id,
                quantity_required=1 + (index % 3),
                note="Demo uyumluluk bağı",
                is_active=True,
            )
            db.session.add(link)
            db.session.flush()
            _register_record(link, f"asset-part-{asset.id}-{part.id}")

    if work_orders and spare_parts:
        completed_orders = [order for order in work_orders if order.status == "tamamlandi"][:20]
        for index, order in enumerate(completed_orders, start=1):
            part = spare_parts[(index * 2) % len(spare_parts)]
            usage = WorkOrderPartUsage(
                work_order_id=order.id,
                spare_part_id=part.id,
                quantity_used=1 + (index % 2),
                note="Demo iş emri parça kullanımı",
                consumed_from_stock_id=None,
            )
            db.session.add(usage)
            db.session.flush()
            _register_record(usage, f"wo-usage-{order.id}-{part.id}")

    if table_exists("assignment_record") and table_exists("assignment_recipient") and table_exists("assignment_item"):
        staff_by_airport = {}
        for airport in airports:
            scoped_staff = [u for u in users if u.havalimani_id == airport.id and u.rol in {ROLE_PERSONNEL, ROLE_MAINTENANCE}]
            if scoped_staff:
                staff_by_airport[airport.id] = scoped_staff

        for index, airport in enumerate(airports, start=1):
            scoped_staff = staff_by_airport.get(airport.id, [])
            scoped_assets = [asset for asset in assets if asset.havalimani_id == airport.id]
            if len(scoped_staff) < 2 or len(scoped_assets) < 3:
                continue

            assignment = AssignmentRecord(
                assignment_no=f"ASG-DEMO-{airport.kodu}-{index:02d}",
                assignment_date=today - timedelta(days=index),
                delivered_by_id=scoped_staff[0].id,
                delivered_by_name=scoped_staff[0].tam_ad,
                airport_id=airport.id,
                note="Demo zimmet kaydı",
                status="active" if index % 2 else "partially_returned",
                created_by_id=users[0].id if users else None,
            )
            db.session.add(assignment)
            db.session.flush()
            _register_record(assignment, assignment.assignment_no)

            recipient = AssignmentRecipient(
                assignment_id=assignment.id,
                user_id=scoped_staff[1].id,
            )
            db.session.add(recipient)
            db.session.flush()
            _register_record(recipient, f"recipient-{assignment.id}-{scoped_staff[1].id}")

            selected_assets = scoped_assets[:2]
            for item_index, asset in enumerate(selected_assets, start=1):
                item = AssignmentItem(
                    assignment_id=assignment.id,
                    material_id=asset.legacy_material_id,
                    asset_id=asset.id,
                    item_name=_clip_text(asset.legacy_material.ad if asset.legacy_material else (asset.equipment_template.name if asset.equipment_template else "Demo Ekipman"), 180, "Demo Ekipman"),
                    quantity=1,
                    unit="adet",
                    note="Demo zimmet kalemi",
                    returned_quantity=1 if (item_index == 1 and index % 2 == 0) else 0,
                    returned_at=get_tr_now() if (item_index == 1 and index % 2 == 0) else None,
                    returned_by_id=scoped_staff[0].id if (item_index == 1 and index % 2 == 0) else None,
                    return_note="Kısmi iade - demo" if (item_index == 1 and index % 2 == 0) else None,
                )
                db.session.add(item)
                db.session.flush()
                _register_record(item, f"assignment-item-{assignment.id}-{item_index}")

            history = AssignmentHistoryEntry(
                assignment_id=assignment.id,
                event_type="created",
                event_note="Demo zimmet oluşturuldu",
                created_by_id=users[0].id if users else None,
            )
            db.session.add(history)
            db.session.flush()
            _register_record(history, f"assignment-history-{assignment.id}")

    ppe_specs = [
        {
            "category": "Baş ve Yüz Koruması",
            "subcategory": "Baret",
            "item_name": "Baret",
            "brand": "MSA",
            "model_name": "V-Gard",
            "size_info": "M",
        },
        {
            "category": "El Koruması",
            "subcategory": "Mekanik Risk Eldiveni",
            "item_name": "Koruyucu Eldiven",
            "brand": "Ansell",
            "model_name": "HyFlex",
            "size_info": "L",
        },
        {
            "category": "Baş ve Yüz Koruması",
            "subcategory": "Koruyucu Gözlük",
            "item_name": "Koruyucu Gözlük",
            "brand": "Uvex",
            "model_name": "i-3",
            "size_info": "STD",
        },
        {
            "category": "Vücut Koruması",
            "subcategory": "Reflektif Yelek",
            "item_name": "Yüksek Görünürlük Yeleği",
            "brand": "3M",
            "model_name": "Reflect",
            "size_info": "XL",
        },
    ]
    ppe_pool_specs = [
        {
            "category": "Ayak Koruması",
            "subcategory": "Çelik Burunlu İş Botu",
            "item_name": "KKD Havuz Botu",
            "brand": "YDS",
            "model_name": "Rescue Pro",
            "size_info": "42",
            "quantity": 4,
        },
        {
            "category": "Solunum Koruması",
            "subcategory": "Toz Maskesi",
            "item_name": "KKD Havuz Maskesi",
            "brand": "3M",
            "model_name": "Aura 9332+",
            "size_info": "STD",
            "quantity": 12,
        },
    ]
    ppe_records_by_airport = {}
    for airport in airports:
        scoped_staff = [
            user
            for user in users
            if user.havalimani_id == airport.id and user.rol in {ROLE_PERSONNEL, ROLE_MAINTENANCE, ROLE_MANAGER}
        ]
        airport_ppe_records = []
        for index, staff in enumerate(scoped_staff[:4], start=1):
            spec = ppe_specs[(index - 1) % len(ppe_specs)]
            record = PPERecord(
                user_id=staff.id,
                airport_id=airport.id,
                assignment_id=None,
                ppe_assignment_id=None,
                category=spec["category"],
                subcategory=spec["subcategory"],
                item_name=spec["item_name"],
                brand=spec["brand"],
                model_name=spec["model_name"],
                brand_model=f"{spec['brand']} {spec['model_name']}",
                size_info=spec["size_info"],
                delivered_at=today - timedelta(days=rng.randint(5, 70)),
                quantity=1,
                status=rng.choice(["aktif", "aktif", "eksik", "hasarli"]),
                physical_condition=rng.choice(["iyi", "iyi", "hasarli"]),
                is_active=True,
                manufacturer_url="https://example.com/demo-kkd",
                description=f"{airport.kodu} demo KKD personel kaydı",
                created_by_id=users[0].id if users else None,
            )
            db.session.add(record)
            db.session.flush()
            _register_record(record, f"{airport.kodu}-{staff.id}-{spec['item_name']}")
            airport_ppe_records.append(record)

            event = PPERecordEvent(
                ppe_record_id=record.id,
                event_type="created",
                status_after=record.status,
                event_note="Demo seed ile oluşturuldu.",
                created_by_id=users[0].id if users else None,
            )
            db.session.add(event)
            db.session.flush()
            _register_record(event, f"ppe-event-{record.id}")

        for pool_index, spec in enumerate(ppe_pool_specs, start=1):
            pool_record = PPERecord(
                user_id=None,
                airport_id=airport.id,
                assignment_id=None,
                ppe_assignment_id=None,
                category=spec["category"],
                subcategory=spec["subcategory"],
                item_name=spec["item_name"],
                brand=spec["brand"],
                model_name=spec["model_name"],
                brand_model=f"{spec['brand']} {spec['model_name']}",
                size_info=spec["size_info"],
                delivered_at=today - timedelta(days=rng.randint(2, 30)),
                quantity=int(spec["quantity"]),
                status="aktif",
                physical_condition="iyi",
                is_active=True,
                manufacturer_url="https://example.com/demo-kkd",
                description=f"{airport.kodu} demo KKD havuz kaydı #{pool_index}",
                created_by_id=users[0].id if users else None,
            )
            db.session.add(pool_record)
            db.session.flush()
            _register_record(pool_record, f"{airport.kodu}-pool-{pool_index}")
            airport_ppe_records.append(pool_record)

            pool_event = PPERecordEvent(
                ppe_record_id=pool_record.id,
                event_type="created",
                status_after=pool_record.status,
                event_note="Demo seed ile havuz kaydı oluşturuldu.",
                created_by_id=users[0].id if users else None,
            )
            db.session.add(pool_event)
            db.session.flush()
            _register_record(pool_event, f"ppe-pool-event-{pool_record.id}")

        ppe_records_by_airport[airport.id] = airport_ppe_records

    if table_exists("ppe_assignment_record") and table_exists("ppe_assignment_item"):
        for index, airport in enumerate(airports, start=1):
            scoped_staff = [
                user
                for user in users
                if user.havalimani_id == airport.id and user.rol in {ROLE_PERSONNEL, ROLE_MAINTENANCE, ROLE_MANAGER}
            ]
            scoped_records = [
                row
                for row in ppe_records_by_airport.get(airport.id, [])
                if bool(getattr(row, "is_active", False)) and float(row.quantity or 0) > 0
            ]
            if len(scoped_staff) < 2 or len(scoped_records) < 2:
                continue

            assignment = PPEAssignmentRecord(
                assignment_no=f"KKD-DEMO-{airport.kodu}-{index:02d}",
                assignment_date=today - timedelta(days=index),
                delivered_by_id=scoped_staff[0].id,
                delivered_by_name=scoped_staff[0].tam_ad,
                recipient_user_id=scoped_staff[1].id,
                airport_id=airport.id,
                note="Demo KKD tahsis kaydı",
                status="active",
                created_by_id=users[0].id if users else None,
            )
            db.session.add(assignment)
            db.session.flush()
            _register_record(assignment, assignment.assignment_no)

            selected_records = [scoped_records[0]]
            pool_record = next((row for row in scoped_records if row.user_id is None), None)
            if pool_record is not None and pool_record.id != selected_records[0].id:
                selected_records.append(pool_record)
            if len(selected_records) < 2:
                selected_records.extend(scoped_records[1:2])
            for item_index, record in enumerate(selected_records, start=1):
                quantity = float(min(max(int(record.quantity or 1), 1), 2))
                item = PPEAssignmentItem(
                    assignment_id=assignment.id,
                    ppe_record_id=record.id,
                    item_name=record.item_name,
                    category=record.category,
                    subcategory=record.subcategory,
                    brand=record.brand,
                    model_name=record.model_name,
                    serial_no=record.serial_no,
                    size_info=record.size_info,
                    quantity=quantity,
                    unit="adet",
                    note="Demo KKD tahsis kalemi",
                )
                db.session.add(item)
                db.session.flush()
                _register_record(item, f"ppe-assignment-item-{assignment.id}-{item_index}")

            linked_pool = next((row for row in selected_records if row.user_id is None), None)
            if linked_pool is not None:
                linked_pool.ppe_assignment_id = assignment.id

    db.session.commit()
    summary = _summary()
    _set_platform_demo_state(True, "seeded", summary=summary)
    db.session.commit()
    _seed_homepage_demo_if_available()
    log_kaydet(
        "Demo Veri",
        "Demo seed verileri oluşturuldu.",
        event_key="demo.seed.create",
        target_model="DemoSeedRecord",
        outcome="success",
    )
    return summary
