from datetime import timedelta

from flask import Blueprint, jsonify
from flask_login import current_user, login_required

from decorators import CANONICAL_ROLE_SYSTEM, get_effective_role, permission_required
from models import (
    AssetMeterReading,
    InventoryAsset,
    Kutu,
    MaintenanceHistory,
    MaintenancePlan,
    Malzeme,
    SparePartStock,
    WorkOrder,
    WorkOrderChecklistResponse,
    WorkOrderPartUsage,
    get_tr_now,
)


api_bp = Blueprint("api", __name__)


def _can_view_all():
    return current_user.rol in ["sahip", "genel_mudurluk"]


def _can_view_all_boxes():
    return get_effective_role(current_user) == CANONICAL_ROLE_SYSTEM


def _asset_scope():
    query = InventoryAsset.query.filter_by(is_deleted=False)
    if _can_view_all():
        return query
    return query.filter_by(havalimani_id=current_user.havalimani_id)


def _work_order_scope():
    query = WorkOrder.query.filter_by(is_deleted=False).join(InventoryAsset).filter(InventoryAsset.is_deleted.is_(False))
    if _can_view_all():
        return query
    return query.filter(InventoryAsset.havalimani_id == current_user.havalimani_id)


@api_bp.route("/api/envanter")
@login_required
@permission_required("inventory.view")
def api_envanter():
    if current_user.rol != "sahip":
        malzemeler = Malzeme.query.filter_by(havalimani_id=current_user.havalimani_id, is_deleted=False).all()
    else:
        malzemeler = Malzeme.query.filter_by(is_deleted=False).all()

    return jsonify(
        {
            "durum": "basarili",
            "veri": [{"ad": m.ad, "sn": m.seri_no, "durum": m.durum} for m in malzemeler],
        }
    )


@api_bp.route("/api/kutu/<string:kodu>")
@login_required
@permission_required("inventory.view")
def api_kutu_detay(kodu):
    kutu = Kutu.query.filter_by(kodu=kodu, is_deleted=False).first()
    if not kutu:
        return jsonify({"durum": "hata", "mesaj": "Kutu bulunamadi"}), 404

    if not _can_view_all_boxes() and kutu.havalimani_id != current_user.havalimani_id:
        return jsonify({"durum": "hata", "mesaj": "Yetkisiz erisim"}), 403

    malzemeler = [{"ad": m.ad, "durum": m.durum, "seri_no": m.seri_no} for m in kutu.malzemeler if not m.is_deleted]
    return jsonify(
        {
            "kutu_kodu": kutu.kodu,
            "havalimani": kutu.havalimani.ad,
            "malzemeler": malzemeler,
        }
    )


@api_bp.route("/api/bakim/istatistikler")
@login_required
@permission_required("maintenance.view")
def api_bakim_istatistikleri():
    today = get_tr_now().date()
    soon_date = today + timedelta(days=7)

    assets = _asset_scope()
    open_orders = WorkOrder.query.filter_by(is_deleted=False).join(InventoryAsset).filter(
        InventoryAsset.is_deleted.is_(False),
        WorkOrder.status.in_(["acik", "atandi", "islemde"]),
    )
    if not _can_view_all():
        open_orders = open_orders.filter(InventoryAsset.havalimani_id == current_user.havalimani_id)

    data = {
        "yaklasan_bakim": assets.filter(
            InventoryAsset.next_maintenance_date.isnot(None),
            InventoryAsset.next_maintenance_date >= today,
            InventoryAsset.next_maintenance_date <= soon_date,
        ).count(),
        "geciken_bakim": assets.filter(
            InventoryAsset.next_maintenance_date.isnot(None),
            InventoryAsset.next_maintenance_date < today,
        ).count(),
        "acik_is_emri": open_orders.count(),
        "kritik_ariza": assets.filter(
            InventoryAsset.is_critical.is_(True),
            InventoryAsset.status.in_(["arizali", "bakimda"]),
        ).count(),
    }
    return jsonify({"durum": "basarili", "veri": data})


