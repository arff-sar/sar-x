from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import and_, func
from sqlalchemy.orm import joinedload

from decorators import (
    CANONICAL_ROLE_SYSTEM,
    CANONICAL_ROLE_TEAM_LEAD,
    CANONICAL_ROLE_TEAM_MEMBER,
    get_effective_role,
    has_permission,
)
from extensions import table_exists
from models import (
    AssetMeterReading,
    CalibrationSchedule,
    ConsumableItem,
    ConsumableStockMovement,
    Havalimani,
    InventoryAsset,
    MaintenanceTriggerRule,
    SparePartStock,
    WorkOrder,
    get_tr_now,
)
from services.text_normalization_service import turkish_equals
from demo_data import apply_platform_demo_scope, demo_record_ids, platform_demo_is_active

OPEN_WORK_ORDER_STATUSES = {"acik", "atandi", "islemde", "beklemede_parca", "beklemede_onay"}
REPORT_DEFINITIONS = {
    "maintenance": {"label": "Bakım Raporları"},
    "inventory": {"label": "Envanter Durum Raporu"},
    "workorders": {"label": "İş Emri Performansı"},
    "parts": {"label": "Yedek Parça Stok Raporu"},
    "consumables_usage": {"label": "Sarf Tüketim Raporu"},
    "consumables_stock": {"label": "Sarf Stok Durumu"},
    "calibration": {"label": "Kalibrasyon Raporu"},
    "warranty": {"label": "Garanti Bitiş Raporu"},
    "lifecycle": {"label": "Lifecycle Durum Raporu"},
    "airports": {"label": "Havalimanı Bazlı Özet"},
    "qr": {"label": "QR / Asset Kod Raporu"},
}


def report_tabs():
    return [{"key": key, "label": item["label"]} for key, item in REPORT_DEFINITIONS.items()]


def parse_report_filters(args):
    trend_days = args.get("trend_days", type=int) or 30
    if trend_days not in {7, 30, 90}:
        trend_days = 30
    return {
        "airport_id": args.get("airport_id", type=int),
        "date_from": _parse_date(args.get("date_from")),
        "date_to": _parse_date(args.get("date_to")),
        "category": (args.get("category") or "").strip(),
        "maintenance_state": (args.get("maintenance_state") or "").strip(),
        "work_order_type": (args.get("work_order_type") or "").strip(),
        "priority": (args.get("priority") or "").strip(),
        "stock_level": (args.get("stock_level") or "").strip(),
        "asset_status": (args.get("asset_status") or "").strip(),
        "warranty_state": (args.get("warranty_state") or "").strip(),
        "calibration_state": (args.get("calibration_state") or "").strip(),
        "assignee_id": args.get("assignee_id", type=int),
        "demo_scope": (args.get("demo_scope") or "all").strip() or "all",
        "trend_days": trend_days,
    }


def filter_options(user):
    if _can_view_all(user):
        airport_query = Havalimani.query.filter_by(is_deleted=False)
        airport_query = apply_platform_demo_scope(airport_query, "Havalimani", Havalimani.id)
        airports = airport_query.order_by(Havalimani.kodu.asc()).all()
    else:
        airport_query = Havalimani.query.filter_by(is_deleted=False, id=getattr(user, "havalimani_id", None))
        airport_query = apply_platform_demo_scope(airport_query, "Havalimani", Havalimani.id)
        airports = airport_query.order_by(Havalimani.kodu.asc()).all()

    user_map = {}
    for airport in airports:
        for person in airport.personeller:
            if not person.is_deleted:
                user_map[person.id] = person

    categories = sorted(
        {
            asset.equipment_template.category
            for asset in _asset_rows(user, {"demo_scope": "all"})
            if asset.equipment_template and asset.equipment_template.category
        }
    )

    return {
        "airports": airports,
        "categories": categories,
        "users": sorted(user_map.values(), key=lambda item: item.tam_ad or ""),
        "trend_days": [7, 30, 90],
        "asset_statuses": ["active", "in_maintenance", "out_of_service", "disposed", "transferred", "calibration_due"],
    }


