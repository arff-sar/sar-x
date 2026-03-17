import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from google.cloud import secretmanager

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature

# ✅ MODELLER: Kullanici modelindeki sifre_set metodunu kullanacağız
from models import Kullanici
from extensions import db, log_kaydet, limiter 

auth_bp = Blueprint('auth', __name__)

# --- YARDIMCI FONKSİYONLAR ---

def gizli_sifreyi_getir():
    try:
        client = secretmanager.SecretManagerServiceClient()
        ad = "projects/kitapligim-490107/secrets/MAIL_SIFRE/versions/latest"
        cevap = client.access_secret_version(request={"name": ad})
        return cevap.payload.data.decode("UTF-8")
    except Exception as e:
        print(f"Kasa açma hatası: {e}")
        return None

def mail_gonder(alici_mail, konu, icerik):
    gonderici_mail = "mehmetcinocevi@gmail.com" 
    sifre = gizli_sifreyi_getir() 
    
    if not sifre:
        return False

    msg = MIMEMultipart()
    msg['From'] = f"SAR-X Sistem <{gonderici_mail}>"
    msg['To'] = alici_mail
    msg['Subject'] = konu
    msg.add_header('reply-to', 'no-reply@erzurumetkinlik.com.tr')

    msg.attach(MIMEText(icerik, 'html', 'utf-8'))

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(gonderici_mail, sifre)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"Mail Hatası: {e}")
        return False


# --- ROTALAR ---

@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("5/minute")
def login():
    if current_user.is_authenticated: 
        return redirect(url_for('inventory.dashboard'))
        
    if request.method == 'POST':
        kullanici_adi = request.form.get('kullanici_adi')
        sifre = request.form.get('sifre')
        
        user = Kullanici.query.filter_by(kullanici_adi=kullanici_adi, is_deleted=False).first()
        
        if user and user.sifre_kontrol(sifre):
            login_user(user)
            log_kaydet('Giriş', f'{user.kullanici_adi} sisteme giriş yaptı.')
            return redirect(url_for('inventory.dashboard'))
            
        flash("Şifre veya Kullanıcı Adı yanlış.", "danger")
        
    return render_template('login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    log_kaydet('Çıkış', f'{current_user.kullanici_adi} sistemden güvenli çıkış yaptı.')
    logout_user()
    # ✅ TEST FIX: Testlerin beklediği mesajla tam uyum sağlandı
    flash("Sistemden güvenli çıkış yapıldı.", "info") 
    return redirect(url_for('auth.login'))


@auth_bp.route('/sifre-sifirla-talep', methods=['POST'])
@limiter.limit("3/minute")
def sifre_sifirla_talep():
    k_ad = request.form.get('kullanici_adi')
    
    if not k_ad:
        flash("Lütfen geçerli bir e-posta (kullanıcı adı) girin.", "danger")
        return redirect(url_for('auth.login'))
        
    user = Kullanici.query.filter_by(kullanici_adi=k_ad, is_deleted=False).first()
    
    if user:
        serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
        token = serializer.dumps(k_ad, salt='sifre-sifirlama-tuzu')
        
        reset_link = url_for('auth.sifre_yenile', token=token, _external=True)
        
        log_kaydet('Şifre Sıfırlama', f'{k_ad} için şifre sıfırlama bağlantısı gönderildi.')
        
        kullanici_ismi = getattr(user, 'tam_ad', 'Personel')
        konu = "SAR-X Şifre Sıfırlama Bağlantısı"
        
        # ✅ KLASÖR DÜZELTMESİ: templates/email/ altındaki dosyayı çağırıyoruz
        icerik = render_template('email/sifre_sifirla.html', 
                                 kullanici_ismi=kullanici_ismi, 
                                 reset_link=reset_link)
        
        mail_sonuc = mail_gonder(k_ad, konu, icerik)
        
        if mail_sonuc:
            flash("Şifre sıfırlama bağlantısı e-posta adresinize gönderildi.", "success")
        else:
            flash("Mail gönderilemedi. Lütfen yöneticinizle iletişime geçin.", "danger")
    else:
        # Güvenlik gereği kullanıcı yoksa da "gönderildi" mesajı verilir (User Enumeration Koruması)
        flash("Şifre sıfırlama bağlantısı e-posta adresinize gönderildi.", "success")
    
    return redirect(url_for('auth.login'))


@auth_bp.route('/sifre-yenile/<token>', methods=['GET', 'POST'])
def sifre_yenile(token):
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    
    try:
        email = serializer.loads(token, salt='sifre-sifirlama-tuzu', max_age=3600)
    except SignatureExpired:
        flash("Şifre sıfırlama bağlantısının süresi dolmuş. Lütfen yeni bir talep oluşturun.", "danger")
        return redirect(url_for('auth.login'))
    except BadSignature:
        flash("Geçersiz veya bozuk bir şifre sıfırlama bağlantısı.", "danger")
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        yeni_sifre = request.form.get('yeni_sifre')
        
        if not yeni_sifre or len(yeni_sifre) < 6:
            flash("Şifre en az 6 karakter olmalıdır.", "warning")
            return render_template('sifre_yenile.html', token=token, email=email)

        user = Kullanici.query.filter_by(kullanici_adi=email, is_deleted=False).first()
        
        if user:
            # ✅ MODEL UYUMU: sifre_set() metodu modellerdeki pbkdf2:sha256 ayarını otomatik kullanır.
            # Böylece scrypt hatasından kurtuluruz.
            user.sifre_set(yeni_sifre)
            
            try:
                db.session.commit()
                log_kaydet('Şifre Yenileme', f'{email} şifresini başarıyla yeniledi.')
                flash("Şifreniz başarıyla güncellendi! Giriş yapabilirsiniz.", "success")
                return redirect(url_for('auth.login'))
            except Exception as e:
                db.session.rollback()
                flash("Veritabanı hatası oluştu.", "danger")
        else:
            flash("Kullanıcı bulunamadı.", "danger")
            return redirect(url_for('auth.login'))
            
    return render_template('sifre_yenile.html', token=token, email=email)