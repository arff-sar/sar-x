import json

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from decorators import has_permission, permission_required, update_user_permission_overrides
from extensions import audit_log, create_notification, db, limiter, log_kaydet, table_exists
from models import ApprovalRequest, InventoryAsset, Kullanici, WorkOrder, get_tr_now
from . import admin_bp


def _can_review_approval(item):
    if item.approval_type in {"role_change", "permission_change"}:
        return has_permission("roles.manage")
    return has_permission("workorder.approve") or has_permission("roles.manage")


def _apply_role_change(payload, approver_id):
    user = db.session.get(Kullanici, payload.get("user_id"))
    if not user or user.is_deleted:
        return False

    previous_role = user.rol
    next_role = payload.get("rol") or user.rol
    user.tam_ad = payload.get("tam_ad") or user.tam_ad
    user.kullanici_adi = payload.get("k_adi") or user.kullanici_adi
    user.havalimani_id = payload.get("h_id")
    update_user_permission_overrides(
        user.id,
        payload.get("allow_permissions", []),
        payload.get("deny_permissions", []),
    )
    user.rol = next_role
    db.session.flush()
    log_kaydet(
        "Yetki",
        f"Rol değişikliği onaylandı: {user.kullanici_adi} ({previous_role} -> {next_role})",
        event_key="role.assignment.change",
        target_model="Kullanici",
        target_id=user.id,
    )
    audit_log(
        "role.assignment.change",
        outcome="success",
        target_user_id=user.id,
        previous_role=previous_role,
        new_role=next_role,
        approved_by=approver_id,
    )
    create_notification(
        user.id,
        "role_change",
        "Rol değişikliği onaylandı",
        f"Hesabınız için yeni rol ataması onaylandı: {next_role}",
        link_url=url_for("admin.kullanicilar"),
        severity="info",
        commit=False,
    )
    return True


def _apply_workorder_close(payload, approver_id):
    from routes.maintenance import _finalize_work_order

    order = db.session.get(WorkOrder, payload.get("work_order_id"))
    if not order or order.is_deleted:
        return False
    if order.status == "tamamlandi":
        return True

    low_stock_alerts, has_critical_failure = _finalize_work_order(
        order=order,
        result_text=payload.get("result_text") or "",
        used_parts=payload.get("used_parts") or "",
        extra_notes=payload.get("extra_notes") or "",
        labor_hours=payload.get("labor_hours"),
        checklist_payload=payload.get("checklist_payload") or {},
    )
    log_kaydet(
        "Bakım İş Emri",
        f"Approval ile iş emri kapatıldı: {order.work_order_no}",
        event_key="workorder.close.approved",
        target_model="WorkOrder",
        target_id=order.id,
        commit=False,
    )
    audit_log(
        "workorder.close.approved",
        outcome="success",
        work_order_id=order.id,
        approved_by=approver_id,
        low_stock_alerts=len(low_stock_alerts),
        critical_failure=has_critical_failure,
    )
    create_notification(
        payload.get("requested_by_id") or approver_id,
        "approval_result",
        "İş emri kapanışı onaylandı",
        f"{order.work_order_no} numaralı iş emri onay ile tamamlandı.",
        link_url=url_for("maintenance.is_emri_detay", work_order_id=order.id),
        severity="success",
        commit=False,
    )
    return True


def _apply_qr_regeneration(payload, approver_id):
    asset = db.session.get(InventoryAsset, payload.get("asset_id"))
    if not asset or asset.is_deleted:
        return False
    asset.qr_code = url_for("inventory.quick_asset_view", asset_id=asset.id, _external=True)
    log_kaydet(
        "QR",
        f"QR yeniden üretimi onaylandı: {asset.asset_code}",
        event_key="inventory.qr.regenerate",
        target_model="InventoryAsset",
        target_id=asset.id,
        commit=False,
    )
    audit_log(
        "inventory.qr.regenerate",
        outcome="success",
        asset_id=asset.id,
        approved_by=approver_id,
    )
    create_notification(
        payload.get("requested_by_id") or approver_id,
        "qr_regenerate",
        "QR yeniden üretimi onaylandı",
        f"{asset.asset_code} için QR yeniden üretimi onaylandı.",
        link_url=url_for("inventory.qr_uret", asset_id=asset.id),
        severity="warning",
        commit=False,
    )
    return True


