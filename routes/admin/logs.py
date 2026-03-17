from flask import render_template, abort
from flask_login import login_required, current_user
from models import IslemLog
from . import admin_bp

@admin_bp.route('/islem-loglari')
@login_required
def loglari_gor():
    """Sistemdeki tüm işlemleri tarihe göre (indeksli) listeler."""
    # GM sadece izleyebilir, Sahip hem izler hem yönetir.
    if not current_user.can_view_all:
        abort(403)
        
    # ✅ PERFORMANS: Zaman indeksli olduğu için çok hızlı döner
    loglar = IslemLog.query.order_by(IslemLog.zaman.desc()).limit(500).all()
    
    return render_template('admin/islem_loglari.html', loglar=loglar)