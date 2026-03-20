import io
import json

from flask import current_app, flash, redirect, render_template, request, send_file, url_for
from flask_login import login_required
from xhtml2pdf import pisa

from decorators import (
    DEFAULT_ROLE_PERMISSIONS,
    get_permission_catalog,
    get_role_permissions,
    get_role_options,
    permission_required,
    sync_authorization_registry,
    update_permission_matrix,
)
from extensions import audit_log, db, limiter, log_kaydet
from models import Kullanici
from . import admin_bp


@admin_bp.route('/admin/roles')
@login_required
@permission_required('roles.manage')
def roles():
    sync_authorization_registry()
    role_options = get_role_options()
    counts = {
        role["key"]: Kullanici.query.filter_by(rol=role["key"], is_deleted=False).count()
        for role in role_options
    }
    return render_template(
        'admin/roles.html',
        role_options=role_options,
        role_counts=counts,
        default_role_permissions=DEFAULT_ROLE_PERMISSIONS,
    )


@admin_bp.route('/admin/roles/<string:role_key>')
@login_required
@permission_required('roles.manage')
def role_detail(role_key):
    role = next((item for item in get_role_options() if item["key"] == role_key), None)
    if not role:
        return redirect(url_for('admin.roles'))
    return render_template(
        'admin/role_form.html',
        role=role,
        permission_catalog=get_permission_catalog(),
        role_permissions=DEFAULT_ROLE_PERMISSIONS.get(role_key, set()),
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
    role_options = get_role_options()
    selected_role = next((item for item in role_options if item["key"] == role_key), role_options[0] if role_options else None)
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
