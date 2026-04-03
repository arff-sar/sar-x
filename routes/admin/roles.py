import io
import json
import re

from flask import abort, current_app, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required
from xhtml2pdf import pisa

from decorators import (
    DEFAULT_ROLE_PERMISSIONS,
    get_manageable_role_options,
    get_permission_catalog,
    get_role_definition,
    get_role_permissions,
    get_role_options,
    is_core_role,
    permission_required,
    sync_authorization_registry,
    update_permission_matrix,
)
from extensions import audit_log, db, limiter, log_kaydet
from models import Kullanici, Permission, Role, RolePermission
from . import admin_bp


ROLE_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,48}$")


def _role_usage_counts():
    counts = {}
    for user in Kullanici.query.filter_by(is_deleted=False).all():
        counts[user.rol] = counts.get(user.rol, 0) + 1
    return counts


def _require_system_role_manager():
    if not current_user.is_sahip:
        abort(403)


def _normalize_custom_role_key(raw_value):
    value = re.sub(r"[^a-z0-9_]+", "_", (raw_value or "").strip().lower()).strip("_")
    return value


def _selected_permission_keys():
    return sorted({item for item in request.form.getlist("selected_permissions") if item})


@admin_bp.route('/admin/roles')
@login_required
@permission_required('roles.manage')
def roles():
    _require_system_role_manager()
    sync_authorization_registry()
    role_options = []
    for role in get_manageable_role_options():
        role_copy = dict(role)
        role_copy["permission_count"] = len(get_role_permissions(role["key"]))
        role_options.append(role_copy)
    counts = _role_usage_counts()
    return render_template(
        'admin/roles.html',
        role_options=role_options,
        role_counts=counts,
        default_role_permissions=DEFAULT_ROLE_PERMISSIONS,
        permission_catalog=get_permission_catalog(),
        core_role_keys={item["key"] for item in get_role_options()},
    )


@admin_bp.route('/admin/roles/<string:role_key>')
@login_required
@permission_required('roles.manage')
def role_detail(role_key):
    _require_system_role_manager()
    role = get_role_definition(role_key, include_custom=True, allow_legacy=True)
    if not role:
        return redirect(url_for('admin.roles'))
    counts = _role_usage_counts()
    return render_template(
        'admin/role_form.html',
        role=role,
        permission_catalog=get_permission_catalog(),
        role_permissions=get_role_permissions(role_key),
        role_user_count=counts.get(role_key, 0),
        is_core_role=is_core_role(role_key),
    )


def _build_summary_modules(permission_catalog, selected_permissions):
    summary_modules = []
    for module, permissions in permission_catalog.items():
        active_permissions = [permission for permission in permissions if permission["key"] in selected_permissions]
        summary_modules.append(
            {
                "key": module,
                "label": permissions[0]["module_label"] if permissions else module,
                "all_permissions": permissions,
                "active_permissions": active_permissions,
                "active_count": len(active_permissions),
            }
        )
    return summary_modules


def _permission_summary_for_role(role_key, selected_permissions=None):
    role_options = get_manageable_role_options()
    selected_role = get_role_definition(role_key, include_custom=True, allow_legacy=True) or (role_options[0] if role_options else None)
    selected_role_key = selected_role["key"] if selected_role else ""
    permission_catalog = get_permission_catalog()
    selected_permissions = set(selected_permissions) if selected_permissions is not None else get_role_permissions(selected_role_key)
    default_permissions = set(DEFAULT_ROLE_PERMISSIONS.get(selected_role_key, set()))
    summary_modules = _build_summary_modules(permission_catalog, selected_permissions)

    role_permission_map = {role["key"]: sorted(get_role_permissions(role["key"])) for role in role_options}
    return {
        "role_options": role_options,
        "selected_role": selected_role,
        "selected_role_key": selected_role_key,
        "selected_permissions": selected_permissions,
        "default_permissions": default_permissions,
        "permission_catalog": permission_catalog,
        "summary_modules": summary_modules,
        "role_permission_map_json": json.dumps(role_permission_map, ensure_ascii=False),
        "permission_catalog_json": json.dumps(permission_catalog, ensure_ascii=False),
    }


@admin_bp.route('/admin/permissions', methods=['GET', 'POST'])
@login_required
@limiter.limit(lambda: '20 per minute', methods=['POST'])
@permission_required('roles.manage')
def permissions():
    _require_system_role_manager()
    if request.method == 'POST':
        role_key = request.form.get('role_key')
        selected_permissions = set(request.form.getlist('selected_permissions'))
        baseline_permissions = set(DEFAULT_ROLE_PERMISSIONS.get(role_key, set()))
        allow_permissions = sorted(selected_permissions - baseline_permissions)
        deny_permissions = sorted(baseline_permissions - selected_permissions)
        update_permission_matrix(role_key, allow_permissions, deny_permissions)
        db.session.commit()
        log_kaydet('Yetki', f'Permission matrix guncellendi: {role_key}', event_key='permission.matrix.update', target_model='Role')
        audit_log('permission.matrix.update', outcome='success', role_key=role_key, grants=len(allow_permissions), denies=len(deny_permissions))
        flash('Permission matrix guncellendi.', 'success')
        return redirect(url_for('admin.permissions', role_key=role_key))

    role_key = request.args.get('role_key') or (get_role_options()[0]["key"] if get_role_options() else "")
    return render_template('admin/permissions.html', **_permission_summary_for_role(role_key))


