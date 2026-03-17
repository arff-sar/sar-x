from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, abort
from flask_login import login_required, current_user
# ✅ GÜVENLİK: guvenli_metin import edildi
from extensions import db, log_kaydet, guvenli_metin
from datetime import datetime, timedelta
from models import Malzeme, Kutu, TR_TZ, get_tr_now
from qr_logic import generate_qr_data
import pandas as pd
from xhtml2pdf import pisa
import io

inventory_bp = Blueprint('inventory', __name__)

# --- YARDIMCI YETKİ FONKSİYONU ---
def havalimani_filtreli_sorgu(model_sinifi):
    """
    SAHİP ve GENEL_MUDURLUK her şeyi görebilir.
    YETKİLİ ve PERSONEL sadece kendi havalimanını görür.
    Her zaman silinmemiş kayıtları döndürür.
    """
    if current_user.rol in ['sahip', 'genel_mudurluk']:
        return model_sinifi.query.filter_by(is_deleted=False)
    return model_sinifi.query.filter_by(havalimani_id=current_user.havalimani_id, is_deleted=False)


# --- ROTALAR ---

@inventory_bp.route('/dashboard')
@login_required
def dashboard():
    if current_user.rol in ['sahip', 'genel_mudurluk']:
        h_ad = "Genel Müdürlük / Tüm Birimler"
    else:
        h_ad = current_user.havalimani.ad

    bugun = datetime.now(TR_TZ).date()
    on_bes_gun_sonra = bugun + timedelta(days=15)

    bakim_sorgu = havalimani_filtreli_sorgu(Malzeme).filter(
        Malzeme.gelecek_bakim_tarihi <= on_bes_gun_sonra,
        Malzeme.durum != 'Hurda'
    )
    ariza_sorgu = havalimani_filtreli_sorgu(Malzeme).filter_by(durum='Arızalı')

    return render_template('dashboard.html', 
                           havalimani_ad=h_ad, 
                           bakim_uyarilari=bakim_sorgu.all(), 
                           arizali_malzemeler=ariza_sorgu.all(), 
                           bugun=bugun)

@inventory_bp.route('/envanter')
@login_required
def envanter():
    malzemeler = havalimani_filtreli_sorgu(Malzeme).all()
    
    if current_user.rol in ['sahip', 'genel_mudurluk']:
        h_ad = "Genel Envanter (Tüm Birimler)"
    else:
        h_ad = current_user.havalimani.ad
    
    return render_template('envanter.html', malzemeler=malzemeler, havalimani_ad=h_ad)

@inventory_bp.route('/malzeme-ekle', methods=['GET', 'POST'])
@login_required
def malzeme_ekle():
    if current_user.rol not in ['sahip', 'yetkili']:
        abort(403)

    if request.method == 'POST':
        k_kodu = request.form.get('kutu_kodu').upper().strip()
        
        if current_user.rol == 'sahip':
            h_id = request.form.get('havalimani_id') or 1
        else:
            h_id = current_user.havalimani_id
        
        kutu = Kutu.query.filter_by(kodu=k_kodu, havalimani_id=h_id, is_deleted=False).first()
        if not kutu:
            kutu = Kutu(kodu=k_kodu, havalimani_id=h_id)
            db.session.add(kutu)
            db.session.commit()

        # ✅ GÜVENLİK: Teknik özellikler Bleach ile temizlendi
        guvenli_teknik = guvenli_metin(request.form.get('teknik'))

        yeni = Malzeme(
            ad=request.form.get('ad'), 
            seri_no=request.form.get('seri_no'), 
            teknik_ozellikler=guvenli_teknik, 
            stok_miktari=request.form.get('stok', 1), 
            durum=request.form.get('durum', 'Aktif'), 
            kritik_mi=True if request.form.get('kritik') == 'on' else False, 
            son_bakim_tarihi=datetime.strptime(request.form.get('bakim'), '%Y-%m-%d').date() if request.form.get('bakim') else None, 
            gelecek_bakim_tarihi=datetime.strptime(request.form.get('gelecek_bakim'), '%Y-%m-%d').date() if request.form.get('gelecek_bakim') else None, 
            kutu_id=kutu.id, 
            havalimani_id=h_id
        )
        db.session.add(yeni)
        db.session.commit()
        log_kaydet('Envanter', f'Yeni malzeme eklendi: {yeni.ad} ({yeni.havalimani.kodu})')
        flash('Malzeme başarıyla eklendi.', 'success')
        return redirect(url_for('inventory.envanter'))
    
    return render_template('malzeme_ekle.html')

