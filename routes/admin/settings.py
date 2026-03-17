from flask import render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from extensions import db, log_kaydet, guvenli_metin
from models import Havalimani, Haber, NavMenu, SliderResim, SiteAyarlari
from . import admin_bp

# --- HAVALİMANI YÖNETİMİ ---

@admin_bp.route('/havalimanlari', methods=['GET', 'POST'])
@login_required
def havalimanlari():
    """Birimleri (Havalimanlarını) yönetir."""
    if not current_user.is_sahip:
        abort(403)
        
    if request.method == 'POST':
        islem = request.form.get('islem')
        
        # ✅ GÜVENLİK: Input temizleme
        ad = guvenli_metin(request.form.get('ad'))
        kodu = guvenli_metin(request.form.get('kodu')).upper()

        if islem == 'ekle':
            # ✅ SOFT DELETE: Sadece aktif olanlar içinde mükerrer kontrolü
            if Havalimani.query.filter_by(kodu=kodu, is_deleted=False).first():
                flash(f'Hata: {kodu} kodlu bir birim zaten mevcut!', 'danger')
            else:
                yeni_h = Havalimani(ad=ad, kodu=kodu)
                db.session.add(yeni_h)
                db.session.commit()
                log_kaydet('Sistem', f'Yeni birim eklendi: {kodu}')
                flash('Yeni birim başarıyla tanımlandı.', 'success')
                
        elif islem == 'guncelle':
            h_id = request.form.get('id')
            h = db.session.get(Havalimani, h_id)
            if h and not h.is_deleted:
                eski_ad = h.ad
                h.ad = ad
                h.kodu = kodu
                db.session.commit()
                log_kaydet('Sistem', f'Birim güncellendi: {eski_ad} -> {h.ad}')
                flash('Birim bilgileri güncellendi.', 'success')
        
        return redirect(url_for('admin.havalimanlari'))

    # ✅ SOFT DELETE: Sadece silinmemiş birimleri listele
    liste = Havalimani.query.filter_by(is_deleted=False).all()
    return render_template('admin/havalimanlari.html', havalimanlari=liste)

@admin_bp.route('/havalimani-sil/<int:id>')
@login_required
def havalimani_sil(id):
    """Birimi fiziksel olarak silmez, arşivler (Soft Delete)."""
    if not current_user.is_sahip:
        abort(403)
        
    h = db.session.get(Havalimani, id)
    if h and not h.is_deleted:
        kod = h.kodu
        # ✅ SOFT DELETE: db.session.delete yerine kullanıyoruz
        h.soft_delete()
        log_kaydet('Sistem', f'Birim arşivlendi: {kod}')
        flash(f"{kod} birimi ve bağlı kayıtlar arşivlendi.", "info")
    else:
        flash("Birim bulunamadı.", "danger")
        
    return redirect(url_for('admin.havalimanlari'))

# --- SİTE YÖNETİMİ VE CMS ---

@admin_bp.route('/site-yonetimi')
@login_required
def site_yonetimi():
    """Genel site ayarları, slider ve menü yönetimi."""
    if not current_user.is_sahip:
        abort(403)
    return render_template('admin/site_yonetimi.html', 
                           menuler=NavMenu.query.all(), 
                           sliderlar=SliderResim.query.all(), 
                           ayarlar=SiteAyarlari.query.first())

@admin_bp.route('/haber-ekle', methods=['POST'])
@login_required
def haber_ekle():
    """Site ana sayfasına haber ekler."""
    if not current_user.can_edit:
        abort(403)
        
    baslik = guvenli_metin(request.form.get('haber_baslik'))
    icerik = guvenli_metin(request.form.get('haber_icerik'))
    
    yeni_haber = Haber(baslik=baslik, icerik=icerik)
    db.session.add(yeni_haber)
    db.session.commit()
    
    log_kaydet("İçerik", f"Yeni haber: {baslik}")
    flash("Haber başarıyla yayınlandı.", "success")
    return redirect(url_for('inventory.dashboard' if current_user.rol == 'yetkili' else 'admin.site_yonetimi'))

@admin_bp.route('/site-ayarlarini-guncelle', methods=['POST'])
@login_required
def site_ayarlarini_guncelle():
    """Global site başlık ve alt metinlerini günceller."""
    if not current_user.is_sahip: abort(403)
    
    ayarlar = SiteAyarlari.query.first() or SiteAyarlari()
    if not ayarlar.id: db.session.add(ayarlar)
    
    ayarlar.baslik = guvenli_metin(request.form.get('baslik'))
    ayarlar.alt_metin = guvenli_metin(request.form.get('alt_metin'))
    
    db.session.commit()
    log_kaydet("Sistem", "Site ayarları güncellendi.")
    flash("Site ayarları güncellendi.", "success")
    return redirect(url_for('admin.site_yonetimi'))

# --- SLIDER VE MENÜ (CMS ALT BİLEŞENLERİ) ---

@admin_bp.route('/slider-ekle', methods=['POST'])
@login_required
def slider_ekle():
    if not current_user.is_sahip: abort(403)
    yeni = SliderResim(
        resim_url=guvenli_metin(request.form.get('resim_url')), 
        baslik=guvenli_metin(request.form.get('slider_baslik'))
    )
    db.session.add(yeni)
    db.session.commit()
    flash("Slider eklendi.", "success")
    return redirect(url_for('admin.site_yonetimi'))

@admin_bp.route('/menu-ekle', methods=['POST'])
@login_required
def menu_ekle():
    if not current_user.is_sahip: abort(403)
    yeni = NavMenu(
        ad=guvenli_metin(request.form.get('menu_ad')), 
        link=guvenli_metin(request.form.get('menu_link'))
    )
    db.session.add(yeni)
    db.session.commit()
    flash("Menü eklendi.", "success")
    return redirect(url_for('admin.site_yonetimi'))

# Slider/Menu silme işlemleri CMS olduğu için genelde hard-delete kalabilir 
# ancak istersen onları da soft-delete yapabiliriz.