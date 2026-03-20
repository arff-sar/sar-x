from flask import current_app, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from extensions import db, limiter, log_kaydet
from models import Malzeme, Kullanici, Havalimani
from . import admin_bp
from decorators import permission_required

@admin_bp.route('/arsiv')
@login_required
@permission_required('archive.manage')
def arsiv_listesi():
    # SQLite uyumluluğu için .is_(True) kullanarak verileri zorla çekiyoruz
    silinen_malzemeler = Malzeme.query.filter(Malzeme.is_deleted.is_(True)).all()
    silinen_kullanicilar = Kullanici.query.filter(Kullanici.is_deleted.is_(True)).all()
    silinen_havalimanlari = Havalimani.query.filter(Havalimani.is_deleted.is_(True)).all()
    
    return render_template('admin/archive.html',
                           malzemeler=silinen_malzemeler,
                           kullanicilar=silinen_kullanicilar,
                           havalimanlari=silinen_havalimanlari)


@admin_bp.route('/arsiv_islem', methods=['POST'])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
@permission_required('archive.manage')
def arsiv_islem():
    """
    Arşivdeki öğeyi geri yükler veya kalıcı olarak siler.
    """
    islem_tipi = request.form.get('islem_tipi') # 'geri_yukle' veya 'kalici_sil'
    model_tipi = request.form.get('model_tipi') # 'malzeme', 'kullanici', 'havalimani'
    kayit_id = request.form.get('kayit_id')
    
    model_map = {
        'malzeme': Malzeme,
        'kullanici': Kullanici,
        'havalimani': Havalimani
    }
    
    model = model_map.get(model_tipi)
    if not model or not kayit_id:
        flash("Geçersiz işlem parametreleri.", "danger")
        return redirect(url_for('admin.arsiv_listesi'))
        
    # Kaydı veritabanından bul
    kayit = db.session.get(model, int(kayit_id))
    
    if kayit:
        if islem_tipi == 'geri_yukle':
            # Soft Delete'i geri al
            kayit.is_deleted = False
            kayit.deleted_at = None
            db.session.commit()
            log_kaydet('Arşiv', f'{model_tipi.capitalize()} ({kayit.id}) geri yüklendi.')
            flash(f"Kayıt başarıyla geri yüklendi.", "success")
            
        elif islem_tipi == 'kalici_sil':
            # Veritabanından tamamen temizle
            detay = f"{model_tipi.capitalize()} ({kayit.id}) kalıcı olarak silindi."
            db.session.delete(kayit)
            db.session.commit()
            log_kaydet('Arşiv', detay)
            flash("Kayıt veritabanından kalıcı olarak silindi.", "warning")
    else:
        flash("İşlem yapılacak kayıt bulunamadı.", "danger")
            
    return redirect(url_for('admin.arsiv_listesi'))
