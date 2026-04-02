import io
import json
from datetime import datetime, timedelta

from flask import Blueprint, current_app, render_template, request, redirect, send_file, url_for, flash, abort
from flask_login import login_required, current_user
from xhtml2pdf import pisa

from extensions import audit_log, create_approval_request, create_notification, db, limiter, log_kaydet, guvenli_metin
from decorators import (
    CANONICAL_ROLE_ADMIN,
    CANONICAL_ROLE_SYSTEM,
    CANONICAL_ROLE_TEAM_LEAD,
    CANONICAL_ROLE_TEAM_MEMBER,
    get_effective_role,
    has_permission,
    permission_required,
)
from demo_data import apply_platform_demo_scope
from models import (
    AssetMeterReading,
    EquipmentTemplate,
    Havalimani,
    InventoryCategory,
    InventoryAsset,
    Kullanici,
    MaintenanceTriggerRule,
    MeterDefinition,
    MaintenanceFormField,
    MaintenanceFormTemplate,
    MaintenanceHistory,
    MaintenanceInstruction,
    MaintenancePlan,
    SparePart,
    SparePartStock,
    WorkOrder,
    WorkOrderChecklistResponse,
    WorkOrderPartUsage,
    get_tr_now,
)


maintenance_bp = Blueprint("maintenance", __name__)

STATUS_OPEN_SET = {"acik", "atandi", "islemde", "beklemede_parca", "beklemede_onay"}
ORDER_STATUSES = ["acik", "atandi", "islemde", "beklemede_parca", "beklemede_onay", "tamamlandi", "iptal_edildi"]
ORDER_PRIORITIES = ["dusuk", "orta", "yuksek", "kritik"]
WORK_ORDER_TYPES = ["preventive", "corrective", "inspection", "calibration", "emergency", "request"]
SOURCE_TYPES = ["manual", "scheduler", "meter_trigger", "inspection_failure", "user_report"]
CHECKLIST_FAILURE_VALUES = {"fail", "hayir", "false", "0", "no"}
CHECKLIST_FIELD_TYPES = {
    "text": "Serbest Metin",
    "number": "Sayı",
    "date": "Tarih",
    "yes_no": "Evet / Hayır",
    "pass_fail": "Geçti / Kaldı",
    "select": "Seçim Listesi",
}
MAINTENANCE_PERIOD_TYPES = {
    "gunluk": "Günlük",
    "aylik": "Aylık",
    "yillik": "Yıllık",
}


def _can_view_all():
    return bool(getattr(current_user, "is_sahip", False))


def _can_create_work_order():
    return has_permission("workorder.create")


def _can_edit_work_order():
    return has_permission("workorder.edit")


def _can_assign_work_order():
    return has_permission("workorder.assign")


def _can_manage_form_catalog():
    return has_permission("maintenance.templates.manage") or has_permission("maintenance.plan.change")


def _can_manage_instruction_maintenance_forms():
    return get_effective_role(current_user) in {CANONICAL_ROLE_SYSTEM, CANONICAL_ROLE_TEAM_LEAD}


def _can_manage_instruction_catalog():
    return bool(getattr(current_user, "is_sahip", False))


def _build_instruction_catalog_options():
    allowed_categories = [
        guvenli_metin(item.name or "").strip()
        for item in InventoryCategory.query.filter_by(is_deleted=False, is_active=True)
        .order_by(InventoryCategory.name.asc())
        .all()
        if guvenli_metin(item.name or "").strip()
    ]
    allowed_category_set = {item for item in allowed_categories if item}

    templates = (
        EquipmentTemplate.query.join(
            InventoryAsset,
            InventoryAsset.equipment_template_id == EquipmentTemplate.id,
        )
        .filter(
            EquipmentTemplate.is_deleted.is_(False),
            EquipmentTemplate.is_active.is_(True),
            EquipmentTemplate.name.isnot(None),
            EquipmentTemplate.name != "",
            EquipmentTemplate.category.isnot(None),
            EquipmentTemplate.category != "",
            InventoryAsset.is_deleted.is_(False),
        )
        .distinct()
        .order_by(
            EquipmentTemplate.category.asc(),
            EquipmentTemplate.name.asc(),
            EquipmentTemplate.brand.asc(),
            EquipmentTemplate.model_code.asc(),
            EquipmentTemplate.id.asc(),
        )
        .all()
    )

    catalog = []
    for template in templates:
        category = guvenli_metin(template.category or "").strip()
        if not category:
            continue
        if allowed_category_set and category not in allowed_category_set:
            continue
        catalog.append(
            {
                "id": template.id,
                "category": category,
                "name": guvenli_metin(template.name or "").strip(),
                "brand": guvenli_metin(template.brand or "").strip(),
                "model_code": guvenli_metin(template.model_code or "").strip(),
            }
        )

    selectable_categories = sorted({item["category"] for item in catalog}, key=str.lower)
    return catalog, selectable_categories


def _build_maintenance_form_equipment_options():
    templates = (
        EquipmentTemplate.query.filter(
            EquipmentTemplate.is_deleted.is_(False),
            EquipmentTemplate.is_active.is_(True),
            EquipmentTemplate.name.isnot(None),
            EquipmentTemplate.name != "",
        )
        .order_by(
            EquipmentTemplate.category.asc(),
            EquipmentTemplate.name.asc(),
            EquipmentTemplate.brand.asc(),
            EquipmentTemplate.model_code.asc(),
            EquipmentTemplate.id.asc(),
        )
        .all()
    )

    options = []
    for template in templates:
        options.append(
            {
                "id": template.id,
                "name": guvenli_metin(template.name or "").strip(),
                "category": guvenli_metin(template.category or "").strip(),
                "brand": guvenli_metin(template.brand or "").strip(),
                "model_code": guvenli_metin(template.model_code or "").strip(),
            }
        )
    return options


def _normalize_period_type(raw_value):
    value = guvenli_metin(raw_value or "").strip().lower()
    return value if value in MAINTENANCE_PERIOD_TYPES else None


def _parse_maintenance_step_rows(raw_payload):
    try:
        payload = json.loads(raw_payload or "[]")
    except (TypeError, ValueError):
        return [], "Bakım adımları doğrulanamadı. Adımları tekrar ekleyip kaydedin."

    if not isinstance(payload, list):
        return [], "Bakım adımları doğrulanamadı. Adımları tekrar ekleyip kaydedin."

    rows = []
    seen = set()
    for item in payload:
        label = " ".join(str(item or "").split()).strip()
        if not label:
            continue
        normalized_key = label.casefold()
        if normalized_key in seen:
            continue
        seen.add(normalized_key)
        rows.append(label)
    return rows, None


def _build_maintenance_form_name(template, period_label):
    base_name = f"{template.name} - {period_label} Bakım Formu"
    existing = MaintenanceFormTemplate.query.filter(
        MaintenanceFormTemplate.is_deleted.is_(False),
        MaintenanceFormTemplate.name == base_name,
    ).first()
    if not existing:
        return base_name

    suffix = template.model_code or template.brand or f"#{template.id}"
    suffix = guvenli_metin(suffix or "").strip() or f"#{template.id}"
    candidate = f"{base_name} ({suffix})"
    sequence = 2
    while MaintenanceFormTemplate.query.filter(
        MaintenanceFormTemplate.is_deleted.is_(False),
        MaintenanceFormTemplate.name == candidate,
    ).first():
        candidate = f"{base_name} ({suffix}-{sequence})"
        sequence += 1
    return candidate


def _asset_scope():
    query = InventoryAsset.query.filter_by(is_deleted=False)
    query = apply_platform_demo_scope(query, "InventoryAsset", InventoryAsset.id)
    if _can_view_all():
        return query
    return query.filter_by(havalimani_id=current_user.havalimani_id)