def build_dashboard_kpis(user, filters, snapshot=None):
    snapshot = snapshot or build_operational_snapshot(user, filters)
    kpis = {
        "total_assets": _kpi_item("Toplam Ekipman", snapshot["totals"]["total_assets"], snapshot["trends"]["total_assets"], "BİRİM"),
        "faulty_assets": _kpi_item("Arızalı Malzeme", snapshot["totals"]["faulty_assets"], snapshot["trends"]["faulty_assets"], "ARIZA"),
        "overdue_maintenance": _kpi_item("Geciken Bakım", snapshot["totals"]["overdue_maintenance"], snapshot["trends"]["overdue_maintenance"], "GECİKEN"),
        "open_work_orders": _kpi_item("Açık İş Emri", snapshot["totals"]["open_work_orders"], snapshot["trends"]["open_work_orders"], "İŞ EMRİ"),
        "low_stock": _kpi_item("Düşük Stok Parça", snapshot["totals"]["low_stock"], snapshot["trends"]["low_stock"], "STOK"),
        "meter_upcoming": _kpi_item("Sayaç Yaklaşan Bakım", snapshot["totals"]["meter_upcoming"], snapshot["trends"]["meter_upcoming"], "SAYAÇ"),
        "auto_work_orders": _kpi_item("Otomatik İş Emri", snapshot["totals"]["auto_work_orders"], snapshot["trends"]["auto_work_orders"], "OTOMATİK"),
        "child_faults": _kpi_item("Alt Bileşen Arızası", snapshot["totals"]["child_faults"], snapshot["trends"]["child_faults"], "CHILD"),
        "calibration_overdue": _kpi_item("Kalibrasyon Gecikmesi", snapshot["totals"]["calibration_overdue"], snapshot["trends"]["calibration_overdue"], "KALİBRASYON"),
        "calibration_upcoming": _kpi_item("Yaklaşan Kalibrasyon", snapshot["totals"]["calibration_upcoming"], snapshot["trends"]["calibration_upcoming"], "KALİBRASYON"),
        "warranty_expiring": _kpi_item("Garanti Bitişi Yaklaşan", snapshot["totals"]["warranty_expiring"], snapshot["trends"]["warranty_expiring"], "GARANTİ"),
        "low_consumables": _kpi_item("Düşük Sarf Stoğu", snapshot["totals"]["low_consumables"], snapshot["trends"]["low_consumables"], "SARF"),
        "critical_consumables": _kpi_item("Kritik Sarf Stoğu", snapshot["totals"]["critical_consumables"], snapshot["trends"]["critical_consumables"], "SARF"),
        "out_of_service_critical": _kpi_item("Kritik Servis Dışı", snapshot["totals"]["out_of_service_critical"], snapshot["trends"]["out_of_service_critical"], "SERVİS DIŞI"),
    }
    return {"kpis": kpis, "snapshot": snapshot}


def build_operational_snapshot(user, filters):
    assets = _asset_rows(user, filters)
    orders = _work_order_rows(user, filters)
    stocks = _stock_rows(user, filters)
    consumables = _consumable_rows(user, filters)
    trend_days = int(filters.get("trend_days") or 30)

    total_assets = len(assets)
    active_assets = sum(1 for asset in assets if asset.status == "aktif")
    faulty_assets = sum(1 for asset in assets if asset.status == "arizali")
    maintenance_assets = sum(1 for asset in assets if asset.status == "bakimda")
    today = get_tr_now().date()
    overdue_maintenance = sum(1 for asset in assets if asset.next_maintenance_date and asset.next_maintenance_date < today and asset.status != "pasif")
    upcoming_maintenance = sum(1 for asset in assets if asset.next_maintenance_date and today <= asset.next_maintenance_date <= (today + timedelta(days=15)))
    open_work_orders = sum(1 for order in orders if order.status in OPEN_WORK_ORDER_STATUSES)
    low_stock = sum(1 for stock in stocks if stock.is_low_stock())
    critical_stock = sum(
        1
        for stock in stocks
        if stock.spare_part and stock.available_quantity <= float(stock.spare_part.critical_level or 0)
    )
    calibration_overdue = sum(1 for asset in assets if asset.next_calibration_date and asset.next_calibration_date < today and asset.status != "pasif")
    calibration_upcoming = sum(1 for asset in assets if asset.next_calibration_date and today <= asset.next_calibration_date <= (today + timedelta(days=15)))
    warranty_expiring = sum(1 for asset in assets if asset.warranty_end_date and today <= asset.warranty_end_date <= (today + timedelta(days=30)))
    child_faults = sum(1 for asset in assets if asset.parent_asset_id and asset.status in {"arizali", "bakimda"})
    auto_work_orders = sum(1 for order in orders if order.source_type == "meter_trigger" and order.status in OPEN_WORK_ORDER_STATUSES)
    avg_close_hours = _average_close_hours(orders)
    meter_upcoming = _meter_upcoming_count(assets, filters)
    low_consumables = sum(1 for row in consumables if row["available_quantity"] <= float(row["min_stock_level"] or 0))
    critical_consumables = sum(1 for row in consumables if row["available_quantity"] <= float(row["critical_level"] or 0))
    out_of_service_critical = sum(1 for asset in assets if asset.is_critical and asset.lifecycle_status == "out_of_service")

    category_faults = Counter(
        (asset.equipment_template.category or "Tanımsız")
        for asset in assets
        if asset.equipment_template and asset.status in {"arizali", "bakimda"}
    )
    airport_open_orders = Counter(
        (order.asset.airport.ad if order.asset and order.asset.airport else "Tanımsız")
        for order in orders
        if order.status in OPEN_WORK_ORDER_STATUSES
    )
    status_donut = {
        "labels": ["Aktif", "Arızalı", "Bakımda"],
        "values": [active_assets, faulty_assets, maintenance_assets],
    }
    trend_series = _build_trend_series(orders, trend_days)

    return {
        "totals": {
            "total_assets": total_assets,
            "active_assets": active_assets,
            "faulty_assets": faulty_assets,
            "maintenance_assets": maintenance_assets,
            "overdue_maintenance": overdue_maintenance,
            "upcoming_maintenance": upcoming_maintenance,
            "open_work_orders": open_work_orders,
            "avg_close_hours": avg_close_hours,
            "low_stock": low_stock,
            "critical_stock": critical_stock,
            "calibration_overdue": calibration_overdue,
            "calibration_upcoming": calibration_upcoming,
            "warranty_expiring": warranty_expiring,
            "meter_upcoming": meter_upcoming,
            "child_faults": child_faults,
            "auto_work_orders": auto_work_orders,
            "low_consumables": low_consumables,
            "critical_consumables": critical_consumables,
            "out_of_service_critical": out_of_service_critical,
        },
        "ratios": {
            "active_ratio": _ratio(active_assets, total_assets),
            "faulty_ratio": _ratio(faulty_assets, total_assets),
            "maintenance_ratio": _ratio(maintenance_assets, total_assets),
        },
        "trends": _build_trend_map(
            assets,
            orders,
            stocks,
            trend_days,
            meter_upcoming,
            overdue_maintenance,
            open_work_orders,
            low_stock,
            child_faults,
            calibration_overdue,
            total_assets,
            faulty_assets,
            auto_work_orders,
            calibration_upcoming=calibration_upcoming,
            warranty_expiring=warranty_expiring,
            low_consumables=low_consumables,
            critical_consumables=critical_consumables,
            out_of_service_critical=out_of_service_critical,
        ),
        "charts": {
            "status_donut": status_donut,
            "work_order_line": trend_series,
            "category_bar": {
                "labels": [item[0] for item in category_faults.most_common(5)],
                "values": [item[1] for item in category_faults.most_common(5)],
            },
            "airport_bar": {
                "labels": [item[0] for item in airport_open_orders.most_common(5)],
                "values": [item[1] for item in airport_open_orders.most_common(5)],
            },
            "consumable_bar": {
                "labels": [row["title"] for row in consumables[:5]],
                "values": [row["available_quantity"] for row in consumables[:5]],
            },
        },
        "top_fault_categories": category_faults.most_common(5),
        "top_airports": airport_open_orders.most_common(5),
        "stale_critical_orders": sorted(
            [
                order for order in orders
                if order.priority == "kritik" and order.status in OPEN_WORK_ORDER_STATUSES
            ],
            key=lambda row: row.opened_at or get_tr_now(),
            reverse=False,
        )[:8],
        "filters": filters,
    }