@admin_bp.route('/admin/permissions/export/pdf', methods=['GET', 'POST'])
@login_required
@permission_required('roles.manage')
def permissions_export_pdf():
    _require_system_role_manager()
    role_key = request.values.get('role_key') or (get_role_options()[0]["key"] if get_role_options() else "")
    selected_permissions = request.form.getlist('selected_permissions') if request.method == 'POST' else None
    payload = _permission_summary_for_role(role_key, selected_permissions=selected_permissions)
    selected_role = payload["selected_role"]
    html = render_template(
        'admin/permission_matrix_pdf.html',
        selected_role=selected_role,
        summary_modules=payload["summary_modules"],
        selected_permissions=sorted(payload["selected_permissions"]),
    )
    output = io.BytesIO()
    pisa.CreatePDF(html, dest=output)
    output.seek(0)
    role_label = (selected_role or {}).get("label", "yetki_ozeti").replace(" ", "_")
    log_kaydet('Yetki', f'Permission matrix PDF oluşturuldu: {role_key}', event_key='permission.matrix.export', target_model='Role')
    audit_log('permission.matrix.export', outcome='success', role_key=role_key, format='pdf')
    return send_file(
        output,
        as_attachment=True,
        download_name=f"{role_label}_yetki_ozeti.pdf",
        mimetype="application/pdf",
    )


@admin_bp.route('/admin/roles/create', methods=['POST'])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
@permission_required('roles.manage')
def role_create():
    _require_system_role_manager()
    sync_authorization_registry()
    label = (request.form.get("label") or "").strip()
    role_key = _normalize_custom_role_key(request.form.get("key"))
    scope = (request.form.get("scope") or "global").strip()
    description = (request.form.get("description") or "").strip()

    if not label:
        flash("Rol adı zorunludur.", "danger")
        return redirect(url_for('admin.site_yonetimi', tab='organizasyon'))
    if not ROLE_KEY_PATTERN.match(role_key):
        flash("Rol key değeri küçük harf, rakam ve alt çizgi ile oluşturulmalıdır.", "danger")
        return redirect(url_for('admin.site_yonetimi', tab='organizasyon'))
    if scope not in {"global", "airport"}:
        flash("Rol kapsamı geçersiz.", "danger")
        return redirect(url_for('admin.site_yonetimi', tab='organizasyon'))
    if get_role_definition(role_key, include_custom=True, allow_legacy=True) or Role.query.filter_by(key=role_key).first():
        flash("Bu rol key zaten kullanımda.", "danger")
        return redirect(url_for('admin.site_yonetimi', tab='organizasyon'))

    role = Role(
        key=role_key,
        label=label,
        scope=scope,
        description=description,
        is_system=False,
        is_active=True,
    )
    db.session.add(role)
    db.session.flush()

    selected_permission_keys = _selected_permission_keys()
    if not selected_permission_keys:
        selected_permission_keys = sorted(get_role_permissions(request.form.get("base_role_key")))

    for permission_key in selected_permission_keys:
        permission = Permission.query.filter_by(key=permission_key).first()
        if permission:
            db.session.add(RolePermission(role_id=role.id, permission_id=permission.id, is_allowed=True))

    db.session.commit()
    log_kaydet("Yetki", f"Özel rol oluşturuldu: {role_key}", event_key="role.create", target_model="Role", target_id=role.id)
    audit_log("role.create", outcome="success", role_key=role_key)
    flash("Özel rol oluşturuldu.", "success")
    return redirect(url_for('admin.role_detail', role_key=role_key))


@admin_bp.route('/admin/roles/<string:role_key>/update', methods=['POST'])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
@permission_required('roles.manage')
def role_update(role_key):
    _require_system_role_manager()
    role = Role.query.filter_by(key=role_key).first_or_404()
    if role.is_system:
        flash("Çekirdek roller bu ekrandan yeniden adlandırılamaz.", "warning")
        return redirect(url_for('admin.role_detail', role_key=role_key))

    label = (request.form.get("label") or "").strip()
    scope = (request.form.get("scope") or role.scope).strip()
    description = (request.form.get("description") or "").strip()
    if not label:
        flash("Rol adı zorunludur.", "danger")
        return redirect(url_for('admin.role_detail', role_key=role_key))
    if scope not in {"global", "airport"}:
        flash("Rol kapsamı geçersiz.", "danger")
        return redirect(url_for('admin.role_detail', role_key=role_key))

    role.label = label
    role.scope = scope
    role.description = description
    db.session.commit()
    log_kaydet("Yetki", f"Özel rol güncellendi: {role_key}", event_key="role.update", target_model="Role", target_id=role.id)
    audit_log("role.update", outcome="success", role_key=role_key)
    flash("Rol detayları güncellendi.", "success")
    return redirect(url_for('admin.role_detail', role_key=role_key))


@admin_bp.route('/admin/roles/<string:role_key>/delete', methods=['POST'])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
@permission_required('roles.manage')
def role_delete(role_key):
    _require_system_role_manager()
    if is_core_role(role_key):
        flash("Çekirdek roller silinemez.", "warning")
        return redirect(url_for('admin.site_yonetimi', tab='organizasyon'))
    role = Role.query.filter_by(key=role_key).first_or_404()
    if role.is_system:
        flash("Çekirdek roller silinemez.", "warning")
        return redirect(url_for('admin.site_yonetimi', tab='organizasyon'))

    active_user_count = Kullanici.query.filter_by(rol=role_key, is_deleted=False).count()
    if active_user_count:
        flash("Bu role bağlı aktif kullanıcılar var. Önce kullanıcıları başka role taşıyın.", "warning")
        return redirect(url_for('admin.role_detail', role_key=role_key))

    role.is_active = False
    db.session.commit()
    log_kaydet("Yetki", f"Özel rol pasife alındı: {role_key}", event_key="role.delete", target_model="Role", target_id=role.id)
    audit_log("role.delete", outcome="success", role_key=role_key)
    flash("Özel rol pasife alındı.", "success")
    return redirect(url_for('admin.site_yonetimi', tab='organizasyon'))
