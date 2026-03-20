from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from decorators import has_permission, permission_required
from extensions import audit_log, db, guvenli_metin, limiter, log_kaydet
from models import Havalimani, InventoryAsset, SparePart, SparePartStock, Supplier, WorkOrder, WorkOrderPartUsage


parts_bp = Blueprint("parts", __name__)


def _can_manage():
    return has_permission("parts.edit")


def _visible_airports():
    if current_user.rol in ["sahip", "genel_mudurluk"]:
        return Havalimani.query.filter_by(is_deleted=False).order_by(Havalimani.kodu.asc()).all()
    return [current_user.havalimani] if current_user.havalimani else []


def _visible_stock_query():
    query = SparePartStock.query.filter_by(is_deleted=False, is_active=True)
    if current_user.rol in ["sahip", "genel_mudurluk"]:
        return query
    return query.filter_by(airport_id=current_user.havalimani_id)


@parts_bp.route("/yedek-parcalar")
@login_required
@permission_required("parts.view")
def spare_parts_list():
    q = guvenli_metin(request.args.get("q") or "").strip()
    category = guvenli_metin(request.args.get("kategori") or "").strip()
    low_only = request.args.get("dusuk_stok") == "1"

    query = SparePart.query.filter_by(is_deleted=False)
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                SparePart.part_code.ilike(like),
                SparePart.title.ilike(like),
                SparePart.manufacturer.ilike(like),
            )
        )
    if category:
        query = query.filter(SparePart.category == category)

    parts = query.order_by(SparePart.title.asc()).all()
    stocks = _visible_stock_query().all()
    stock_map = {}
    for stock in stocks:
        stock_map.setdefault(stock.spare_part_id, []).append(stock)

    if low_only:
        filtered_parts = []
        for part in parts:
            part_stocks = stock_map.get(part.id, [])
            if any(stock.is_low_stock() for stock in part_stocks):
                filtered_parts.append(part)
        parts = filtered_parts

    categories = (
        db.session.query(SparePart.category)
        .filter(SparePart.is_deleted.is_(False), SparePart.category.isnot(None), SparePart.category != "")
        .distinct()
        .order_by(SparePart.category.asc())
        .all()
    )

    return render_template(
        "spare_parts.html",
        parts=parts,
        stock_map=stock_map,
        categories=[row[0] for row in categories],
        selected_category=category,
        search_query=q,
        low_only=low_only,
    )


@parts_bp.route("/yedek-parcalar/yeni", methods=["GET", "POST"])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"), methods=["POST"])
@permission_required("parts.edit")
def spare_part_create():
    if not _can_manage():
        abort(403)

    suppliers = Supplier.query.filter_by(is_deleted=False, is_active=True).order_by(Supplier.name.asc()).all()
    airports = _visible_airports()

    if request.method == "POST":
        part_code = guvenli_metin(request.form.get("part_code") or "").strip().upper()
        title = guvenli_metin(request.form.get("title") or "").strip()
        if not part_code or not title:
            flash("Parça kodu ve parça adı zorunludur.", "danger")
            return redirect(url_for("parts.spare_part_create"))

        if SparePart.query.filter_by(part_code=part_code).first():
            flash("Bu parça kodu zaten kayıtlı.", "danger")
            return redirect(url_for("parts.spare_part_create"))

        part = SparePart(
            part_code=part_code,
            title=title,
            category=guvenli_metin(request.form.get("category") or "").strip(),
            compatible_asset_type=guvenli_metin(request.form.get("compatible_asset_type") or "").strip(),
            manufacturer=guvenli_metin(request.form.get("manufacturer") or "").strip(),
            model_code=guvenli_metin(request.form.get("model") or "").strip(),
            description=guvenli_metin(request.form.get("description") or "").strip(),
            unit=guvenli_metin(request.form.get("unit") or "").strip() or "adet",
            min_stock_level=request.form.get("min_stock_level", type=float) or 0,
            critical_level=request.form.get("critical_level", type=float) or 0,
            supplier_id=request.form.get("supplier_id", type=int) or None,
            is_active=request.form.get("is_active") == "on",
        )
        db.session.add(part)
        db.session.flush()

        for airport in airports:
            key_prefix = f"stock_{airport.id}_"
            on_hand_raw = request.form.get(f"{key_prefix}on_hand")
            reserved_raw = request.form.get(f"{key_prefix}reserved")
            reorder_raw = request.form.get(f"{key_prefix}reorder")
            shelf_raw = request.form.get(f"{key_prefix}shelf")
            if not any([on_hand_raw, reserved_raw, reorder_raw, shelf_raw]):
                continue
            quantity_on_hand = request.form.get(f"{key_prefix}on_hand", type=float) or 0
            db.session.add(
                SparePartStock(
                    spare_part_id=part.id,
                    airport_id=airport.id,
                    quantity_on_hand=quantity_on_hand,
                    quantity_reserved=request.form.get(f"{key_prefix}reserved", type=float) or 0,
                    reorder_point=request.form.get(f"{key_prefix}reorder", type=float) or part.min_stock_level or 0,
                    shelf_location=guvenli_metin(request.form.get(f"{key_prefix}shelf") or "").strip(),
                    is_active=True,
                )
            )

        db.session.commit()
        log_kaydet("Yedek Parça", f"Yedek parça eklendi: {part.part_code} / {part.title}")
        audit_log("parts.create", outcome="success", part_id=part.id, part_code=part.part_code)
        flash("Yedek parça kaydedildi.", "success")
        return redirect(url_for("parts.spare_parts_list"))

    return render_template(
        "spare_part_detail.html",
        part=None,
        stocks=[],
        suppliers=suppliers,
        airports=airports,
        usages=[],
    )