def _apply_asset_lifecycle(payload, approver_id):
    from routes.inventory import _ensure_operational_state, _lifecycle_to_status

    asset = db.session.get(InventoryAsset, payload.get("asset_id"))
    if not asset or asset.is_deleted:
        return False

    lifecycle_status = str(payload.get("lifecycle_status") or "active").strip() or "active"
    target_airport_id = payload.get("target_airport_id")
    note = payload.get("note") or ""

    state = _ensure_operational_state(asset)
    state.lifecycle_status = lifecycle_status
    state.lifecycle_note = note
    asset.status = _lifecycle_to_status(lifecycle_status)
    if lifecycle_status == "transferred" and target_airport_id:
        asset.havalimani_id = target_airport_id
        if asset.legacy_material:
            asset.legacy_material.havalimani_id = target_airport_id

    log_kaydet(
        "Lifecycle",
        f"Lifecycle onay ile güncellendi: {asset.asset_code} -> {lifecycle_status}",
        event_key="asset.lifecycle.change",
        target_model="InventoryAsset",
        target_id=asset.id,
        commit=False,
    )
    audit_log(
        "asset.lifecycle.change",
        outcome="success",
        asset_id=asset.id,
        lifecycle_status=lifecycle_status,
        approved_by=approver_id,
    )
    create_notification(
        payload.get("requested_by_id") or approver_id,
        "approval_result",
        "Lifecycle değişimi onaylandı",
        f"{asset.asset_code} için lifecycle değişimi onaylandı: {lifecycle_status}.",
        link_url=url_for("inventory.asset_lifecycle"),
        severity="warning" if lifecycle_status in {"out_of_service", "decommissioned", "disposed"} else "info",
        commit=False,
    )
    return True


def _apply_approval(item):
    payload = {}
    try:
        payload = json.loads(item.request_payload or "{}")
    except (TypeError, ValueError):
        payload = {}

    if item.approval_type == "role_change":
        return _apply_role_change(payload, current_user.id)
    if item.approval_type == "workorder_close":
        return _apply_workorder_close(payload, current_user.id)
    if item.approval_type == "qr_regenerate":
        return _apply_qr_regeneration(payload, current_user.id)
    if item.approval_type == "asset_lifecycle":
        return _apply_asset_lifecycle(payload, current_user.id)
    return False


@admin_bp.route("/admin/approvals")
@login_required
@permission_required("roles.manage", "workorder.approve", any_of=True)
def approvals():
    if not table_exists("approval_request"):
        return render_template("admin/approvals.html", approvals=[])
    status = (request.args.get("status") or "").strip()
    query = ApprovalRequest.query.order_by(ApprovalRequest.created_at.desc())
    if status:
        query = query.filter_by(status=status)
    approvals = query.limit(200).all()
    approvals = [item for item in approvals if _can_review_approval(item)]
    return render_template("admin/approvals.html", approvals=approvals, selected_status=status)


@admin_bp.route("/admin/approvals/<int:id>", methods=["GET", "POST"])
@login_required
@permission_required("roles.manage", "workorder.approve", any_of=True)
@limiter.limit(lambda: "20 per minute", methods=["POST"])
def approval_detail(id):
    item = db.session.get(ApprovalRequest, id)
    if not item or not _can_review_approval(item):
        abort(403)

    if request.method == "POST":
        action = (request.form.get("action") or "").strip()
        review_note = request.form.get("review_note") or ""
        if item.status != "pending":
            flash("Bu talep zaten işlenmiş.", "info")
            return redirect(url_for("admin.approval_detail", id=item.id))
        if action == "approve":
            if not _apply_approval(item):
                flash("Onay uygulaması başarısız oldu.", "danger")
                return redirect(url_for("admin.approval_detail", id=item.id))
            if item.approval_type == "role_change":
                try:
                    payload = json.loads(item.request_payload or "{}")
                except (TypeError, ValueError):
                    payload = {}
                target_user = db.session.get(Kullanici, payload.get("user_id"))
                if target_user and payload.get("rol"):
                    target_user.rol = payload.get("rol")
            item.status = "approved"
        elif action == "reject":
            item.status = "rejected"
        else:
            item.status = "cancelled"
        item.approved_by_id = current_user.id
        item.review_note = review_note
        item.reviewed_at = get_tr_now()
        db.session.commit()
        log_kaydet(
            "Approval",
            f"Approval işlendi: #{item.id} -> {item.status}",
            event_key=f"approval.{item.status}",
            target_model=item.target_model,
            target_id=item.target_id,
        )
        audit_log(
            f"approval.{item.status}",
            outcome="success",
            approval_id=item.id,
            approval_type=item.approval_type,
            target_model=item.target_model,
            target_id=item.target_id,
        )
        create_notification(
            item.requested_by_id,
            "approval_result",
            "Onay talebi güncellendi",
            f"#{item.id} numaralı talebiniz {item.status} olarak işlendi.",
            link_url=url_for("admin.approval_detail", id=item.id),
            severity="success" if item.status == "approved" else "warning",
        )
        flash("Approval talebi işlendi.", "success")
        return redirect(url_for("admin.approval_detail", id=item.id))

    return render_template("admin/approvals.html", approvals=[item], focused_approval=item)
