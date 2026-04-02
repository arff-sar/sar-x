from urllib.parse import urlparse, urlunsplit

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from extensions import db, table_exists
from models import Notification
from . import admin_bp


def _safe_notification_redirect_target(raw_target):
    fallback = url_for("admin.notifications")
    target = str(raw_target or "").strip()
    if not target or target.startswith("//"):
        return fallback

    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc:
        request_origin = urlparse(request.host_url)
        if (parsed.scheme or "").lower() != (request_origin.scheme or "").lower():
            return fallback
        if (parsed.hostname or "").lower() != (request_origin.hostname or "").lower():
            return fallback
        try:
            request_port = request_origin.port
            parsed_port = parsed.port
        except ValueError:
            return fallback
        if (request_port or None) != (parsed_port or None):
            return fallback
        safe_path = parsed.path if str(parsed.path or "").startswith("/") else f"/{parsed.path or ''}"
        return urlunsplit(("", "", safe_path or "/", parsed.query, parsed.fragment))

    if not target.startswith("/"):
        return fallback
    return target


@admin_bp.route("/admin/notifications")
@login_required
def notifications():
    if not table_exists("notification"):
        return render_template("admin/notifications.html", notifications=[])
    items = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).limit(200).all()
    return render_template("admin/notifications.html", notifications=items)


@admin_bp.route("/admin/notifications/read/<int:id>", methods=["POST"])
@login_required
def notifications_read(id):
    item = db.session.get(Notification, id)
    if not item or item.user_id != current_user.id:
        abort(403)
    item.is_read = True
    db.session.commit()
    return redirect(_safe_notification_redirect_target(item.link_url))


@admin_bp.route("/admin/notifications/read-all", methods=["POST"])
@login_required
def notifications_read_all():
    if not table_exists("notification"):
        return redirect(url_for("admin.notifications"))
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({"is_read": True})
    db.session.commit()
    flash("Tüm bildirimler okundu olarak işaretlendi.", "success")
    return redirect(url_for("admin.notifications"))
