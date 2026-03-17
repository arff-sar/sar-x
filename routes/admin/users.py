from flask import render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from extensions import db, log_kaydet, guvenli_metin
from models import Kullanici, Havalimani
from . import admin_bp

@admin_bp.route('/kullanicilar')
@login_required
def kullanicilar():
    """Kullanıcıları listeler (Sadece silinmemiş olanlar)."""
    if not current_user.is_sahip:
        flash("Bu sayfaya sadece sistem sahibi erişebilir.", "danger")
        return redirect(url_for('inventory.dashboard'))
    
    # ✅ SOFT DELETE: Sadece is_deleted=False olanları getiriyoruz
    liste = Kullanici.query.filter_by(is_deleted=False).all()
    havalimanlari = Havalimani.query.filter_by(is_deleted=False).all()
    
    return render_template('admin/kullanicilar.html', 
                           kullanicilar=liste, 
                           havalimanlari=havalimanlari)

@admin_bp.route('/kullanici-ekle', methods=['POST'])
@login_required
def kullanici_ekle():
    """Yeni kullanıcı ekler."""
    if not current_user.is_sahip:
        abort(403)
        
    # ✅ GÜVENLİK: Inputları temizliyoruz
    tam_ad = guvenli_metin(request.form.get('tam_ad'))
    k_adi = guvenli_metin(request.form.get('k_adi'))
    rol = request.form.get('rol')
    h_id = request.form.get('h_id')
    sifre = request.form.get('sifre')
    
    # Global Roller (Sahip & GM) bir limana bağlanamaz
    if rol in ['sahip', 'genel_mudurluk']:
        h_id = None
    elif rol in ['yetkili', 'personel'] and not h_id:
        flash("Saha personeli için birim seçimi zorunludur!", "danger")
        return redirect(url_for('admin.kullanicilar'))

    # Kullanıcı adı kontrolü
    mevcut = Kullanici.query.filter_by(kullanici_adi=k_adi).first()
    if mevcut:
        flash("Bu e-posta/kullanıcı adı zaten kullanımda!", "warning")
        return redirect(url_for('admin.kullanicilar'))

    yeni = Kullanici(
        tam_ad=tam_ad, 
        kullanici_adi=k_adi, 
        rol=rol, 
        havalimani_id=h_id
    )
    yeni.sifre_set(sifre)
    db.session.add(yeni)
    db.session.commit()
    
    log_kaydet('Güvenlik', f'Yeni kullanıcı ({rol}) eklendi: {k_adi}')
    flash(f"{tam_ad} personeli sisteme eklendi.", "success")
    return redirect(url_for('admin.kullanicilar'))

@admin_bp.route('/kullanici-sil/<int:id>')
@login_required
def kullanici_sil(id):
    """Kullanıcıyı soft-delete ile arşivler."""
    if not current_user.is_sahip:
        abort(403)
        
    user = db.session.get(Kullanici, id)
    
    if not user or user.is_deleted:
        flash("Kullanıcı bulunamadı!", "danger")
    elif user.kullanici_adi == 'mehmetcinocevi@gmail.com':
        flash("Ana yönetici hesabı silinemez!", "danger")
    else:
        k_adi = user.kullanici_adi
        
        # ✅ SOFT DELETE: db.session.delete yerine kendi metodumuzu çağırıyoruz
        user.soft_delete()
        
        log_kaydet('Güvenlik', f'Kullanıcı silindi (Arşivlendi): {k_adi}')
        flash(f"{k_adi} kullanıcısı sistemden kaldırıldı.", "info")
        
    return redirect(url_for('admin.kullanicilar'))