def build_report_dataset(user, report_key, filters):
    assets = _asset_rows(user, filters)
    orders = _work_order_rows(user, filters)
    stocks = _stock_rows(user, filters)
    consumables = _consumable_rows(user, filters)
    calibration_rows = _calibration_rows(user, filters)
    airports = _visible_airports(user)

    if report_key == "maintenance":
        rows = [
            {
                "Havalimanı": asset.airport.ad if asset.airport else "-",
                "Asset Code": asset.asset_code or "-",
                "Ekipman": asset.equipment_template.name if asset.equipment_template else "-",
                "Kategori": asset.equipment_template.category if asset.equipment_template else "-",
                "Bakım Durumu": asset.maintenance_state or "-",
                "Son Bakım": _fmt_date(asset.last_maintenance_date),
                "Sonraki Bakım": _fmt_date(asset.next_maintenance_date),
                "Durum": asset.status,
                "Demo": "Evet" if _is_demo("InventoryAsset", asset.id) else "Hayır",
            }
            for asset in sorted(assets, key=lambda row: row.next_maintenance_date or date.max)
        ]
    elif report_key == "inventory":
        rows = [
            {
                "Havalimanı": asset.airport.ad if asset.airport else "-",
                "Asset Code": asset.asset_code or "-",
                "Seri No": asset.serial_no or "-",
                "Ekipman": asset.equipment_template.name if asset.equipment_template else "-",
                "Kategori": asset.equipment_template.category if asset.equipment_template else "-",
                "Durum": asset.status,
                "Bakım Durumu": asset.maintenance_state or "-",
                "Konum": asset.depot_location or "-",
                "Demo": "Evet" if _is_demo("InventoryAsset", asset.id) else "Hayır",
            }
            for asset in sorted(assets, key=lambda row: (row.airport.ad if row.airport else "", row.asset_code or ""))
        ]
    elif report_key == "workorders":
        rows = [
            {
                "İş Emri": order.work_order_no,
                "Havalimanı": order.asset.airport.ad if order.asset and order.asset.airport else "-",
                "Ekipman": order.asset.equipment_template.name if order.asset and order.asset.equipment_template else "-",
                "Tür": order.work_order_type,
                "Öncelik": order.priority,
                "Durum": order.status,
                "Açılış": _fmt_datetime(order.opened_at),
                "Kapanış": _fmt_datetime(order.completed_at),
                "Kapanma Süresi (saat)": _close_hours(order),
                "Atanan": order.assigned_user.tam_ad if order.assigned_user else "-",
                "Demo": "Evet" if _is_demo("WorkOrder", order.id) else "Hayır",
            }
            for order in sorted(orders, key=lambda row: row.opened_at or get_tr_now(), reverse=True)
        ]
    elif report_key == "parts":
        rows = [
            {
                "Parça Kodu": stock.spare_part.part_code if stock.spare_part else "-",
                "Parça": stock.spare_part.title if stock.spare_part else "-",
                "Havalimanı": stock.airport_stock.ad if stock.airport_stock else "-",
                "Mevcut": round(stock.available_quantity, 2),
                "Reorder": round(float(stock.reorder_point or 0), 2),
                "Kritik Seviye": round(float(stock.spare_part.critical_level if stock.spare_part else 0), 2),
                "Durum": _stock_label(stock),
                "Demo": "Evet" if _is_demo("SparePartStock", stock.id) else "Hayır",
            }
            for stock in sorted(stocks, key=lambda row: (row.airport_stock.ad if row.airport_stock else "", row.spare_part.title if row.spare_part else ""))
        ]
    elif report_key == "consumables_usage":
        rows = [
            {
                "Kod": row["code"],
                "Sarf": row["title"],
                "Kategori": row["category"],
                "Havalimanı": row["airport_name"],
                "Mevcut": row["available_quantity"],
                "Min": row["min_stock_level"],
                "Kritik": row["critical_level"],
                "Durum": row["stock_label"],
            }
            for row in consumables
        ]
    elif report_key == "consumables_stock":
        rows = [
            {
                "Kod": row["code"],
                "Sarf": row["title"],
                "Kategori": row["category"],
                "Birim": row["unit"],
                "Havalimanı": row["airport_name"],
                "Mevcut": row["available_quantity"],
                "Son Hareket": row["last_movement_type"],
                "Durum": row["stock_label"],
            }
            for row in consumables
        ]
    elif report_key == "calibration":
        rows = calibration_rows
    elif report_key == "warranty":
        rows = [
            {
                "Asset Code": asset.asset_code or "-",
                "Ekipman": asset.equipment_template.name if asset.equipment_template else "-",
                "Havalimanı": asset.airport.ad if asset.airport else "-",
                "Garanti Sonu": _fmt_date(asset.warranty_end_date),
                "Garanti Durumu": "Kapsamda" if asset.under_warranty else "Dışı",
                "Lifecycle": asset.lifecycle_status,
            }
            for asset in assets
            if asset.warranty_end_date
        ]
    elif report_key == "lifecycle":
        rows = [
            {
                "Asset Code": asset.asset_code or "-",
                "Ekipman": asset.equipment_template.name if asset.equipment_template else "-",
                "Havalimanı": asset.airport.ad if asset.airport else "-",
                "Lifecycle": asset.lifecycle_status,
                "Durum": asset.status,
                "Garanti": "Kapsamda" if asset.under_warranty else "Yok / Bitti",
                "Kalibrasyon": _fmt_date(asset.next_calibration_date),
            }
            for asset in assets
        ]
    elif report_key == "airports":
        rows = []
        for airport in airports:
            airport_assets = [asset for asset in assets if asset.havalimani_id == airport.id]
            airport_orders = [order for order in orders if order.asset and order.asset.havalimani_id == airport.id]
            airport_stocks = [stock for stock in stocks if stock.airport_id == airport.id]
            rows.append(
                {
                    "Havalimanı": airport.ad,
                    "Toplam Ekipman": len(airport_assets),
                    "Arızalı": sum(1 for asset in airport_assets if asset.status == "arizali"),
                    "Bakımda": sum(1 for asset in airport_assets if asset.status == "bakimda"),
                    "Açık İş Emri": sum(1 for order in airport_orders if order.status in OPEN_WORK_ORDER_STATUSES),
                    "Düşük Stok": sum(1 for stock in airport_stocks if stock.is_low_stock()),
                }
            )
    elif report_key == "qr":
        rows = [
            {
                "Asset Code": asset.asset_code or "-",
                "Seri No": asset.serial_no or "-",
                "Havalimanı": asset.qr_label_airport_name,
                "QR Payload": asset.qr_code or "-",
                "Oluşturma": _fmt_datetime(asset.created_at),
                "Demo": "Evet" if _is_demo("InventoryAsset", asset.id) else "Hayır",
            }
            for asset in sorted(assets, key=lambda row: row.id or 0)
        ]
    else:
        rows = []

    return {
        "key": report_key,
        "label": REPORT_DEFINITIONS.get(report_key, {}).get("label", report_key),
        "rows": rows,
        "columns": list(rows[0].keys()) if rows else [],
    }