@inventory_bp.route('/bakim-kaydet/<int:id>', methods=['POST'])
@login_required
def bakim_kaydet(id):
    if current_user.rol == 'genel_mudurluk':
        abort(403)

    from models import BakimKaydi
    malzeme = Malzeme.query.filter_by(id=id, is_deleted=False).first_or_404()

    if current_user.rol != 'sahip' and malzeme.havalimani_id != current_user.havalimani_id:
        flash("Farklı bir birimin malzemesine bakım girişi yapamazsınız!", "danger")
        abort(403)

    # ✅ GÜVENLİK: İşlem notu Bleach ile temizlendi
    guvenli_not = guvenli_metin(request.form.get('not'))

    yeni_kayit = BakimKaydi(
        malzeme_id=id, 
        yapan_personel_id=current_user.id, 
        islem_notu=guvenli_not, 
        maliyet=float(request.form.get('maliyet', 0))
    )
    
    malzeme.son_bakim_tarihi = get_tr_now().date()
    yeni_gelecek = request.form.get('gelecek_bakim')
    if yeni_gelecek:
        malzeme.gelecek_bakim_tarihi = datetime.strptime(yeni_gelecek, '%Y-%m-%d').date()

    db.session.add(yeni_kayit)
    db.session.commit()
    
    log_kaydet('Bakım', f'{malzeme.ad} için bakım kaydı girildi ({malzeme.havalimani.kodu})')
    flash('Bakım kaydı başarıyla işlendi.', 'success')
    return redirect(url_for('inventory.envanter'))

@inventory_bp.route('/envanter/excel')
@login_required
def envanter_excel():
    if current_user.rol == 'personel':
        abort(403)

    malzemeler = havalimani_filtreli_sorgu(Malzeme).all()
    data = [{
        "Birim": m.havalimani.kodu,
        "Kutu": m.kutu.kodu,
        "Malzeme Adı": m.ad, 
        "Seri No": m.seri_no, 
        "Durum": m.durum, 
        "Son Bakım": m.son_bakim_tarihi.strftime('%d.%m.%Y') if m.son_bakim_tarihi else "-",
        "Gelecek Bakım": m.gelecek_bakim_tarihi.strftime('%d.%m.%Y') if m.gelecek_bakim_tarihi else "-"
    } for m in malzemeler]
    
    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    output.seek(0)
    
    log_kaydet('Rapor', f'Envanter Excel raporu oluşturuldu ({current_user.rol})')
    return send_file(output, download_name=f"SAR_Envanter_{datetime.now(TR_TZ).strftime('%Y%m%d')}.xlsx", as_attachment=True)

@inventory_bp.route('/envanter/pdf')
@login_required
def envanter_pdf():
    if current_user.rol == 'personel':
        abort(403)

    malzemeler = havalimani_filtreli_sorgu(Malzeme).all()
    html = render_template('pdf_sablonu.html', malzemeler=malzemeler, tarih=datetime.now(TR_TZ))
    output = io.BytesIO()
    pisa.CreatePDF(html, dest=output)
    output.seek(0)
    
    log_kaydet('Rapor', f'Envanter PDF raporu oluşturuldu ({current_user.rol})')
    return send_file(output, download_name=f"SAR_Rapor_{datetime.now(TR_TZ).strftime('%Y%m%d')}.pdf", as_attachment=True)

@inventory_bp.route('/kutu/<string:kodu>')
@login_required
def kutu_detay(kodu):
    if current_user.havalimani_id:
        kutu = Kutu.query.filter_by(kodu=kodu, havalimani_id=current_user.havalimani_id, is_deleted=False).first()
    else:
        kutu = Kutu.query.filter_by(kodu=kodu, is_deleted=False).first()
        
    if not kutu:
        flash('Biriminizde böyle bir kutu bulunamadı veya yetkiniz yok.', 'danger')
        return redirect(url_for('inventory.dashboard'))
        
    return render_template('kutu_detay.html', kutu=kutu)


# --- YENİ EKLENEN B PLANI VE YAZDIRMA ROTALARI ---

@inventory_bp.route('/kutu-bul', methods=['POST'])
@login_required
def kutu_bul():
    """Kamera bozulduğunda personelin Dashboard üzerinden manuel olarak kutuyu bulması"""
    kodu = request.form.get('kutu_kodu', '').strip().upper()
    
    if kodu:
        if current_user.havalimani_id:
            kutu = Kutu.query.filter_by(kodu=kodu, havalimani_id=current_user.havalimani_id, is_deleted=False).first()
        else:
            kutu = Kutu.query.filter_by(kodu=kodu, is_deleted=False).first()
            
        if kutu:
            return redirect(url_for('inventory.kutu_detay', kodu=kutu.kodu))
        else:
            flash(f"⚠️ '{kodu}' koduna ait bir ünite bulunamadı veya erişim yetkiniz yok.", "danger")
            
    return redirect(url_for('inventory.dashboard'))

@inventory_bp.route('/qr-uret/<string:kodu>')
@login_required
def qr_uret(kodu):
    """Envanter tablosundan tıklanıldığında doğrudan yazdırma sayfasını (qr_yazdir.html) açar"""
    if current_user.havalimani_id:
        kutu = Kutu.query.filter_by(kodu=kodu, havalimani_id=current_user.havalimani_id, is_deleted=False).first_or_404()
    else:
        kutu = Kutu.query.filter_by(kodu=kodu, is_deleted=False).first_or_404()
        
    return render_template('qr_yazdir.html', kutu=kutu)

@inventory_bp.route('/api/qr-img/<string:kodu>')
@login_required
def qr_img(kodu):
    """Yazdırma sayfası içindeki <img> etiketine resmi çizen rota"""
    target_url = url_for('inventory.kutu_detay', kodu=kodu, _external=True)
    img_io = generate_qr_data(target_url) # Senin özel qr_logic kütüphaneni kullanır
    return send_file(img_io, mimetype='image/png') if img_io else ("QR Hatası", 500)