def _work_order_scope():
    query = WorkOrder.query.filter_by(is_deleted=False).join(InventoryAsset)
    query = apply_platform_demo_scope(query, "WorkOrder", WorkOrder.id)
    if _can_view_all():
        return query.filter(InventoryAsset.is_deleted.is_(False))
    return query.filter(
        InventoryAsset.is_deleted.is_(False),
        InventoryAsset.havalimani_id == current_user.havalimani_id,
    )


def _parse_date(raw_value):
    if not raw_value:
        return None
    try:
        return datetime.strptime(raw_value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _parse_datetime(raw_value):
    if not raw_value:
        return None
    try:
        return datetime.strptime(raw_value, "%Y-%m-%dT%H:%M")
    except (TypeError, ValueError):
        return None


def _to_float(raw_value, default=0.0):
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return default


def _next_work_order_no():
    now = get_tr_now()
    return f"WO-{now.strftime('%Y%m%d%H%M%S')}-{now.microsecond % 1000:03d}"


def _checklist_fields_for_asset(asset):
    if asset.equipment_template and asset.equipment_template.default_maintenance_form:
        return asset.equipment_template.default_maintenance_form.fields
    return []


def _ensure_asset_work_order(asset):
    open_order = (
        WorkOrder.query.filter_by(asset_id=asset.id, is_deleted=False)
        .filter(WorkOrder.status.in_(STATUS_OPEN_SET))
        .order_by(WorkOrder.opened_at.desc())
        .first()
    )
    if open_order:
        return open_order, False

    form_template_id = None
    if asset.equipment_template and asset.equipment_template.default_maintenance_form_id:
        form_template_id = asset.equipment_template.default_maintenance_form_id

    work_order = WorkOrder(
        work_order_no=_next_work_order_no(),
        asset_id=asset.id,
        maintenance_type="bakim",
        work_order_type="preventive",
        source_type="manual",
        description=f"{asset.equipment_template.name if asset.equipment_template else 'Ekipman'} için saha bakım akışı",
        target_date=get_tr_now().date(),
        assigned_user_id=current_user.id,
        created_user_id=current_user.id,
        status="acik",
        priority="yuksek" if asset.is_critical else "orta",
        checklist_template_id=form_template_id,
    )
    db.session.add(work_order)
    db.session.flush()
    return work_order, True


def _asset_allowed(asset):
    return _can_view_all() or asset.havalimani_id == current_user.havalimani_id


def _user_scope():
    query = Kullanici.query.filter_by(is_deleted=False)
    query = apply_platform_demo_scope(query, "Kullanici", Kullanici.id)
    if _can_view_all():
        return query
    return query.filter(Kullanici.havalimani_id == current_user.havalimani_id)


def _user_allowed(user):
    return _can_view_all() or getattr(user, "havalimani_id", None) == current_user.havalimani_id


def _parse_part_usage_input(raw_text):
    """
    Beklenen format:
    PARCA-KODU:2
    PARCA-XYZ:1.5
    """
    usages = []
    for raw_line in (raw_text or "").replace(",", "\n").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if ":" not in line:
            # Geriye dönük uyum: serbest metin girişleri stok düşümüne zorlanmaz.
            continue
        code, qty_raw = [part.strip() for part in line.split(":", 1)]
        quantity = max(_to_float(qty_raw, 0), 0)
        if not code or quantity <= 0:
            continue
        usages.append((code, quantity))
    return usages


def _status_label(status_value):
    labels = {
        "acik": "Açık",
        "atandi": "Atandı",
        "islemde": "İşlemde",
        "beklemede_parca": "Parça Bekleniyor",
        "beklemede_onay": "Onay Bekleniyor",
        "tamamlandi": "Tamamlandı",
        "iptal_edildi": "İptal Edildi",
    }
    return labels.get(status_value, status_value)


def _normalize_checklist_field_type(raw_value):
    mapping = {
        "text": "text",
        "serbest_metin": "text",
        "metin": "text",
        "number": "number",
        "sayi": "number",
        "numeric_reading": "number",
        "date": "date",
        "tarih": "date",
        "boolean": "yes_no",
        "checkbox": "yes_no",
        "yes_no": "yes_no",
        "evet_hayir": "yes_no",
        "pass_fail": "pass_fail",
        "gecti_kaldi": "pass_fail",
        "select": "select",
        "secim": "select",
        "dropdown": "select",
    }
    return mapping.get((raw_value or "text").strip().lower(), "text")


def _parse_checklist_rows(raw_fields):
    rows = []
    for index, raw_line in enumerate((raw_fields or "").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split("|")]
        label = parts[0] if parts else ""
        if not label:
            continue
        field_type = _normalize_checklist_field_type(parts[1] if len(parts) > 1 else "text")
        is_required = (parts[2].lower() == "zorunlu") if len(parts) > 2 and parts[2] else False
        is_critical = (parts[3].lower() == "kritik") if len(parts) > 3 and parts[3] else False
        option_values = []
        if len(parts) > 4 and parts[4]:
            option_values = [item.strip() for item in parts[4].split(",") if item.strip()]
        help_text = parts[5] if len(parts) > 5 else ""
        rows.append(
            {
                "label": label,
                "field_type": field_type,
                "is_required": is_required,
                "is_critical": is_critical,
                "options": option_values,
                "help_text": help_text,
                "order_index": index,
            }
        )
    return rows


def _field_meta(field):
    try:
        payload = json.loads(field.options_json or "{}")
    except (TypeError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    options = payload.get("options") or []
    return {
        "options": options if isinstance(options, list) else [],
        "help_text": str(payload.get("help_text") or "").strip(),
        "is_critical": bool(payload.get("is_critical")),
    }


def _is_critical_field(field):
    key = (field.field_key or "").lower()
    label = (field.label or "").lower()
    return "kritik" in key or "kritik" in label or "critical" in key or "critical" in label


def _apply_part_usage(order, used_parts_text):
    parsed = _parse_part_usage_input(used_parts_text)
    if not parsed:
        return []

    WorkOrderPartUsage.query.filter_by(work_order_id=order.id).delete()
    low_stock_alerts = []
    for part_code, quantity in parsed:
        spare_part = SparePart.query.filter(
            SparePart.is_deleted.is_(False),
            SparePart.is_active.is_(True),
            SparePart.part_code.ilike(part_code),
        ).first()
        if not spare_part:
            raise ValueError(f"Yedek parça bulunamadı: {part_code}")

        stock = SparePartStock.query.filter_by(
            spare_part_id=spare_part.id,
            airport_id=order.asset.havalimani_id,
            is_deleted=False,
            is_active=True,
        ).first()
        if not stock:
            raise ValueError(f"Parça stoğu bulunamadı: {spare_part.part_code}")

        if stock.available_quantity < quantity:
            raise ValueError(
                f"Yetersiz stok: {spare_part.part_code} (Mevcut: {stock.available_quantity}, İstenen: {quantity})"
            )

        stock.consume(quantity)
        usage = WorkOrderPartUsage(
            work_order_id=order.id,
            spare_part_id=spare_part.id,
            quantity_used=quantity,
            note=f"{spare_part.part_code} iş emrinde tüketildi",
            consumed_from_stock_id=stock.id,
        )
        db.session.add(usage)
        audit_log(
            "parts.consume",
            outcome="success",
            work_order_id=order.id,
            part_code=spare_part.part_code,
            quantity_used=quantity,
            airport_id=order.asset.havalimani_id,
        )

        if stock.is_low_stock():
            low_stock_alerts.append(
                f"{spare_part.part_code} düşük stok seviyesine indi (kalan: {stock.available_quantity:.1f} {spare_part.unit or 'adet'})."
            )
    return low_stock_alerts


def _evaluate_meter_triggers(asset, meter_definition, reading):
    triggered_orders = []
    related_rules = MaintenanceTriggerRule.query.filter(
        MaintenanceTriggerRule.is_deleted.is_(False),
        MaintenanceTriggerRule.is_active.is_(True),
        MaintenanceTriggerRule.meter_definition_id == meter_definition.id,
    ).all()

    for rule in related_rules:
        if rule.asset_id and rule.asset_id != asset.id:
            continue
        if rule.equipment_template_id and rule.equipment_template_id != asset.equipment_template_id:
            continue

        threshold = float(rule.threshold_value or 0)
        if threshold <= 0:
            continue

        previous = float(rule.last_trigger_reading or 0)
        should_trigger = reading.reading_value >= threshold and (previous <= 0 or (reading.reading_value - previous) >= threshold)
        should_warn = reading.reading_value >= max(threshold - float(rule.warning_lead_value or 0), 0)

        if should_warn and asset.maintenance_state in {"normal", "", None}:
            asset.maintenance_state = "yaklasan"

        if not should_trigger:
            continue

        rule.last_trigger_reading = reading.reading_value
        rule.last_triggered_at = get_tr_now()
        asset.maintenance_state = "gecikmis"

        if rule.auto_create_work_order:
            work_order = WorkOrder(
                work_order_no=_next_work_order_no(),
                asset_id=asset.id,
                maintenance_type="bakim",
                work_order_type="preventive",
                source_type="meter_trigger",
                description=f"Sayaç tetikleyici: {rule.name} ({meter_definition.name}) eşiği aşıldı",
                target_date=get_tr_now().date() + timedelta(days=1),
                created_user_id=current_user.id,
                status="acik",
                priority="yuksek" if asset.is_critical else "orta",
            )
            db.session.add(work_order)
            db.session.flush()
            triggered_orders.append(work_order)
            audit_log(
                "work_order.auto_create",
                outcome="success",
                source_type="meter_trigger",
                work_order_id=work_order.id,
                asset_id=asset.id,
                trigger_rule_id=rule.id,
            )

            log_kaydet(
                "Bakım Sayaç",
                f"Otomatik iş emri oluşturuldu: {work_order.work_order_no} / Asset {asset.id} / Rule {rule.id}",
                commit=False,
            )

    asset.last_meter_sync_at = get_tr_now()
    return triggered_orders


def _finalize_work_order(order, result_text, used_parts, extra_notes, labor_hours, checklist_payload):
    checklist_fields = []
    if order.checklist_template:
        checklist_fields = order.checklist_template.fields
    elif order.asset.equipment_template and order.asset.equipment_template.default_maintenance_form:
        checklist_fields = order.asset.equipment_template.default_maintenance_form.fields

    WorkOrderChecklistResponse.query.filter_by(work_order_id=order.id).delete()
    response_snapshot = []
    has_critical_failure = False

    for field in checklist_fields:
        input_name = f"field_{field.id}"
        value = guvenli_metin(checklist_payload.get(input_name) or "")
        if field.is_required and not value:
            raise ValueError(f"Checklist alanı zorunlu: {field.label}")

        is_failure = value.strip().lower() in CHECKLIST_FAILURE_VALUES
        has_critical_failure = has_critical_failure or (_is_critical_field(field) and is_failure)

        entry = WorkOrderChecklistResponse(
            work_order_id=order.id,
            field_id=field.id,
            field_key=field.field_key,
            field_label=field.label,
            response_value=value,
            responded_by_id=current_user.id,
            is_failure=is_failure,
            approval_note=guvenli_metin(checklist_payload.get(f"approval_{field.id}") or ""),
        )
        db.session.add(entry)
        response_snapshot.append(
            {
                "key": field.field_key,
                "label": field.label,
                "type": field.field_type,
                "value": value,
                "is_failure": is_failure,
            }
        )

    low_stock_alerts = _apply_part_usage(order, used_parts)

    today = get_tr_now().date()
    order.status = "tamamlandi"
    order.completed_at = get_tr_now()
    order.result = result_text
    order.used_parts = used_parts
    order.extra_notes = extra_notes
    order.labor_hours = labor_hours
    order.labor_minutes = int((labor_hours or 0) * 60) if labor_hours is not None else order.labor_minutes
    order.completed_by_id = current_user.id
    order.completion_notes = extra_notes
    order.verification_status = "beklemede"
    if has_critical_failure:
        order.verification_status = "kritik_bulgu"
        order.is_repeat_failure = True

    order.asset.last_maintenance_date = today

    active_plan = MaintenancePlan.query.filter(
        MaintenancePlan.asset_id == order.asset.id,
        MaintenancePlan.is_deleted.is_(False),
        MaintenancePlan.is_active.is_(True),
    ).order_by(MaintenancePlan.updated_at.desc()).first()

    if active_plan:
        active_plan.last_maintenance_date = today
        next_date = active_plan.recalculate_next_due_date(today)
        order.asset.next_maintenance_date = next_date
    else:
        period = (
            order.asset.maintenance_period_days
            or (order.asset.equipment_template.maintenance_period_days if order.asset.equipment_template else None)
            or 180
        )
        order.asset.next_maintenance_date = today + timedelta(days=period)

    history = MaintenanceHistory(
        asset_id=order.asset.id,
        work_order_id=order.id,
        performed_by_id=current_user.id,
        maintenance_type=order.maintenance_type,
        performed_at=get_tr_now(),
        result=result_text,
        checklist_snapshot=json.dumps(response_snapshot, ensure_ascii=False),
        notes=extra_notes,
        next_maintenance_date=order.asset.next_maintenance_date,
        inspection_score=0 if has_critical_failure else 100 if response_snapshot else None,
        inspection_summary="Kritik checklist bulgusu var" if has_critical_failure else None,
        source_type=order.source_type or "manual",
    )
    db.session.add(history)
    return low_stock_alerts, has_critical_failure


@maintenance_bp.route("/bakim")
@login_required
@permission_required("maintenance.view")
def bakim_paneli():
    today = get_tr_now().date()
    soon_limit = today + timedelta(days=7)

    assets_query = _asset_scope()
    work_orders_query = _work_order_scope()

    upcoming_assets = assets_query.filter(
        InventoryAsset.next_maintenance_date.isnot(None),
        InventoryAsset.next_maintenance_date >= today,
        InventoryAsset.next_maintenance_date <= soon_limit,
    ).order_by(InventoryAsset.next_maintenance_date.asc()).all()

    overdue_assets = assets_query.filter(
        InventoryAsset.next_maintenance_date.isnot(None),
        InventoryAsset.next_maintenance_date < today,
        InventoryAsset.status != "pasif",
    ).order_by(InventoryAsset.next_maintenance_date.asc()).all()

    open_orders = work_orders_query.filter(WorkOrder.status.in_(STATUS_OPEN_SET)).all()
    critical_fault_assets = assets_query.filter(
        InventoryAsset.is_critical.is_(True),
        InventoryAsset.status.in_(["arizali", "bakimda"]),
    ).all()

    return render_template(
        "bakim_paneli.html",
        today=today,
        upcoming_assets=upcoming_assets,
        overdue_assets=overdue_assets,
        open_orders=open_orders,
        critical_fault_assets=critical_fault_assets,
        status_label=_status_label,
    )


@maintenance_bp.route("/bakim/takvim")
@login_required
@permission_required("maintenance.view")
def bakim_takvimi():
    assets = _asset_scope().filter(
        InventoryAsset.next_maintenance_date.isnot(None)
    ).order_by(InventoryAsset.next_maintenance_date.asc()).all()
    return render_template("bakim_takvimi.html", assets=assets, today=get_tr_now().date())


@maintenance_bp.route("/bakim/is-emirleri")
@login_required
@permission_required("workorder.view")
def is_emirleri():
    durum = request.args.get("durum", "").strip()
    oncelik = request.args.get("oncelik", "").strip()
    bakim_turu = request.args.get("bakim_turu", "").strip()
    work_order_type = request.args.get("work_order_type", "").strip()

    query = _work_order_scope()
    if durum:
        query = query.filter(WorkOrder.status == durum)
    if oncelik:
        query = query.filter(WorkOrder.priority == oncelik)
    if bakim_turu:
        query = query.filter(WorkOrder.maintenance_type == bakim_turu)
    if work_order_type:
        query = query.filter(WorkOrder.work_order_type == work_order_type)

    orders = query.order_by(WorkOrder.opened_at.desc()).all()

    return render_template(
        "is_emirleri.html",
        orders=orders,
        statuses=ORDER_STATUSES,
        priorities=ORDER_PRIORITIES,
        work_order_types=WORK_ORDER_TYPES,
        status_label=_status_label,
        selected_status=durum,
        selected_priority=oncelik,
        selected_type=bakim_turu,
        selected_work_order_type=work_order_type,
    )


@maintenance_bp.route("/bakim/is-emri/yeni", methods=["GET", "POST"])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"), methods=["POST"])
@permission_required("workorder.create")
def is_emri_olustur():
    if not _can_create_work_order():
        abort(403)

    visible_assets = _asset_scope().order_by(InventoryAsset.created_at.desc()).all()
    visible_users = _user_scope().order_by(Kullanici.tam_ad.asc(), Kullanici.kullanici_adi.asc()).all()
    form_templates = MaintenanceFormTemplate.query.filter_by(is_deleted=False, is_active=True).all()

    if request.method == "POST":
        asset_id = request.form.get("asset_id", type=int)
        asset = db.session.get(InventoryAsset, asset_id)
        if not asset or asset.is_deleted or not _asset_allowed(asset):
            flash("Seçilen ekipman bulunamadı veya erişim yetkiniz yok.", "danger")
            return redirect(url_for("maintenance.is_emri_olustur"))

        assigned_user_id = request.form.get("assigned_user_id", type=int)
        assigned_user = None
        if assigned_user_id:
            assigned_user = db.session.get(Kullanici, assigned_user_id)
            if not assigned_user or assigned_user.is_deleted:
                flash("Atanacak personel bulunamadı.", "danger")
                return redirect(url_for("maintenance.is_emri_olustur"))
            if not _user_allowed(assigned_user):
                abort(403)
        checklist_template_id = request.form.get("checklist_template_id", type=int)
        selected_work_order_type = (request.form.get("work_order_type") or "preventive").strip()
        selected_source_type = (request.form.get("source_type") or "manual").strip()
        if selected_work_order_type not in WORK_ORDER_TYPES:
            selected_work_order_type = "preventive"
        if selected_source_type not in SOURCE_TYPES:
            selected_source_type = "manual"

        work_order = WorkOrder(
            work_order_no=_next_work_order_no(),
            asset_id=asset.id,
            maintenance_type=(request.form.get("maintenance_type") or "bakim").strip(),
            work_order_type=selected_work_order_type,
            source_type=selected_source_type,
            description=guvenli_metin(request.form.get("description") or ""),
            target_date=_parse_date(request.form.get("target_date")),
            sla_target_at=_parse_datetime(request.form.get("sla_target_at")),
            assigned_user_id=assigned_user.id if assigned_user else None,
            created_user_id=current_user.id,
            status="acik",
            priority=(request.form.get("priority") or "orta").strip(),
            checklist_template_id=checklist_template_id or None,
            extra_notes=guvenli_metin(request.form.get("extra_notes") or ""),
            failure_code=guvenli_metin(request.form.get("failure_code") or "").strip(),
        )

        if not work_order.description:
            flash("İş emri açıklaması zorunludur.", "danger")
            return redirect(url_for("maintenance.is_emri_olustur"))

        db.session.add(work_order)
        db.session.commit()
        log_kaydet("Bakım İş Emri", f"İş emri açıldı: {work_order.work_order_no}")
        flash("İş emri başarıyla oluşturuldu.", "success")
        return redirect(url_for("maintenance.is_emri_detay", work_order_id=work_order.id))

    return render_template(
        "is_emri_detay.html",
        mode="create",
        order=None,
        assets=visible_assets,
        users=visible_users,
        form_templates=form_templates,
        statuses=ORDER_STATUSES,
        priorities=ORDER_PRIORITIES,
        work_order_types=WORK_ORDER_TYPES,
        source_types=SOURCE_TYPES,
        status_label=_status_label,
    )


@maintenance_bp.route("/bakim/is-emri/<int:work_order_id>")
@login_required
@permission_required("workorder.view")
def is_emri_detay(work_order_id):
    order = _work_order_scope().filter(WorkOrder.id == work_order_id).first_or_404()
    checklist_fields = []
    if order.checklist_template:
        checklist_fields = order.checklist_template.fields
    elif order.asset.equipment_template and order.asset.equipment_template.default_maintenance_form:
        checklist_fields = order.asset.equipment_template.default_maintenance_form.fields

    existing_responses = {
        response.field_key: response.response_value for response in order.checklist_responses
    }

    users = _user_scope().order_by(Kullanici.tam_ad.asc(), Kullanici.kullanici_adi.asc()).all()
    return render_template(
        "is_emri_detay.html",
        mode="detail",
        order=order,
        checklist_fields=checklist_fields,
        response_map=existing_responses,
        field_meta=_field_meta,
        users=users,
        statuses=ORDER_STATUSES,
        priorities=ORDER_PRIORITIES,
        work_order_types=WORK_ORDER_TYPES,
        source_types=SOURCE_TYPES,
        status_label=_status_label,
    )


@maintenance_bp.route("/bakim/asset/<int:asset_id>/hizli", methods=["GET"], endpoint="asset_hizli_bakim_legacy")
@login_required
@permission_required("maintenance.view")
def asset_hizli_bakim_legacy(asset_id):
    flash("Bakım akışı artık güvenli form gönderimi ile başlatılır.", "warning")
    return redirect(url_for("inventory.quick_asset_view", asset_id=asset_id))


@maintenance_bp.route("/bakim/asset/<int:asset_id>/hizli", methods=["POST"])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
@permission_required("maintenance.view")
def asset_hizli_bakim(asset_id):
    asset = _asset_scope().filter(InventoryAsset.id == asset_id).first_or_404()
    if not _asset_allowed(asset):
        abort(403)

    order, created = _ensure_asset_work_order(asset)
    if created:
        db.session.commit()
        log_kaydet(
            "Bakım İş Emri",
            f"Demo/saha bakım akışı için iş emri oluşturuldu: {order.work_order_no}",
            event_key="workorder.quick_create",
            target_model="WorkOrder",
            target_id=order.id,
        )
    return redirect(url_for("maintenance.work_order_quick_close", work_order_id=order.id))


@maintenance_bp.route("/bakim/is-emri/<int:work_order_id>/durum", methods=["POST"])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
@permission_required("workorder.edit")
def is_emri_durum_guncelle(work_order_id):
    order = _work_order_scope().filter(WorkOrder.id == work_order_id).first_or_404()

    if not (_can_edit_work_order() or order.assigned_user_id == current_user.id):
        abort(403)

    yeni_durum = (request.form.get("status") or "").strip()
    if yeni_durum not in ORDER_STATUSES:
        flash("Geçersiz iş emri durumu.", "danger")
        return redirect(url_for("maintenance.is_emri_detay", work_order_id=order.id))

    if get_effective_role(current_user) == CANONICAL_ROLE_TEAM_MEMBER and yeni_durum not in ["islemde", "tamamlandi", "beklemede_parca"]:
        abort(403)

    order.status = yeni_durum
    assigned_user_id = request.form.get("assigned_user_id", type=int)
    if assigned_user_id and _can_assign_work_order():
        assigned_user = db.session.get(Kullanici, assigned_user_id)
        if not assigned_user or assigned_user.is_deleted:
            flash("Atanacak personel bulunamadı.", "danger")
            return redirect(url_for("maintenance.is_emri_detay", work_order_id=order.id))
        if not _user_allowed(assigned_user):
            abort(403)
        order.assigned_user_id = assigned_user.id
    if yeni_durum == "beklemede_onay" and _can_edit_work_order():
        order.approved_by_id = request.form.get("approved_by_id", type=int) or current_user.id
    if yeni_durum == "tamamlandi":
        order.completed_by_id = current_user.id

    db.session.commit()
    log_kaydet("Bakım İş Emri", f"Durum güncellendi: {order.work_order_no} -> {yeni_durum}")
    flash("İş emri durumu güncellendi.", "success")
    return redirect(url_for("maintenance.is_emri_detay", work_order_id=order.id))


@maintenance_bp.route("/bakim/is-emri/<int:work_order_id>/kapat", methods=["POST"])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
@permission_required("workorder.close")
def is_emri_kapat(work_order_id):
    order = _work_order_scope().filter(WorkOrder.id == work_order_id).first_or_404()

    if not (_can_edit_work_order() or order.assigned_user_id == current_user.id):
        abort(403)

    if order.status == "tamamlandi":
        flash("Bu iş emri zaten tamamlandı.", "info")
        return redirect(url_for("maintenance.is_emri_detay", work_order_id=order.id))

    result_text = guvenli_metin(request.form.get("result") or "")
    used_parts = guvenli_metin(request.form.get("used_parts") or "")
    extra_notes = guvenli_metin(request.form.get("extra_notes") or "")
    labor_hours = request.form.get("labor_hours", type=float)

    if order.priority == "kritik" and not has_permission("workorder.approve"):
        payload = json.dumps(
            {
                "work_order_id": order.id,
                "requested_by_id": current_user.id,
                "result_text": result_text,
                "used_parts": used_parts,
                "extra_notes": extra_notes,
                "labor_hours": labor_hours,
                "checklist_payload": dict(request.form),
            },
            ensure_ascii=False,
        )
        approval = create_approval_request(
            approval_type="workorder_close",
            target_model="WorkOrder",
            target_id=order.id,
            requested_by_id=current_user.id,
            request_payload=payload,
            commit=False,
        )
        if approval:
            log_kaydet(
                "Approval",
                f"Kritik iş emri kapanışı onaya gönderildi: {order.work_order_no}",
                event_key="workorder.close.pending",
                target_model="WorkOrder",
                target_id=order.id,
                commit=False,
            )
            create_notification(
                current_user.id,
                "approval_pending",
                "İş emri kapanışı onay bekliyor",
                f"{order.work_order_no} kritik olduğu için yönetici onayına gönderildi.",
                link_url=url_for("admin.approvals"),
                severity="warning",
                commit=False,
            )
            db.session.commit()
            flash("Kritik iş emri kapanışı onaya gönderildi.", "warning")
            return redirect(url_for("maintenance.is_emri_detay", work_order_id=order.id))

    try:
        low_stock_alerts, has_critical_failure = _finalize_work_order(
            order=order,
            result_text=result_text,
            used_parts=used_parts,
            extra_notes=extra_notes,
            labor_hours=labor_hours,
            checklist_payload=request.form,
        )
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
        return redirect(url_for("maintenance.is_emri_detay", work_order_id=order.id))

    log_kaydet("Bakım İş Emri", f"İş emri kapatıldı: {order.work_order_no}")
    if low_stock_alerts:
        for message in low_stock_alerts:
            create_notification(
                current_user.id,
                "low_stock",
                "Düşük stok uyarısı",
                message,
                link_url=url_for("inventory.envanter"),
                severity="warning",
            )
            flash(message, "warning")
    if has_critical_failure:
        flash("Kritik checklist bulgusu tespit edildi. Düzeltici iş emri önerilir.", "warning")
    flash("İş emri tamamlandı ve bakım geçmişi oluşturuldu.", "success")
    return redirect(url_for("maintenance.is_emri_detay", work_order_id=order.id))


@maintenance_bp.route("/work-orders/<int:work_order_id>/quick-close", methods=["GET", "POST"])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"), methods=["POST"])
@permission_required("workorder.close")
def work_order_quick_close(work_order_id):
    order = _work_order_scope().filter(WorkOrder.id == work_order_id).first_or_404()
    if not (_can_edit_work_order() or order.assigned_user_id == current_user.id):
        abort(403)

    if request.method == "POST":
        result_text = guvenli_metin(request.form.get("result") or "Saha hızlı kapanış")
        extra_notes = guvenli_metin(request.form.get("extra_notes") or "")
        labor_hours = request.form.get("labor_hours", type=float)
        used_parts = guvenli_metin(request.form.get("used_parts") or "")
        if order.priority == "kritik" and not has_permission("workorder.approve"):
            payload = json.dumps(
                {
                    "work_order_id": order.id,
                    "requested_by_id": current_user.id,
                    "result_text": result_text,
                    "used_parts": used_parts,
                    "extra_notes": extra_notes,
                    "labor_hours": labor_hours,
                    "checklist_payload": dict(request.form),
                },
                ensure_ascii=False,
            )
            approval = create_approval_request(
                approval_type="workorder_close",
                target_model="WorkOrder",
                target_id=order.id,
                requested_by_id=current_user.id,
                request_payload=payload,
                commit=False,
            )
            if approval:
                create_notification(
                    current_user.id,
                    "approval_pending",
                    "Hızlı kapanış onaya gönderildi",
                    f"{order.work_order_no} kritik iş emri olduğu için approval bekliyor.",
                    link_url=url_for("admin.approvals"),
                    severity="warning",
                    commit=False,
                )
                db.session.commit()
                flash("Kritik iş emri hızlı kapanıştan önce onaya gönderildi.", "warning")
                return redirect(url_for("maintenance.is_emri_detay", work_order_id=order.id))
        try:
            low_stock_alerts, _ = _finalize_work_order(
                order=order,
                result_text=result_text,
                used_parts=used_parts,
                extra_notes=extra_notes,
                labor_hours=labor_hours,
                checklist_payload=request.form,
            )
            db.session.commit()
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
            return redirect(url_for("maintenance.work_order_quick_close", work_order_id=order.id))

        log_kaydet("Saha Hızlı Kapanış", f"İş emri mobil akıştan kapatıldı: {order.work_order_no}")
        for message in low_stock_alerts:
            flash(message, "warning")
        flash("İş emri hızlı akışla tamamlandı.", "success")
        return redirect(url_for("maintenance.is_emri_detay", work_order_id=order.id))

    checklist_fields = []
    if order.checklist_template:
        checklist_fields = order.checklist_template.fields
    elif order.asset.equipment_template and order.asset.equipment_template.default_maintenance_form:
        checklist_fields = order.asset.equipment_template.default_maintenance_form.fields
    return render_template(
        "quick_close_work_order.html",
        order=order,
        checklist_fields=checklist_fields,
        field_meta=_field_meta,
    )


@maintenance_bp.route("/inspection/<int:work_order_id>/mobile", methods=["GET", "POST"])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"), methods=["POST"])
@permission_required("maintenance.edit")
def inspection_mobile(work_order_id):
    order = _work_order_scope().filter(WorkOrder.id == work_order_id).first_or_404()
    if not (_can_edit_work_order() or order.assigned_user_id == current_user.id):
        abort(403)

    checklist_fields = []
    if order.checklist_template:
        checklist_fields = order.checklist_template.fields
    elif order.asset.equipment_template and order.asset.equipment_template.default_maintenance_form:
        checklist_fields = order.asset.equipment_template.default_maintenance_form.fields

    if request.method == "POST":
        WorkOrderChecklistResponse.query.filter_by(work_order_id=order.id).delete()
        critical_failure_detected = False

        for field in checklist_fields:
            raw_value = guvenli_metin(request.form.get(f"field_{field.id}") or "")
            if field.is_required and not raw_value:
                flash(f"Checklist alanı zorunlu: {field.label}", "danger")
                return redirect(url_for("maintenance.inspection_mobile", work_order_id=order.id))

            is_failure = raw_value.strip().lower() in CHECKLIST_FAILURE_VALUES
            if _is_critical_field(field) and is_failure:
                critical_failure_detected = True

            db.session.add(
                WorkOrderChecklistResponse(
                    work_order_id=order.id,
                    field_id=field.id,
                    field_key=field.field_key,
                    field_label=field.label,
                    response_value=raw_value,
                    responded_by_id=current_user.id,
                    is_failure=is_failure,
                    approval_note=guvenli_metin(request.form.get(f"approval_{field.id}") or ""),
                )
            )

        if critical_failure_detected and request.form.get("auto_corrective") == "on":
            corrective_order = WorkOrder(
                work_order_no=_next_work_order_no(),
                asset_id=order.asset_id,
                maintenance_type="ariza",
                work_order_type="corrective",
                source_type="inspection_failure",
                description=f"Mobil inspection kritik bulgu: {order.work_order_no}",
                target_date=get_tr_now().date(),
                created_user_id=current_user.id,
                assigned_user_id=order.assigned_user_id or current_user.id,
                status="acik",
                priority="kritik",
                is_repeat_failure=True,
            )
            db.session.add(corrective_order)
            flash("Kritik bulgu için otomatik düzeltici iş emri açıldı.", "warning")
            log_kaydet(
                "Inspection",
                f"Kritik inspection fail -> corrective WO: {corrective_order.work_order_no}",
                commit=False,
            )
            audit_log(
                "inspection.failure.corrective",
                outcome="success",
                source_work_order_id=order.id,
                asset_id=order.asset_id,
            )

        db.session.commit()
        log_kaydet("Inspection", f"Mobil checklist güncellendi: {order.work_order_no}")
        audit_log(
            "inspection.mobile.save",
            outcome="success",
            work_order_id=order.id,
            critical_failure=critical_failure_detected,
        )
        flash("Saha checklist kaydı alındı.", "success")
        return redirect(url_for("maintenance.is_emri_detay", work_order_id=order.id))

    return render_template(
        "inspection_mobile.html",
        order=order,
        checklist_fields=checklist_fields,
    )


@maintenance_bp.route("/bakim/sayaclar", methods=["GET", "POST"])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"), methods=["POST"])
@permission_required("maintenance.edit")
def meter_readings():
    if get_effective_role(current_user) == CANONICAL_ROLE_ADMIN:
        abort(403)

    assets = _asset_scope().order_by(InventoryAsset.updated_at.desc()).all()
    selected_asset_id = request.args.get("asset_id", type=int)
    selected_asset = None
    if selected_asset_id:
        selected_asset = _asset_scope().filter(InventoryAsset.id == selected_asset_id).first()

    if request.method == "POST":
        asset_id = request.form.get("asset_id", type=int)
        asset = _asset_scope().filter(InventoryAsset.id == asset_id).first()
        if not asset:
            flash("Sayaç kaydı için ekipman bulunamadı.", "danger")
            return redirect(url_for("maintenance.meter_readings"))

        meter_id = request.form.get("meter_definition_id", type=int)
        meter_definition = None
        if meter_id:
            meter_definition = MeterDefinition.query.filter_by(id=meter_id, is_deleted=False).first()
        if not meter_definition:
            meter_name = guvenli_metin(request.form.get("meter_name") or "").strip()
            meter_type = guvenli_metin(request.form.get("meter_type") or "hours").strip() or "hours"
            if not meter_name:
                flash("Sayaç seçimi veya sayaç adı zorunludur.", "danger")
                return redirect(url_for("maintenance.meter_readings", asset_id=asset.id))
            meter_definition = MeterDefinition(
                name=meter_name,
                meter_type=meter_type,
                unit=guvenli_metin(request.form.get("unit") or "").strip() or "adet",
                asset_id=asset.id,
                equipment_template_id=asset.equipment_template_id,
                is_active=True,
            )
            db.session.add(meter_definition)
            db.session.flush()

        reading_value = _to_float(request.form.get("reading_value"), -1)
        if reading_value < 0:
            flash("Sayaç değeri 0 veya daha büyük olmalıdır.", "danger")
            return redirect(url_for("maintenance.meter_readings", asset_id=asset.id))

        reading = AssetMeterReading(
            asset_id=asset.id,
            meter_definition_id=meter_definition.id,
            reading_value=reading_value,
            reading_at=get_tr_now(),
            note=guvenli_metin(request.form.get("note") or ""),
            recorded_by_id=current_user.id,
        )
        db.session.add(reading)
        triggered_orders = _evaluate_meter_triggers(asset, meter_definition, reading)
        db.session.commit()

        log_kaydet(
            "Sayaç Okuma",
            f"Sayaç kaydı eklendi: Asset {asset.id}, Meter {meter_definition.name}, Değer {reading_value}",
        )
        audit_log(
            "meter.reading.create",
            outcome="success",
            asset_id=asset.id,
            meter_id=meter_definition.id,
            reading_value=reading_value,
            auto_work_orders=len(triggered_orders),
        )
        if triggered_orders:
            flash(f"Sayaç eşiği aşıldı. {len(triggered_orders)} otomatik iş emri oluşturuldu.", "warning")
        flash("Sayaç kaydı işlendi.", "success")
        return redirect(url_for("maintenance.meter_readings", asset_id=asset.id))

    reading_query = AssetMeterReading.query.filter_by(is_deleted=False).join(InventoryAsset)
    if not _can_view_all():
        reading_query = reading_query.filter(InventoryAsset.havalimani_id == current_user.havalimani_id)
    if selected_asset:
        reading_query = reading_query.filter(AssetMeterReading.asset_id == selected_asset.id)

    readings = reading_query.order_by(AssetMeterReading.reading_at.desc()).limit(100).all()
    meters = MeterDefinition.query.filter_by(is_deleted=False, is_active=True).order_by(MeterDefinition.name.asc()).all()

    return render_template(
        "meter_readings.html",
        assets=assets,
        selected_asset=selected_asset,
        meters=meters,
        readings=readings,
    )


@maintenance_bp.route("/bakim/gecmis")
@login_required
@permission_required("maintenance.view")
def bakim_gecmisi():
    query = MaintenanceHistory.query.filter_by(is_deleted=False).join(InventoryAsset)
    if not _can_view_all():
        query = query.filter(InventoryAsset.havalimani_id == current_user.havalimani_id)
    histories = query.order_by(MaintenanceHistory.performed_at.desc()).all()
    return render_template("bakim_gecmisi.html", histories=histories)


@maintenance_bp.route("/bakim/form-sablonlari", methods=["GET", "POST"])
@login_required
@permission_required("maintenance.plan.change", "maintenance.templates.manage", any_of=True)
def bakim_formu_yonetimi():
    if not _can_manage_form_catalog():
        abort(403)

    if request.method == "POST":
        if not _can_manage_form_catalog():
            abort(403)

        name = guvenli_metin(request.form.get("name") or "").strip()
        description = guvenli_metin(request.form.get("description") or "").strip()
        raw_fields = request.form.get("fields", "")

        if not name:
            flash("Form şablonu adı zorunludur.", "danger")
            return redirect(url_for("maintenance.bakim_formu_yonetimi"))

        template = MaintenanceFormTemplate(name=name, description=description, is_active=True)
        db.session.add(template)
        db.session.flush()

        parsed_rows = _parse_checklist_rows(raw_fields)
        for item in parsed_rows:
            field_key = f"field_{template.id}_{item['order_index']}"
            db.session.add(
                MaintenanceFormField(
                    form_template_id=template.id,
                    field_key=field_key,
                    label=item["label"],
                    field_type=item["field_type"],
                    is_required=item["is_required"],
                    order_index=item["order_index"],
                    options_json=json.dumps(
                        {
                            "options": item["options"],
                            "help_text": item["help_text"],
                            "is_critical": item["is_critical"],
                        },
                        ensure_ascii=False,
                    ),
                )
            )

        db.session.commit()
        log_kaydet("Bakım Formu", f"Bakım form şablonu eklendi: {template.name}")
        flash("Bakım formu şablonu oluşturuldu.", "success")
        return redirect(url_for("maintenance.bakim_formu_yonetimi"))

    templates = MaintenanceFormTemplate.query.filter_by(is_deleted=False).order_by(
        MaintenanceFormTemplate.created_at.desc()
    ).all()
    return render_template(
        "bakim_formu_yonetimi.html",
        templates=templates,
        field_type_labels=CHECKLIST_FIELD_TYPES,
        field_meta=_field_meta,
    )


@maintenance_bp.route("/bakim/geciken")
@login_required
@permission_required("maintenance.view")
def geciken_bakimlar():
    today = get_tr_now().date()
    assets = _asset_scope().filter(
        InventoryAsset.next_maintenance_date.isnot(None),
        InventoryAsset.next_maintenance_date < today,
    ).order_by(InventoryAsset.next_maintenance_date.asc()).all()
    return render_template("bakim_takvimi.html", assets=assets, today=today, overdue_only=True)


@maintenance_bp.route("/bakim/ekipman-sablonlari", methods=["GET", "POST"])
@login_required
@permission_required("maintenance.plan.change", "maintenance.instructions.manage", any_of=True)
def ekipman_sablonlari():
    selectable_catalog, selectable_categories = _build_instruction_catalog_options()
    maintenance_form_equipment_options = _build_maintenance_form_equipment_options()

    if request.method == "POST":
        form_action = (request.form.get("form_action") or "").strip()
        if form_action == "create_maintenance_form":
            if not _can_manage_instruction_maintenance_forms():
                abort(403)

            if not maintenance_form_equipment_options:
                flash("Önce merkezi ekipman şablonu oluşturulmalıdır.", "danger")
                return redirect(url_for("maintenance.ekipman_sablonlari"))

            equipment_template_id = request.form.get("form_equipment_template_id", type=int)
            selected_period = _normalize_period_type(request.form.get("periyot_turu"))
            raw_steps_payload = request.form.get("maintenance_steps_payload", "")

            if not equipment_template_id:
                flash("Bakım formu için merkezi ekipman seçmelisiniz.", "danger")
                return redirect(url_for("maintenance.ekipman_sablonlari"))

            equipment_template = EquipmentTemplate.query.filter_by(
                id=equipment_template_id,
                is_deleted=False,
                is_active=True,
            ).first()
            if equipment_template is None:
                flash("Seçilen ekipman şablonu sistemde bulunamadı.", "danger")
                return redirect(url_for("maintenance.ekipman_sablonlari"))

            if selected_period is None:
                flash("Bakım periyot türü seçmelisiniz.", "danger")
                return redirect(url_for("maintenance.ekipman_sablonlari"))

            step_rows, parse_error = _parse_maintenance_step_rows(raw_steps_payload)
            if parse_error:
                flash(parse_error, "danger")
                return redirect(url_for("maintenance.ekipman_sablonlari"))
            if not step_rows:
                flash("En az 1 bakım adımı eklemelisiniz.", "danger")
                return redirect(url_for("maintenance.ekipman_sablonlari"))

            duplicate = MaintenanceFormTemplate.query.filter(
                MaintenanceFormTemplate.is_deleted.is_(False),
                MaintenanceFormTemplate.equipment_template_id == equipment_template.id,
                MaintenanceFormTemplate.period_type == selected_period,
            ).first()
            if duplicate:
                flash("Bu ekipman ve periyot için bakım formu zaten kayıtlı.", "danger")
                return redirect(url_for("maintenance.ekipman_sablonlari"))

            period_label = MAINTENANCE_PERIOD_TYPES[selected_period]
            template_name = _build_maintenance_form_name(equipment_template, period_label)
            template_description = f"{equipment_template.name} için {period_label.lower()} bakım adımları."

            new_template = MaintenanceFormTemplate(
                name=template_name,
                description=template_description,
                equipment_template_id=equipment_template.id,
                period_type=selected_period,
                is_active=True,
            )
            db.session.add(new_template)
            db.session.flush()

            for order_index, label in enumerate(step_rows, start=1):
                db.session.add(
                    MaintenanceFormField(
                        form_template_id=new_template.id,
                        field_key=f"step_{new_template.id}_{order_index}",
                        label=label,
                        field_type="yes_no",
                        is_required=True,
                        order_index=order_index,
                        options_json=json.dumps({"options": [], "help_text": "", "is_critical": False}, ensure_ascii=False),
                    )
                )

            db.session.commit()
            log_kaydet("Bakım Formu", f"Bakım formu oluşturuldu: {new_template.name}")
            flash("Bakım formu oluşturuldu.", "success")
            return redirect(url_for("maintenance.ekipman_sablonlari"))

        if form_action == "delete_maintenance_form":
            if not _can_manage_instruction_maintenance_forms():
                abort(403)

            form_template_id = request.form.get("form_template_id", type=int)
            if not form_template_id:
                flash("Silinecek bakım formu seçilemedi.", "danger")
                return redirect(url_for("maintenance.ekipman_sablonlari"))

            template = MaintenanceFormTemplate.query.filter_by(
                id=form_template_id,
                is_deleted=False,
            ).first()
            if template is None:
                flash("Bakım formu bulunamadı.", "danger")
                return redirect(url_for("maintenance.ekipman_sablonlari"))

            template.is_active = False
            template.soft_delete()
            for field in template.fields:
                if not field.is_deleted:
                    field.soft_delete()

            db.session.commit()
            log_kaydet("Bakım Formu", f"Bakım formu silindi: {template.name}")
            flash("Bakım formu silindi.", "success")
            return redirect(url_for("maintenance.ekipman_sablonlari"))

        if not _can_manage_instruction_catalog():
            abort(403)

        selected_template_id = request.form.get("selected_template_id", type=int)
        selected_category = guvenli_metin(request.form.get("category") or "").strip()
        selected_name = guvenli_metin(request.form.get("name") or "").strip()
        selected_brand = guvenli_metin(request.form.get("brand") or "").strip().replace("__EMPTY__", "")
        selected_model_code = guvenli_metin(request.form.get("model_code") or "").strip().replace("__EMPTY__", "")

        selected_catalog_item = next((item for item in selectable_catalog if item["id"] == selected_template_id), None)
        if selected_catalog_item is None:
            flash("Bakım talimatı oluşturmak için sistemde tanımlı ve envantere eklenmiş bir ekipman seçin.", "danger")
            return redirect(url_for("maintenance.ekipman_sablonlari"))

        if (
            selected_category != selected_catalog_item["category"]
            or selected_name != selected_catalog_item["name"]
            or selected_brand != selected_catalog_item["brand"]
            or selected_model_code != selected_catalog_item["model_code"]
        ):
            flash("Seçilen ekipman bilgisi sistem kayıtlarıyla eşleşmiyor.", "danger")
            return redirect(url_for("maintenance.ekipman_sablonlari"))

        template = EquipmentTemplate.query.filter_by(
            id=selected_template_id,
            is_deleted=False,
            is_active=True,
        ).first_or_404()
        template.description = guvenli_metin(request.form.get("description") or "").strip() or template.description
        template.technical_specs = (
            guvenli_metin(request.form.get("technical_specs") or "").strip() or template.technical_specs
        )
        template.maintenance_period_days = (
            request.form.get("maintenance_period_days", type=int)
            or template.maintenance_period_days
            or 180
        )
        template.default_maintenance_form_id = request.form.get("default_maintenance_form_id", type=int) or None

        instruction = template.maintenance_instruction
        instruction_title = guvenli_metin(request.form.get("instruction_title") or "").strip()
        instruction_description = guvenli_metin(request.form.get("instruction_description") or "").strip()
        manual_url = guvenli_metin(request.form.get("manual_url") or "").strip()
        visual_url = guvenli_metin(request.form.get("visual_url") or "").strip()
        revision_no = guvenli_metin(request.form.get("revision_no") or "").strip()
        instruction_notes = guvenli_metin(request.form.get("instruction_notes") or "").strip()
        has_instruction_payload = bool(
            instruction
            or instruction_title
            or instruction_description
            or manual_url
            or visual_url
            or revision_no
            or request.form.get("revision_date")
            or instruction_notes
        )
        if instruction is None and has_instruction_payload:
            instruction = MaintenanceInstruction(equipment_template_id=template.id, title=instruction_title or template.name)
            db.session.add(instruction)
        if instruction is not None:
            instruction.title = instruction_title or instruction.title or template.name
            instruction.description = instruction_description or instruction.description
            instruction.manual_url = manual_url or instruction.manual_url
            instruction.visual_url = visual_url or instruction.visual_url
            instruction.revision_no = revision_no or instruction.revision_no
            instruction.revision_date = _parse_date(request.form.get("revision_date")) or instruction.revision_date
            instruction.notes = instruction_notes or instruction.notes
            instruction.is_active = (request.form.get("instruction_active") or "on") == "on"

        db.session.commit()
        log_kaydet("Merkezi Şablon", f"Bakım talimatı kaydedildi: {template.name}")
        flash("Merkezi ekipman şablonu kaydedildi.", "success")
        return redirect(url_for("maintenance.ekipman_sablonlari"))

    templates = EquipmentTemplate.query.filter_by(is_deleted=False).order_by(
        EquipmentTemplate.created_at.desc()
    ).all()
    form_templates = MaintenanceFormTemplate.query.filter_by(is_deleted=False, is_active=True).order_by(
        MaintenanceFormTemplate.name.asc()
    ).all()
    maintenance_form_templates = MaintenanceFormTemplate.query.filter(
        MaintenanceFormTemplate.is_deleted.is_(False),
        MaintenanceFormTemplate.equipment_template_id.isnot(None),
        MaintenanceFormTemplate.period_type.isnot(None),
    ).order_by(MaintenanceFormTemplate.created_at.desc()).all()
    airports = Havalimani.query.filter_by(is_deleted=False).all()
    return render_template(
        "ekipman_sablonlari.html",
        templates=templates,
        form_templates=form_templates,
        airports=airports,
        selectable_catalog=selectable_catalog,
        selectable_categories=selectable_categories,
        maintenance_form_equipment_options=maintenance_form_equipment_options,
        maintenance_form_templates=maintenance_form_templates,
        maintenance_period_options=MAINTENANCE_PERIOD_TYPES,
        can_manage_maintenance_forms=_can_manage_instruction_maintenance_forms(),
    )


@maintenance_bp.route("/bakim/ekipman-sablonlari/<int:template_id>/talimat", methods=["GET", "POST"], endpoint="ekipman_talimat")
@login_required
@permission_required("maintenance.plan.change", "maintenance.instructions.manage", any_of=True)
def ekipman_talimat(template_id):
    template = EquipmentTemplate.query.filter_by(id=template_id, is_deleted=False).first_or_404()
    instruction = template.maintenance_instruction

    if request.method == "POST":
        if not _can_manage_instruction_catalog():
            abort(403)
        if instruction is None:
            instruction = MaintenanceInstruction(equipment_template_id=template.id, title=template.name)
            db.session.add(instruction)

        template.default_maintenance_form_id = request.form.get("default_maintenance_form_id", type=int) or None
        template.maintenance_period_days = request.form.get("maintenance_period_days", type=int) or template.maintenance_period_days or 180
        template.model_code = guvenli_metin(request.form.get("model_code") or template.model_code).strip()

        instruction.title = guvenli_metin(request.form.get("title") or template.name).strip() or template.name
        instruction.description = guvenli_metin(request.form.get("description") or "").strip()
        instruction.manual_url = guvenli_metin(request.form.get("manual_url") or "").strip()
        instruction.visual_url = guvenli_metin(request.form.get("visual_url") or "").strip()
        instruction.revision_no = guvenli_metin(request.form.get("revision_no") or "").strip()
        instruction.revision_date = _parse_date(request.form.get("revision_date"))
        instruction.notes = guvenli_metin(request.form.get("notes") or "").strip()
        instruction.is_active = (request.form.get("is_active") or "on") == "on"

        db.session.commit()
        flash("Bakım talimatı güncellendi.", "success")
        return redirect(url_for("maintenance.ekipman_talimat", template_id=template.id))

    form_templates = MaintenanceFormTemplate.query.filter_by(is_deleted=False, is_active=True).order_by(
        MaintenanceFormTemplate.name.asc()
    ).all()
    return render_template(
        "ekipman_talimat_detay.html",
        template=template,
        instruction=instruction,
        form_templates=form_templates,
    )


@maintenance_bp.route("/bakim/is-emri/<int:work_order_id>/pdf")
@login_required
@permission_required("workorder.view")
def is_emri_pdf(work_order_id):
    order = _work_order_scope().filter(WorkOrder.id == work_order_id).first_or_404()
    if order.checklist_template:
        checklist_fields = order.checklist_template.fields
    elif order.asset.equipment_template and order.asset.equipment_template.default_maintenance_form:
        checklist_fields = order.asset.equipment_template.default_maintenance_form.fields
    else:
        checklist_fields = []

    response_map = {response.field_key: response.response_value for response in order.checklist_responses}
    html = render_template(
        "maintenance_work_order_pdf.html",
        order=order,
        checklist_fields=checklist_fields,
        response_map=response_map,
        field_meta=_field_meta,
        generated_at=get_tr_now(),
    )
    payload = io.BytesIO()
    pisa.CreatePDF(html, dest=payload)
    payload.seek(0)
    return send_file(
        payload,
        as_attachment=True,
        download_name=f"{order.work_order_no}.pdf",
        mimetype="application/pdf",
    )
