import io

import pandas as pd
from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required
from xhtml2pdf import pisa

from decorators import CANONICAL_ROLE_ADMIN, CANONICAL_ROLE_SYSTEM, CANONICAL_ROLE_TEAM_LEAD, get_effective_role, permission_required
from extensions import audit_log, limiter, log_kaydet
from reporting import (
    build_dashboard_kpis,
    build_operational_snapshot,
    build_report_dataset,
    filter_options,
    manager_summary,
    parse_report_filters,
    report_tabs,
)


reports_bp = Blueprint("reports", __name__)


@reports_bp.route("/reports")
@login_required
@permission_required("reports.view")
def index():
    filters = parse_report_filters(request.args)
    report_key = (request.args.get("report") or "inventory").strip()
    if report_key not in {tab["key"] for tab in report_tabs()}:
        report_key = "inventory"

    snapshot = build_operational_snapshot(current_user, filters)
    dashboard_kpis = build_dashboard_kpis(current_user, filters)
    report_data = build_report_dataset(current_user, report_key, filters)

    log_kaydet("Rapor", f"Rapor görüntülendi: {report_key}", event_key="reports.view", target_model=report_key)
    audit_log("reports.view", outcome="success", report_key=report_key)

    return render_template(
        "reports/index.html",
        report_key=report_key,
        tabs=report_tabs(),
        filters=filters,
        export_query=_query_passthrough(filters),
        filter_options=filter_options(current_user),
        snapshot=snapshot,
        dashboard_kpis=dashboard_kpis["kpis"],
        report_data=report_data,
    )


@reports_bp.route("/reports/manager-summary")
@login_required
@permission_required("reports.view")
def manager_summary_view():
    if get_effective_role(current_user) not in {CANONICAL_ROLE_SYSTEM, CANONICAL_ROLE_ADMIN, CANONICAL_ROLE_TEAM_LEAD}:
        abort(403)

    filters = parse_report_filters(request.args)
    summary = manager_summary(current_user, filters)

    log_kaydet("Rapor", "Yönetici özeti görüntülendi.", event_key="reports.manager_summary.view", target_model="manager_summary")
    audit_log("reports.manager_summary.view", outcome="success", role=get_effective_role(current_user))
    return render_template(
        "reports/manager_summary.html",
        filters=filters,
        filter_options=filter_options(current_user),
        summary=summary,
    )


@reports_bp.route("/reports/export/<string:report_key>/<string:fmt>")
@login_required
@permission_required("inventory.export")
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
def export(report_key, fmt):
    filters = parse_report_filters(request.args)
    if report_key not in {tab["key"] for tab in report_tabs()}:
        flash("Geçersiz rapor anahtarı.", "danger")
        return redirect(url_for("reports.index"))

    log_kaydet("Rapor", f"Export başlatıldı: {report_key}/{fmt}", event_key="reports.export.start", target_model=report_key)
    audit_log("reports.export.start", outcome="success", report_key=report_key, format=fmt)

    report_data = build_report_dataset(current_user, report_key, filters)
    rows = report_data["rows"]
    limit = int(current_app.config.get("MAX_EXPORT_ROWS", 10000))
    if len(rows) > limit:
        log_kaydet("Rapor", f"Export limiti aşıldı: {report_key}/{fmt} ({len(rows)} satır)", event_key="reports.export.failed", target_model=report_key, outcome="failed")
        audit_log("reports.export.failed", outcome="failed", report_key=report_key, format=fmt, rows=len(rows))
        flash(f"Bu rapor {limit} satır limitini aşıyor. Filtreleri daraltıp tekrar deneyin.", "danger")
        return redirect(url_for("reports.index", report=report_key, **_query_passthrough(filters)))

    frame = pd.DataFrame(rows)
    filename = f"{report_key}_report"

    try:
        if fmt == "csv":
            output = io.StringIO()
            frame.to_csv(output, index=False)
            payload = io.BytesIO(output.getvalue().encode("utf-8-sig"))
            payload.seek(0)
            response = send_file(payload, as_attachment=True, download_name=f"{filename}.csv", mimetype="text/csv")
        elif fmt == "xlsx":
            payload = io.BytesIO()
            with pd.ExcelWriter(payload, engine="openpyxl") as writer:
                frame.to_excel(writer, index=False)
            payload.seek(0)
            response = send_file(
                payload,
                as_attachment=True,
                download_name=f"{filename}.xlsx",
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        elif fmt == "pdf":
            html = render_template("reports/export_pdf.html", report_data=report_data, filters=filters)
            payload = io.BytesIO()
            pisa.CreatePDF(html, dest=payload)
            payload.seek(0)
            response = send_file(payload, as_attachment=True, download_name=f"{filename}.pdf", mimetype="application/pdf")
        else:
            flash("Desteklenmeyen export formatı.", "danger")
            return redirect(url_for("reports.index", report=report_key, **_query_passthrough(filters)))

        log_kaydet("Rapor", f"Export tamamlandı: {report_key}/{fmt}", event_key="reports.export.completed", target_model=report_key)
        audit_log("reports.export.completed", outcome="success", report_key=report_key, format=fmt, rows=len(rows))
        return response
    except Exception:
        log_kaydet("Rapor", f"Export başarısız: {report_key}/{fmt}", event_key="reports.export.failed", target_model=report_key, outcome="failed")
        audit_log("reports.export.failed", outcome="failed", report_key=report_key, format=fmt)
        flash("Export oluşturulurken bir hata oluştu.", "danger")
        return redirect(url_for("reports.index", report=report_key, **_query_passthrough(filters)))


def _query_passthrough(filters):
    payload = {}
    for key, value in filters.items():
        if value in [None, "", "all"]:
            continue
        payload[key] = value.strftime("%Y-%m-%d") if hasattr(value, "strftime") else value
    return payload