def manager_summary(user, filters):
    snapshot = build_operational_snapshot(user, filters)
    totals = snapshot["totals"]
    red_flags = []
    if totals["overdue_maintenance"]:
        red_flags.append(f"{totals['overdue_maintenance']} geciken bakım kaydı var.")
    if totals["critical_stock"]:
        red_flags.append(f"{totals['critical_stock']} kritik stok kalemi acil takip istiyor.")
    if totals["calibration_overdue"]:
        red_flags.append(f"{totals['calibration_overdue']} kalibrasyon gecikmesi mevcut.")
    if totals["critical_consumables"]:
        red_flags.append(f"{totals['critical_consumables']} kritik sarf stoğu acil takip istiyor.")
    if totals["warranty_expiring"]:
        red_flags.append(f"{totals['warranty_expiring']} ekipmanın garanti bitişi yaklaşıyor.")
    if not red_flags:
        red_flags.append("Kritik seviyede kırmızı alan görünmüyor.")

    return {
        "snapshot": snapshot,
        "red_flags": red_flags,
        "risk_categories": snapshot["top_fault_categories"],
        "top_airports": snapshot["top_airports"],
        "stale_critical_orders": snapshot["stale_critical_orders"],
    }


def _asset_rows(user, filters):
    query = InventoryAsset.query.filter_by(is_deleted=False).options(
        joinedload(InventoryAsset.equipment_template),
        joinedload(InventoryAsset.airport),
        joinedload(InventoryAsset.operational_state),
    )
    if not _can_view_all(user):
        query = query.filter_by(havalimani_id=user.havalimani_id)
    rows = query.all()
    demo_scope = (filters.get("demo_scope") or "all") if isinstance(filters, dict) else "all"
    rows = _filter_demo_rows(rows, "InventoryAsset", demo_scope)
    if filters.get("airport_id"):
        rows = [row for row in rows if row.havalimani_id == filters["airport_id"]]
    if filters.get("category"):
        rows = [
            row for row in rows
            if row.equipment_template and turkish_equals(row.equipment_template.category, filters["category"])
        ]
    if filters.get("maintenance_state"):
        rows = [row for row in rows if (row.maintenance_state or "") == filters["maintenance_state"]]
    if filters.get("asset_status"):
        rows = [row for row in rows if row.lifecycle_status == filters["asset_status"]]
    if filters.get("warranty_state") == "under":
        rows = [row for row in rows if row.under_warranty]
    elif filters.get("warranty_state") == "expired":
        rows = [row for row in rows if row.warranty_end_date and row.warranty_end_date < get_tr_now().date()]
    if filters.get("calibration_state") == "overdue":
        rows = [row for row in rows if row.next_calibration_date and row.next_calibration_date < get_tr_now().date()]
    elif filters.get("calibration_state") == "upcoming":
        rows = [row for row in rows if row.next_calibration_date and get_tr_now().date() <= row.next_calibration_date <= (get_tr_now().date() + timedelta(days=15))]
    if filters.get("date_from"):
        rows = [row for row in rows if row.created_at and row.created_at.date() >= filters["date_from"]]
    if filters.get("date_to"):
        rows = [row for row in rows if row.created_at and row.created_at.date() <= filters["date_to"]]
    return rows