@parts_bp.route("/yedek-parcalar/<int:part_id>", methods=["GET", "POST"])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"), methods=["POST"])
@permission_required("parts.view")
def spare_part_detail(part_id):
    part = SparePart.query.filter_by(id=part_id, is_deleted=False).first_or_404()
    suppliers = Supplier.query.filter_by(is_deleted=False, is_active=True).order_by(Supplier.name.asc()).all()
    airports = _visible_airports()

    stocks_query = SparePartStock.query.filter_by(spare_part_id=part.id, is_deleted=False)
    if current_user.rol not in ["sahip", "genel_mudurluk"]:
        stocks_query = stocks_query.filter_by(airport_id=current_user.havalimani_id)
    stocks = stocks_query.order_by(SparePartStock.airport_id.asc()).all()

    if request.method == "POST":
        if not _can_manage():
            abort(403)

        action = (request.form.get("action") or "update").strip()
        if action == "stock_adjust":
            airport_id = request.form.get("airport_id", type=int)
            stock = SparePartStock.query.filter_by(
                spare_part_id=part.id,
                airport_id=airport_id,
                is_deleted=False,
            ).first()
            if not stock:
                stock = SparePartStock(
                    spare_part_id=part.id,
                    airport_id=airport_id,
                    quantity_on_hand=0,
                    quantity_reserved=0,
                    reorder_point=part.min_stock_level or 0,
                    is_active=True,
                )
                db.session.add(stock)
                db.session.flush()

            quantity_on_hand = request.form.get("quantity_on_hand", type=float)
            quantity_reserved = request.form.get("quantity_reserved", type=float)
            reorder_point = request.form.get("reorder_point", type=float)
            if quantity_on_hand is not None:
                stock.quantity_on_hand = quantity_on_hand
            if quantity_reserved is not None:
                stock.quantity_reserved = quantity_reserved
            if reorder_point is not None:
                stock.reorder_point = reorder_point
            stock.shelf_location = guvenli_metin(request.form.get("shelf_location") or stock.shelf_location or "").strip()
            db.session.commit()
            log_kaydet("Parça Stok", f"Stok güncellendi: {part.part_code} / Havalimanı {airport_id}")
            audit_log("parts.stock.update", outcome="success", part_id=part.id, airport_id=airport_id)
            flash("Stok güncellendi.", "success")
            return redirect(url_for("parts.spare_part_detail", part_id=part.id))

        part.title = guvenli_metin(request.form.get("title") or "").strip() or part.title
        part.category = guvenli_metin(request.form.get("category") or "").strip()
        part.compatible_asset_type = guvenli_metin(request.form.get("compatible_asset_type") or "").strip()
        part.manufacturer = guvenli_metin(request.form.get("manufacturer") or "").strip()
        part.model_code = guvenli_metin(request.form.get("model") or "").strip()
        part.description = guvenli_metin(request.form.get("description") or "").strip()
        part.unit = guvenli_metin(request.form.get("unit") or "").strip() or part.unit
        min_stock_level = request.form.get("min_stock_level", type=float)
        critical_level = request.form.get("critical_level", type=float)
        if min_stock_level is not None:
            part.min_stock_level = min_stock_level
        if critical_level is not None:
            part.critical_level = critical_level
        part.supplier_id = request.form.get("supplier_id", type=int) or None
        part.is_active = request.form.get("is_active") == "on"

        db.session.commit()
        log_kaydet("Yedek Parça", f"Yedek parça güncellendi: {part.part_code} / {part.title}")
        audit_log("parts.update", outcome="success", part_id=part.id)
        flash("Yedek parça güncellendi.", "success")
        return redirect(url_for("parts.spare_part_detail", part_id=part.id))

    usages_query = WorkOrderPartUsage.query.filter_by(spare_part_id=part.id, is_deleted=False)
    if current_user.rol not in ["sahip", "genel_mudurluk"]:
        usages_query = usages_query.join(WorkOrder).join(InventoryAsset).filter(
            InventoryAsset.havalimani_id == current_user.havalimani_id
        )
    usages = usages_query.order_by(WorkOrderPartUsage.created_at.desc()).limit(100).all()

    return render_template(
        "spare_part_detail.html",
        part=part,
        stocks=stocks,
        suppliers=suppliers,
        airports=airports,
        usages=usages,
    )