@api_bp.route("/api/bakim/acik-is-emirleri")
@login_required
@permission_required("workorder.view")
def api_acik_is_emirleri():
    query = WorkOrder.query.filter_by(is_deleted=False).join(InventoryAsset).filter(
        InventoryAsset.is_deleted.is_(False),
        WorkOrder.status.in_(["acik", "atandi", "islemde"]),
    )
    if not _can_view_all():
        query = query.filter(InventoryAsset.havalimani_id == current_user.havalimani_id)

    orders = query.order_by(WorkOrder.opened_at.desc()).limit(100).all()
    return jsonify(
        {
            "durum": "basarili",
            "veri": [
                {
                    "id": order.id,
                    "is_emri_no": order.work_order_no,
                    "durum": order.status,
                    "oncelik": order.priority,
                    "bakim_turu": order.maintenance_type,
                    "asset_id": order.asset_id,
                }
                for order in orders
            ],
        }
    )


@api_bp.route("/api/bakim/yaklasan-kayitlar")
@login_required
@permission_required("maintenance.view")
def api_yaklasan_bakim_kayitlari():
    today = get_tr_now().date()
    soon_date = today + timedelta(days=15)
    records = _asset_scope().filter(
        InventoryAsset.next_maintenance_date.isnot(None),
        InventoryAsset.next_maintenance_date >= today,
        InventoryAsset.next_maintenance_date <= soon_date,
    ).order_by(InventoryAsset.next_maintenance_date.asc()).all()

    return jsonify(
        {
            "durum": "basarili",
            "veri": [
                {
                    "asset_id": row.id,
                    "seri_no": row.serial_no,
                    "sonraki_bakim_tarihi": row.next_maintenance_date.strftime("%Y-%m-%d"),
                    "havalimani_id": row.havalimani_id,
                }
                for row in records
            ],
        }
    )


@api_bp.route("/api/bakim/asset/<int:asset_id>/gecmis")
@login_required
@permission_required("maintenance.view")
def api_asset_bakim_gecmisi(asset_id):
    asset = _asset_scope().filter(InventoryAsset.id == asset_id).first()
    if not asset:
        return jsonify({"durum": "hata", "mesaj": "Ekipman bulunamadı"}), 404

    history_rows = (
        MaintenanceHistory.query.filter_by(asset_id=asset.id, is_deleted=False)
        .order_by(MaintenanceHistory.performed_at.desc())
        .all()
    )

    return jsonify(
        {
            "durum": "basarili",
            "veri": [
                {
                    "id": row.id,
                    "bakim_turu": row.maintenance_type,
                    "sonuc": row.result,
                    "tarih": row.performed_at.strftime("%Y-%m-%d %H:%M"),
                    "sonraki_bakim_tarihi": row.next_maintenance_date.strftime("%Y-%m-%d")
                    if row.next_maintenance_date
                    else None,
                }
                for row in history_rows
            ],
        }
    )


@api_bp.route("/api/bakim/asset/<int:asset_id>/sayac-gecmisi")
@login_required
@permission_required("maintenance.view")
def api_asset_meter_history(asset_id):
    asset = _asset_scope().filter(InventoryAsset.id == asset_id).first()
    if not asset:
        return jsonify({"durum": "hata", "mesaj": "Ekipman bulunamadı"}), 404

    rows = AssetMeterReading.query.filter_by(asset_id=asset.id, is_deleted=False).order_by(
        AssetMeterReading.reading_at.desc()
    ).limit(200).all()
    return jsonify(
        {
            "durum": "basarili",
            "veri": [
                {
                    "id": row.id,
                    "meter_id": row.meter_definition_id,
                    "meter_name": row.meter_definition.name if row.meter_definition else None,
                    "meter_type": row.meter_definition.meter_type if row.meter_definition else None,
                    "value": row.reading_value,
                    "reading_at": row.reading_at.strftime("%Y-%m-%d %H:%M"),
                    "note": row.note,
                }
                for row in rows
            ],
        }
    )