def _work_order_rows(user, filters):
    query = WorkOrder.query.filter_by(is_deleted=False).options(
        joinedload(WorkOrder.asset).joinedload(InventoryAsset.airport),
        joinedload(WorkOrder.asset).joinedload(InventoryAsset.equipment_template),
        joinedload(WorkOrder.assigned_user),
    )
    if not _can_view_all(user):
        query = query.join(InventoryAsset).filter(InventoryAsset.havalimani_id == user.havalimani_id)
    rows = query.all()
    demo_scope = (filters.get("demo_scope") or "all") if isinstance(filters, dict) else "all"
    rows = _filter_demo_rows(rows, "WorkOrder", demo_scope)
    if filters.get("airport_id"):
        rows = [row for row in rows if row.asset and row.asset.havalimani_id == filters["airport_id"]]
    if filters.get("category"):
        rows = [
            row for row in rows
            if row.asset and row.asset.equipment_template and turkish_equals(row.asset.equipment_template.category, filters["category"])
        ]
    if filters.get("work_order_type"):
        rows = [row for row in rows if row.work_order_type == filters["work_order_type"]]
    if filters.get("priority"):
        rows = [row for row in rows if row.priority == filters["priority"]]
    if filters.get("assignee_id"):
        rows = [row for row in rows if row.assigned_user_id == filters["assignee_id"]]
    if filters.get("date_from"):
        rows = [row for row in rows if row.opened_at and row.opened_at.date() >= filters["date_from"]]
    if filters.get("date_to"):
        rows = [row for row in rows if row.opened_at and row.opened_at.date() <= filters["date_to"]]
    return rows


