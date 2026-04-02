from datetime import timedelta

from flask import Blueprint, abort, current_app, jsonify, request
from flask_login import current_user, login_required
from flask_wtf.csrf import generate_csrf
import sqlalchemy as sa
from sqlalchemy.orm import joinedload

from decorators import CANONICAL_ROLE_SYSTEM, CANONICAL_ROLE_TEAM_LEAD, get_effective_role, permission_required
from extensions import db, limiter
from models import (
    AirportMessage,
    AssetMeterReading,
    Havalimani,
    InventoryAsset,
    Kutu,
    MaintenanceHistory,
    MaintenancePlan,
    Malzeme,
    SparePart,
    SparePartStock,
    WorkOrder,
    WorkOrderChecklistResponse,
    WorkOrderPartUsage,
    get_tr_now,
)


api_bp = Blueprint("api", __name__)


def _can_view_all():
    return get_effective_role(current_user) == CANONICAL_ROLE_SYSTEM


def _can_view_all_boxes():
    return get_effective_role(current_user) == CANONICAL_ROLE_SYSTEM


def _can_moderate_airport_messages():
    return get_effective_role(current_user) in {CANONICAL_ROLE_SYSTEM, CANONICAL_ROLE_TEAM_LEAD}


def _visible_message_airports():
    query = Havalimani.query.filter_by(is_deleted=False).order_by(Havalimani.ad.asc())
    if _can_view_all():
        return query.all()
    airport_id = getattr(current_user, "havalimani_id", None)
    if airport_id is None:
        return []
    return query.filter(Havalimani.id == airport_id).all()


def _resolve_message_airport_id(raw_airport_id, *, for_write=False):
    cleaned = str(raw_airport_id or "").strip()
    if not cleaned:
        if _can_view_all() and not for_write:
            return None
        return getattr(current_user, "havalimani_id", None)

    try:
        airport_id = int(cleaned)
    except (TypeError, ValueError):
        abort(400)

    if _can_view_all():
        exists = Havalimani.query.filter_by(id=airport_id, is_deleted=False).first()
        if not exists:
            abort(404)
        return airport_id

    if airport_id != getattr(current_user, "havalimani_id", None):
        abort(403)
    return airport_id


def _prune_expired_airport_messages():
    cutoff = get_tr_now().replace(tzinfo=None) - timedelta(days=7)
    (
        AirportMessage.query.filter(AirportMessage.created_at.isnot(None), AirportMessage.created_at < cutoff)
        .delete(synchronize_session=False)
    )
    db.session.commit()


def _message_display_name(message):
    if message.user and getattr(message.user, "tam_ad", None):
        return message.user.tam_ad
    if message.user and getattr(message.user, "kullanici_adi", None):
        return message.user.kullanici_adi
    return "Sistem"


def _serialize_airport_message(message):
    current_role = get_effective_role(current_user)
    can_moderate = current_role == CANONICAL_ROLE_SYSTEM
    if current_role == CANONICAL_ROLE_TEAM_LEAD and message.havalimani_id == getattr(current_user, "havalimani_id", None):
        can_moderate = True
    can_delete = bool(message.user_id == current_user.id or can_moderate)
    return {
        "id": message.id,
        "airport_id": message.havalimani_id,
        "airport_label": message.havalimani.ad if message.havalimani else "-",
        "author": _message_display_name(message),
        "text": message.message_text,
        "created_at": message.created_at.strftime("%d.%m.%Y %H:%M") if message.created_at else "-",
        "can_delete": can_delete,
    }


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


@api_bp.route("/api/csrf-token", methods=["GET"])
@login_required
def api_csrf_token():
    return jsonify({"status": "success", "csrf_token": generate_csrf()})


@api_bp.route("/api/envanter")
@login_required
@permission_required("inventory.view")
def api_envanter():
    if not _can_view_all():
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


