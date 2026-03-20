from flask import abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from extensions import db, table_exists
from models import Notification
from . import admin_bp


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
    return redirect(item.link_url or url_for("admin.notifications"))


@admin_bp.route("/admin/notifications/read-all", methods=["POST"])
@login_required
def notifications_read_all():
    if not table_exists("notification"):
        return redirect(url_for("admin.notifications"))
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({"is_read": True})
    db.session.commit()
    flash("Tüm bildirimler okundu olarak işaretlendi.", "success")
    return redirect(url_for("admin.notifications"))