def _stock_rows(user, filters):
    query = SparePartStock.query.filter_by(is_deleted=False, is_active=True).options(
        joinedload(SparePartStock.spare_part),
        joinedload(SparePartStock.airport_stock),
    )
    if not _can_view_all(user):
        query = query.filter_by(airport_id=user.havalimani_id)
    rows = query.all()
    demo_scope = (filters.get("demo_scope") or "all") if isinstance(filters, dict) else "all"
    rows = _filter_demo_rows(rows, "SparePartStock", demo_scope)
    if filters.get("airport_id"):
        rows = [row for row in rows if row.airport_id == filters["airport_id"]]
    if filters.get("stock_level") == "low":
        rows = [row for row in rows if row.is_low_stock()]
    elif filters.get("stock_level") == "critical":
        rows = [
            row for row in rows
            if row.spare_part and row.available_quantity <= float(row.spare_part.critical_level or 0)
        ]
    if filters.get("date_from"):
        rows = [row for row in rows if row.created_at and row.created_at.date() >= filters["date_from"]]
    if filters.get("date_to"):
        rows = [row for row in rows if row.created_at and row.created_at.date() <= filters["date_to"]]
    return rows


def _consumable_rows(user, filters):
    if not table_exists("consumable_item") or not table_exists("consumable_stock_movement"):
        return []
    items = ConsumableItem.query.filter_by(is_deleted=False, is_active=True).order_by(ConsumableItem.title.asc()).all()
    movements = ConsumableStockMovement.query.filter_by(is_deleted=False).order_by(ConsumableStockMovement.created_at.asc()).all()
    if not _can_view_all(user):
        movements = [row for row in movements if row.airport_id == user.havalimani_id]
    if filters.get("airport_id"):
        movements = [row for row in movements if row.airport_id == filters["airport_id"]]
    demo_scope = (filters.get("demo_scope") or "all") if isinstance(filters, dict) else "all"
    items = _filter_demo_rows(items, "ConsumableItem", demo_scope)

    grouped = defaultdict(list)
    for movement in movements:
        grouped[(movement.consumable_id, movement.airport_id)].append(movement)

    rows = []
    visible_airports = {airport.id: airport for airport in _visible_airports(user)}
    for item in items:
        for (consumable_id, airport_id), bucket in grouped.items():
            if consumable_id != item.id:
                continue
            available = 0.0
            for movement in bucket:
                sign = 1 if movement.movement_type in {"in", "adjust", "transfer"} else -1
                available += sign * float(movement.quantity or 0)
            airport = visible_airports.get(airport_id)
            rows.append(
                {
                    "code": item.code,
                    "title": item.title,
                    "category": item.category or "-",
                    "unit": item.unit or "adet",
                    "airport_id": airport_id,
                    "airport_name": airport.ad if airport else "-",
                    "available_quantity": round(available, 2),
                    "min_stock_level": float(item.min_stock_level or 0),
                    "critical_level": float(item.critical_level or 0),
                    "last_movement_type": bucket[-1].movement_type if bucket else "-",
                    "stock_label": _consumable_stock_label(available, item),
                }
            )
    return rows


def _calibration_rows(user, filters):
    if not table_exists("calibration_schedule"):
        return []
    assets = _asset_rows(user, filters)
    asset_ids = {asset.id for asset in assets}
    schedules = CalibrationSchedule.query.filter_by(is_deleted=False, is_active=True).all()
    rows = []
    today = get_tr_now().date()
    for schedule in schedules:
        if schedule.asset_id not in asset_ids:
            continue
        asset = schedule.asset
        next_date = asset.next_calibration_date
        status = "normal"
        if next_date and next_date < today:
            status = "gecikmis"
        elif next_date and next_date <= (today + timedelta(days=schedule.warning_days or 15)):
            status = "yaklasan"
        if filters.get("calibration_state") == "overdue" and status != "gecikmis":
            continue
        if filters.get("calibration_state") == "upcoming" and status != "yaklasan":
            continue
        rows.append(
            {
                "Asset Code": asset.asset_code or "-",
                "Ekipman": asset.equipment_template.name if asset.equipment_template else "-",
                "Havalimanı": asset.airport.ad if asset.airport else "-",
                "Sağlayıcı": schedule.provider or "-",
                "Son Kalibrasyon": _fmt_date(asset.last_calibration_date),
                "Sonraki Kalibrasyon": _fmt_date(next_date),
                "Durum": status,
            }
        )
    return rows


def _visible_airports(user):
    if _can_view_all(user):
        query = Havalimani.query.filter_by(is_deleted=False)
        query = apply_platform_demo_scope(query, "Havalimani", Havalimani.id)
        return query.order_by(Havalimani.kodu.asc()).all()
    query = Havalimani.query.filter_by(is_deleted=False, id=getattr(user, "havalimani_id", None))
    query = apply_platform_demo_scope(query, "Havalimani", Havalimani.id)
    return query.order_by(Havalimani.kodu.asc()).all()


