import random
import json
import re
from html import unescape
from pathlib import Path
from datetime import timedelta

from flask import current_app
from sqlalchemy import false, or_

from decorators import ROLE_ADMIN, ROLE_AIRPORT_MANAGER, ROLE_EDITOR, ROLE_MAINTENANCE, ROLE_MANAGER, ROLE_OWNER, ROLE_PERSONNEL, ROLE_READONLY, ROLE_WAREHOUSE
from extensions import db, log_kaydet, table_exists
from models import (
    AssignmentRecipient,
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
    MaintenancePlan,
    MaintenanceTriggerRule,
    Malzeme,
    MeterDefinition,
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
    return bool(current_app.config.get("DEMO_TOOLS_ENABLED", False))


def _guard_demo_tools():
    if not demo_tools_enabled():
        raise RuntimeError("Demo veri araçları bu ortamda kapalı.")
    if not table_exists("demo_seed_record"):
        if current_app.config.get("AUTO_CREATE_TABLES", False):
            db.create_all()
        else:
            raise RuntimeError("Demo seed tablosu eksik. Önce migration çalıştırın.")


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


def get_platform_demo_status():
    if not table_exists("site_ayarlari") or not table_exists("demo_seed_record"):
        return {"active": False, "summary": _summary(), "updated_at": "-", "action": "unavailable"}
    ayarlar = SiteAyarlari.query.first()
    meta = _load_site_meta(ayarlar)
    state = meta.get(PLATFORM_DEMO_STATE_KEY, {}) if isinstance(meta.get(PLATFORM_DEMO_STATE_KEY), dict) else {}
    return {
        "active": bool(state.get("active")),
        "summary": _summary(),
        "updated_at": state.get("updated_at", "-"),
        "action": state.get("action", "idle"),
    }


def platform_demo_is_active():
    status = get_platform_demo_status()
    return bool(status.get("active"))


def demo_record_ids(model_name):
    if not table_exists("demo_seed_record"):
        return set()
    return {
        int(row.record_id)
        for row in DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG, model_name=model_name).all()
        if row.record_id is not None
    }


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
        return None
    if not table_exists("demo_seed_record"):
        return None
    try:
        from homepage_demo import clear_homepage_demo_data

        return clear_homepage_demo_data()
    except RuntimeError:
        return None
    except Exception:
        db.session.rollback()
        return None


def clear_demo_data():
    _guard_demo_tools()
    if not table_exists("demo_seed_record"):
        return {"deleted": 0}

    demo_template_ids = demo_record_ids("EquipmentTemplate")
    demo_form_ids = demo_record_ids("MaintenanceFormTemplate")
    demo_asset_ids = demo_record_ids("InventoryAsset")
    demo_user_ids = demo_record_ids("Kullanici")
    demo_spare_part_ids = demo_record_ids("SparePart")
    demo_work_order_ids = demo_record_ids("WorkOrder")
    demo_stock_ids = demo_record_ids("SparePartStock")

    with db.session.no_autoflush:
        # Demo bakım formuna referans veren, fakat seed kaydı olmayan şablonlar
        # maintenance_form_template silinirken FK hatasına neden olabiliyor.
        if demo_form_ids:
            extra_templates = EquipmentTemplate.query.filter(
                EquipmentTemplate.default_maintenance_form_id.in_(sorted(demo_form_ids))
            )
            if demo_template_ids:
                extra_templates = extra_templates.filter(~EquipmentTemplate.id.in_(sorted(demo_template_ids)))
            extra_template_ids = {tpl.id for tpl in extra_templates.all()}
            if extra_template_ids:
                demo_template_ids = set(demo_template_ids) | extra_template_ids

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

        # Bridge/usage kayıtları DemoSeedRecord dışında kalabiliyor.
        # Demo varlıklara/parçalara bağlı bağımlılıkları önce temizle.
        if table_exists("asset_spare_part_link") and (demo_asset_ids or demo_spare_part_ids):
            clauses = []
            if demo_asset_ids:
                clauses.append(AssetSparePartLink.asset_id.in_(sorted(demo_asset_ids)))
            if demo_spare_part_ids:
                clauses.append(AssetSparePartLink.spare_part_id.in_(sorted(demo_spare_part_ids)))
            AssetSparePartLink.query.filter(or_(*clauses)).delete(synchronize_session=False)

        if table_exists("work_order_part_usage") and (demo_work_order_ids or demo_spare_part_ids or demo_stock_ids):
            clauses = []
            if demo_work_order_ids:
                clauses.append(WorkOrderPartUsage.work_order_id.in_(sorted(demo_work_order_ids)))
            if demo_spare_part_ids:
                clauses.append(WorkOrderPartUsage.spare_part_id.in_(sorted(demo_spare_part_ids)))
            if demo_stock_ids:
                clauses.append(WorkOrderPartUsage.consumed_from_stock_id.in_(sorted(demo_stock_ids)))
            WorkOrderPartUsage.query.filter(or_(*clauses)).delete(synchronize_session=False)

    model_map = {
        "CalibrationRecord": CalibrationRecord,
        "CalibrationSchedule": CalibrationSchedule,
        "ConsumableStockMovement": ConsumableStockMovement,
        "ConsumableItem": ConsumableItem,
        "MaintenanceTriggerRule": MaintenanceTriggerRule,
        "MeterDefinition": MeterDefinition,
        "MaintenancePlan": MaintenancePlan,
        "WorkOrder": WorkOrder,
        "InventoryAsset": InventoryAsset,
        "Malzeme": Malzeme,
        "Kutu": Kutu,
        "SparePartStock": SparePartStock,
        "SparePart": SparePart,
        "Supplier": Supplier,
        "MaintenanceFormField": MaintenanceFormField,
        "MaintenanceFormTemplate": MaintenanceFormTemplate,
        "EquipmentTemplate": EquipmentTemplate,
        "Kullanici": Kullanici,
        "Havalimani": Havalimani,
    }
    delete_order = [
        "CalibrationRecord",
        "CalibrationSchedule",
        "ConsumableStockMovement",
        "ConsumableItem",
        "MaintenanceTriggerRule",
        "MeterDefinition",
        "MaintenancePlan",
        "WorkOrder",
        "InventoryAsset",
        "Malzeme",
        "Kutu",
        "SparePartStock",
        "SparePart",
        "Supplier",
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
            for row in rows:
                obj = db.session.get(model, row.record_id)
                if obj is not None:
                    db.session.delete(obj)
                    deleted += 1
    DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG).delete(synchronize_session=False)
    _set_platform_demo_state(False, "cleared", summary={"deleted": deleted})
    db.session.commit()
    homepage_result = _clear_homepage_demo_if_available() or {}
    return {"deleted": deleted, "homepage_deleted": int(homepage_result.get("deleted") or 0)}


def seed_demo_data(reset=False):
    _guard_demo_tools()
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
                ad=_clip_text(template.name, 100, "Demo Ekipman"),
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