@api_bp.route("/api/mesajlar", methods=["GET"])
@login_required
def api_airport_messages():
    _prune_expired_airport_messages()

    summary_only = str(request.args.get("summary") or "").strip().lower() in {"1", "true", "yes"}
    selected_airport_id = _resolve_message_airport_id(request.args.get("airport_id"), for_write=False)
    query = (
        AirportMessage.query.options(joinedload(AirportMessage.user), joinedload(AirportMessage.havalimani))
        .order_by(AirportMessage.created_at.desc(), AirportMessage.id.desc())
    )
    if selected_airport_id is not None:
        query = query.filter(AirportMessage.havalimani_id == selected_airport_id)
    elif not _can_view_all():
        query = query.filter(AirportMessage.havalimani_id == getattr(current_user, "havalimani_id", None))

    count_query = query.order_by(None)
    recent_cutoff = get_tr_now().replace(tzinfo=None) - timedelta(hours=24)
    new_message_count = count_query.filter(
        AirportMessage.created_at.isnot(None),
        AirportMessage.created_at >= recent_cutoff,
    ).count()
    total_message_count = count_query.count()
    rows = [] if summary_only else list(reversed(query.limit(80).all()))
    airports = _visible_message_airports()
    payload = {
        "status": "success",
        "messages": [_serialize_airport_message(row) for row in rows],
        "can_moderate": _can_moderate_airport_messages(),
        "selected_airport_id": selected_airport_id,
        "airports": [{"id": airport.id, "name": airport.ad} for airport in airports],
        "can_view_all": _can_view_all(),
        "new_count": int(new_message_count or 0),
        "total_count": int(total_message_count or 0),
    }
    return jsonify(payload)


@api_bp.route("/api/mesajlar", methods=["POST"])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"), methods=["POST"])
def api_airport_message_create():
    _prune_expired_airport_messages()

    payload = request.get_json(silent=True) or request.form
    message_text = str(payload.get("message_text") or "").strip()
    if not message_text:
        return jsonify({"status": "error", "message": "Mesaj boş bırakılamaz."}), 400
    if len(message_text) > 1000:
        return jsonify({"status": "error", "message": "Mesaj en fazla 1000 karakter olabilir."}), 400

    airport_id = _resolve_message_airport_id(payload.get("airport_id"), for_write=True)
    if airport_id is None:
        return jsonify({"status": "error", "message": "Mesaj göndermek için havalimanı seçin."}), 400

    row = AirportMessage(
        havalimani_id=airport_id,
        user_id=current_user.id,
        message_text=message_text,
    )
    db.session.add(row)
    db.session.commit()

    row = (
        AirportMessage.query.options(joinedload(AirportMessage.user), joinedload(AirportMessage.havalimani))
        .filter_by(id=row.id)
        .first()
    )
    return jsonify({"status": "success", "message": _serialize_airport_message(row)})


@api_bp.route("/api/mesajlar/<int:message_id>/sil", methods=["POST"])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"), methods=["POST"])
def api_airport_message_delete(message_id):
    _prune_expired_airport_messages()

    row = (
        AirportMessage.query.options(joinedload(AirportMessage.user), joinedload(AirportMessage.havalimani))
        .filter_by(id=message_id)
        .first_or_404()
    )
    if not _can_view_all() and row.havalimani_id != getattr(current_user, "havalimani_id", None):
        abort(404)

    can_moderate = _can_moderate_airport_messages() and (
        _can_view_all() or row.havalimani_id == getattr(current_user, "havalimani_id", None)
    )
    if row.user_id != current_user.id and not can_moderate:
        abort(403)

    db.session.delete(row)
    db.session.commit()
    return jsonify({"status": "success"})


@api_bp.route("/api/mesajlar/toplu-sil", methods=["POST"])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"), methods=["POST"])
def api_airport_message_bulk_delete():
    _prune_expired_airport_messages()
    if not _can_moderate_airport_messages():
        abort(403)

    payload = request.get_json(silent=True) or request.form
    airport_id = _resolve_message_airport_id(payload.get("airport_id"), for_write=False)
    query = AirportMessage.query
    if airport_id is not None:
        query = query.filter(AirportMessage.havalimani_id == airport_id)
    elif _can_view_all():
        query = query
    else:
        query = query.filter(AirportMessage.havalimani_id == getattr(current_user, "havalimani_id", None))

    deleted_count = query.delete(synchronize_session=False)
    db.session.commit()
    return jsonify({"status": "success", "deleted_count": int(deleted_count or 0)})


@api_bp.route("/api/parca/dusuk-stok")
@login_required
@permission_required("parts.view")
def api_low_stock_parts():
    query = (
        SparePartStock.query.options(
            joinedload(SparePartStock.spare_part),
            joinedload(SparePartStock.airport_stock),
        )
        .outerjoin(SparePartStock.spare_part)
        .filter(SparePartStock.is_deleted.is_(False), SparePartStock.is_active.is_(True))
    )
    if not _can_view_all():
        query = query.filter(SparePartStock.airport_id == current_user.havalimani_id)

    available_quantity = sa.func.coalesce(SparePartStock.quantity_on_hand, 0.0) - sa.func.coalesce(
        SparePartStock.quantity_reserved, 0.0
    )
    threshold = sa.func.coalesce(SparePartStock.reorder_point, SparePart.min_stock_level, 0.0)
    low_rows = query.filter(available_quantity <= threshold).all()
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