def _can_view_all(user):
    actor_role = get_effective_role(user)
    if actor_role == CANONICAL_ROLE_SYSTEM:
        return True
    if actor_role in {CANONICAL_ROLE_TEAM_LEAD, CANONICAL_ROLE_TEAM_MEMBER}:
        return False
    return has_permission("logs.view", user=user) or has_permission("settings.manage", user=user)


def _filter_demo_rows(rows, model_name, demo_scope):
    if not table_exists("demo_seed_record"):
        return rows
    demo_ids = _demo_ids(model_name)
    if platform_demo_is_active():
        return [row for row in rows if row.id in demo_ids]
    if demo_scope == "all":
        return rows
    if demo_scope == "exclude":
        return [row for row in rows if row.id not in demo_ids]
    if demo_scope == "only":
        return [row for row in rows if row.id in demo_ids]
    return rows


def _demo_ids(model_name):
    if not table_exists("demo_seed_record"):
        return set()
    return demo_record_ids(model_name)


def _is_demo(model_name, record_id):
    return record_id in _demo_ids(model_name)


def _build_trend_map(assets, orders, stocks, days, meter_upcoming, overdue_maintenance, open_work_orders, low_stock, child_faults, calibration_overdue, total_assets, faulty_assets, auto_work_orders, calibration_upcoming=0, warranty_expiring=0, low_consumables=0, critical_consumables=0, out_of_service_critical=0):
    now = get_tr_now().replace(tzinfo=None)
    current_start = now - timedelta(days=days)
    previous_start = current_start - timedelta(days=days)
    previous_end = current_start
    current_date = now.date()
    previous_date = previous_end.date()

    total_assets_previous = sum(1 for asset in assets if _as_naive_datetime(asset.created_at) and _as_naive_datetime(asset.created_at) < current_start)
    previous_open_work_orders = sum(
        1
        for order in orders
        if _work_order_open_as_of(order, previous_end)
    )
    previous_overdue_maintenance = sum(
        1
        for asset in assets
        if _asset_existed_before(asset, previous_end)
        and asset.next_maintenance_date
        and asset.next_maintenance_date < previous_date
        and asset.lifecycle_status not in {"disposed", "decommissioned"}
    )
    previous_calibration_overdue = sum(
        1
        for asset in assets
        if _asset_existed_before(asset, previous_end)
        and asset.next_calibration_date
        and asset.next_calibration_date < previous_date
    )
    previous_calibration_upcoming = sum(
        1
        for asset in assets
        if _asset_existed_before(asset, previous_end)
        and asset.next_calibration_date
        and previous_date <= asset.next_calibration_date <= (previous_date + timedelta(days=15))
    )
    previous_warranty_expiring = sum(
        1
        for asset in assets
        if _asset_existed_before(asset, previous_end)
        and asset.warranty_end_date
        and previous_date <= asset.warranty_end_date <= (previous_date + timedelta(days=30))
    )
    auto_work_orders_previous = _count_rows_in_period(
        [order for order in orders if order.source_type == "meter_trigger"],
        "opened_at",
        previous_start,
        previous_end,
    )

    return {
        "total_assets": _trend_payload(total_assets, total_assets_previous),
        "faulty_assets": _unavailable_trend(faulty_assets),
        "overdue_maintenance": _trend_payload(overdue_maintenance, previous_overdue_maintenance),
        "open_work_orders": _trend_payload(open_work_orders, previous_open_work_orders),
        "low_stock": _unavailable_trend(low_stock),
        "meter_upcoming": _unavailable_trend(meter_upcoming),
        "child_faults": _unavailable_trend(child_faults),
        "calibration_overdue": _trend_payload(calibration_overdue, previous_calibration_overdue),
        "auto_work_orders": _trend_payload(auto_work_orders, auto_work_orders_previous),
        "calibration_upcoming": _trend_payload(calibration_upcoming, previous_calibration_upcoming),
        "warranty_expiring": _trend_payload(warranty_expiring, previous_warranty_expiring),
        "low_consumables": _unavailable_trend(low_consumables),
        "critical_consumables": _unavailable_trend(critical_consumables),
        "out_of_service_critical": _unavailable_trend(out_of_service_critical),
    }


def _build_trend_series(orders, days):
    labels = []
    opened = []
    completed = []
    today = get_tr_now().date()
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        labels.append(day.strftime("%d.%m"))
        opened.append(sum(1 for order in orders if order.opened_at and order.opened_at.date() == day))
        completed.append(sum(1 for order in orders if order.completed_at and order.completed_at.date() == day))
    return {"labels": labels, "opened": opened, "completed": completed}


def _average_close_hours(orders):
    durations = [
        round((order.completed_at - order.opened_at).total_seconds() / 3600, 1)
        for order in orders
        if order.completed_at and order.opened_at
    ]
    if not durations:
        return 0
    return round(sum(durations) / len(durations), 1)