@api_bp.route("/api/parca/dusuk-stok")
@login_required
@permission_required("parts.view")
def api_low_stock_parts():
    query = SparePartStock.query.filter_by(is_deleted=False, is_active=True)
    if not _can_view_all():
        query = query.filter(SparePartStock.airport_id == current_user.havalimani_id)
    rows = query.all()
    low_rows = [
        stock
        for stock in rows
        if stock.available_quantity
        <= float(stock.reorder_point if stock.reorder_point is not None else (stock.spare_part.min_stock_level if stock.spare_part else 0))
    ]
    return jsonify(
        {
            "durum": "basarili",
            "veri": [
                {
                    "stock_id": stock.id,
                    "airport_id": stock.airport_id,
                    "airport_code": stock.airport_stock.kodu if stock.airport_stock else None,
                    "part_code": stock.spare_part.part_code if stock.spare_part else None,
                    "part_title": stock.spare_part.title if stock.spare_part else None,
                    "available_quantity": stock.available_quantity,
                    "reorder_point": stock.reorder_point,
                }
                for stock in low_rows
            ],
        }
    )


@api_bp.route("/api/bakim/is-emri/<int:work_order_id>/parca-kullanim")
@login_required
@permission_required("parts.view")
def api_work_order_part_usage(work_order_id):
    order = _work_order_scope().filter(WorkOrder.id == work_order_id).first()
    if not order:
        return jsonify({"durum": "hata", "mesaj": "İş emri bulunamadı"}), 404

    rows = WorkOrderPartUsage.query.filter_by(work_order_id=order.id, is_deleted=False).all()
    return jsonify(
        {
            "durum": "basarili",
            "veri": [
                {
                    "id": row.id,
                    "part_code": row.spare_part.part_code if row.spare_part else None,
                    "part_title": row.spare_part.title if row.spare_part else None,
                    "quantity_used": row.quantity_used,
                    "note": row.note,
                }
                for row in rows
            ],
        }
    )


@api_bp.route("/api/bakim/geciken-periyodik")
@login_required
@permission_required("maintenance.view")
def api_overdue_preventive():
    today = get_tr_now().date()
    query = MaintenancePlan.query.filter(
        MaintenancePlan.is_deleted.is_(False),
        MaintenancePlan.is_active.is_(True),
        MaintenancePlan.next_due_date.isnot(None),
        MaintenancePlan.next_due_date < today,
    )
    if not _can_view_all():
        query = query.filter(MaintenancePlan.owner_airport_id == current_user.havalimani_id)
    rows = query.order_by(MaintenancePlan.next_due_date.asc()).all()
    return jsonify(
        {
            "durum": "basarili",
            "veri": [
                {
                    "plan_id": row.id,
                    "plan_name": row.name,
                    "asset_id": row.asset_id,
                    "airport_id": row.owner_airport_id,
                    "next_due_date": row.next_due_date.strftime("%Y-%m-%d") if row.next_due_date else None,
                }
                for row in rows
            ],
        }
    )


@api_bp.route("/api/bakim/inspection-failures")
@login_required
@permission_required("maintenance.view")
def api_inspection_failures():
    query = WorkOrderChecklistResponse.query.filter_by(is_deleted=False, is_failure=True).join(WorkOrder).join(InventoryAsset)
    if not _can_view_all():
        query = query.filter(InventoryAsset.havalimani_id == current_user.havalimani_id)
    rows = query.order_by(WorkOrderChecklistResponse.responded_at.desc()).limit(200).all()
    return jsonify(
        {
            "durum": "basarili",
            "veri": [
                {
                    "response_id": row.id,
                    "work_order_no": row.work_order.work_order_no if row.work_order else None,
                    "asset_id": row.work_order.asset_id if row.work_order else None,
                    "field_label": row.field_label,
                    "value": row.response_value,
                    "responded_at": row.responded_at.strftime("%Y-%m-%d %H:%M") if row.responded_at else None,
                }
                for row in rows
            ],
        }
    )