def _meter_upcoming_count(assets, filters):
    asset_ids = {asset.id for asset in assets}
    if not asset_ids:
        return 0
    rules = [
        row
        for row in MaintenanceTriggerRule.query.filter_by(is_deleted=False, is_active=True).all()
        if row.asset_id and row.asset_id in asset_ids and row.meter_definition_id
    ]
    if not rules:
        return 0

    rule_pairs = {(row.asset_id, row.meter_definition_id): row for row in rules}
    pair_asset_ids = {item[0] for item in rule_pairs.keys()}
    pair_meter_ids = {item[1] for item in rule_pairs.keys()}

    base_reading_query = AssetMeterReading.query.filter(
        AssetMeterReading.is_deleted.is_(False),
        AssetMeterReading.asset_id.in_(pair_asset_ids),
        AssetMeterReading.meter_definition_id.in_(pair_meter_ids),
    )
    latest_reading_subquery = (
        base_reading_query.with_entities(
            AssetMeterReading.asset_id.label("asset_id"),
            AssetMeterReading.meter_definition_id.label("meter_definition_id"),
            func.max(AssetMeterReading.reading_at).label("max_reading_at"),
        )
        .group_by(AssetMeterReading.asset_id, AssetMeterReading.meter_definition_id)
        .subquery()
    )

    latest_rows = (
        AssetMeterReading.query.join(
            latest_reading_subquery,
            and_(
                AssetMeterReading.asset_id == latest_reading_subquery.c.asset_id,
                AssetMeterReading.meter_definition_id == latest_reading_subquery.c.meter_definition_id,
                AssetMeterReading.reading_at == latest_reading_subquery.c.max_reading_at,
            ),
        )
        .with_entities(
            AssetMeterReading.asset_id,
            AssetMeterReading.meter_definition_id,
            AssetMeterReading.reading_value,
        )
        .all()
    )

    count = 0
    for asset_id, meter_definition_id, reading_value in latest_rows:
        rule = rule_pairs.get((asset_id, meter_definition_id))
        if not rule:
            continue
        warning_threshold = float(rule.threshold_value or 0) - float(rule.warning_lead_value or 0)
        if float(reading_value or 0) >= max(warning_threshold, 0):
            count += 1
    return count


def _parse_date(raw_value):
    if not raw_value:
        return None
    try:
        return datetime.strptime(str(raw_value), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _fmt_date(value):
    return value.strftime("%d.%m.%Y") if value else "-"


def _fmt_datetime(value):
    return value.strftime("%d.%m.%Y %H:%M") if value else "-"


def _consumable_stock_label(available_quantity, item):
    if available_quantity <= float(item.critical_level or 0):
        return "Kritik"
    if available_quantity <= float(item.min_stock_level or 0):
        return "Düşük"
    return "Yeterli"


def _ratio(part, total):
    if not total:
        return 0
    return round((part / total) * 100, 1)


def _stock_label(stock):
    if stock.spare_part and stock.available_quantity <= float(stock.spare_part.critical_level or 0):
        return "Kritik"
    if stock.is_low_stock():
        return "Düşük"
    return "Yeterli"


def _close_hours(order):
    if not order.completed_at or not order.opened_at:
        return "-"
    return round((order.completed_at - order.opened_at).total_seconds() / 3600, 1)


def _kpi_item(label, value, trend, badge):
    return {
        "label": label,
        "value": value,
        "badge": badge,
        "trend": trend,
    }


def _trend_payload(current, previous):
    if previous is None:
        return _unavailable_trend(current)
    baseline = previous or 0
    if baseline == 0:
        percent = 100 if current else 0
    else:
        percent = round(((current - baseline) / baseline) * 100, 1)
    direction = "up" if current > baseline else "down" if current < baseline else "flat"
    return {
        "current": current,
        "previous": previous,
        "percent": percent,
        "direction": direction,
        "available": True,
    }


def _unavailable_trend(current):
    return {
        "current": current,
        "previous": None,
        "percent": None,
        "direction": "flat",
        "available": False,
    }


def _as_naive_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    return None


def _asset_existed_before(asset, dt_value):
    created_at = _as_naive_datetime(getattr(asset, "created_at", None))
    return bool(created_at and created_at < dt_value)


def _work_order_open_as_of(order, dt_value):
    opened_at = _as_naive_datetime(getattr(order, "opened_at", None))
    completed_at = _as_naive_datetime(getattr(order, "completed_at", None))
    if not opened_at or opened_at >= dt_value:
        return False
    if completed_at and completed_at <= dt_value:
        return False
    return getattr(order, "status", "") not in {"iptal_edildi"}


def _count_rows_in_period(rows, attr_name, start_dt, end_dt):
    count = 0
    for row in rows:
        value = _as_naive_datetime(getattr(row, attr_name, None))
        if value and start_dt <= value < end_dt:
            count += 1
    return count
