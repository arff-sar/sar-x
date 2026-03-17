from extensions import db
from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import pytz

# --- ZAMAN AYARLARI ---
TR_TZ = pytz.timezone('Europe/Istanbul')

def get_tr_now():
    """İstanbul yerel saatini döner."""
    return datetime.now(TR_TZ)

# --- MİXİNLER (YENİLENMİŞ) ---

class TimestampMixin:
    """Tüm tablolara otomatik yerel tarih ekler."""
    created_at = db.Column(db.DateTime, default=get_tr_now)
    updated_at = db.Column(db.DateTime, default=get_tr_now, onupdate=get_tr_now)

class SoftDeleteMixin:
    """✅ YENİ: Verilerin fiziksel olarak silinmesini engeller, arşivler."""
    is_deleted = db.Column(db.Boolean, default=False, index=True) # Hızlı filtreleme için indekslendi
    deleted_at = db.Column(db.DateTime, nullable=True)

    def soft_delete(self):
        self.is_deleted = True
        self.deleted_at = get_tr_now()
        db.session.commit()

# --- ANA MODELLER ---

class Havalimani(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = 'havalimani'
    id = db.Column(db.Integer, primary_key=True)
    ad = db.Column(db.String(100), nullable=False)
    kodu = db.Column(db.String(10), nullable=False, unique=True)
    
    personeller = db.relationship('Kullanici', backref='havalimani', lazy=True)
    kutular = db.relationship('Kutu', backref='havalimani', lazy=True)
    malzemeler = db.relationship('Malzeme', backref='havalimani', lazy=True)

class Kullanici(db.Model, UserMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = 'kullanici'
    id = db.Column(db.Integer, primary_key=True)
    kullanici_adi = db.Column(db.String(50), unique=True, nullable=False)
    sifre_hash = db.Column(db.String(256))
    tam_ad = db.Column(db.String(100), nullable=False)
    
    # ✅ PERFORMANS: Rol ve Havalimanı ID indekslendi
    rol = db.Column(db.String(20), nullable=False, default='personel', index=True) 
    havalimani_id = db.Column(db.Integer, db.ForeignKey('havalimani.id'), nullable=True, index=True)
    
    sertifika_tarihi = db.Column(db.Date)
    uzmanlik_alani = db.Column(db.String(100))
    kayit_tarihi = db.Column(db.DateTime, default=get_tr_now)

    @property
    def is_sahip(self):
        return self.rol == 'sahip'

    @property
    def is_genel_mudurluk(self):
        return self.rol == 'genel_mudurluk'

    @property
    def can_edit(self):
        return self.rol in ['sahip', 'yetkili']

    @property
    def can_view_all(self):
        return self.rol in ['sahip', 'genel_mudurluk']

    def sifre_set(self, sifre):
        self.sifre_hash = generate_password_hash(sifre, method='pbkdf2:sha256')

    def sifre_kontrol(self, sifre):
        return check_password_hash(self.sifre_hash, sifre)

class Kutu(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = 'kutu'
    id = db.Column(db.Integer, primary_key=True)
    kodu = db.Column(db.String(50), unique=True, nullable=False)
    konum = db.Column(db.String(100)) 
    havalimani_id = db.Column(db.Integer, db.ForeignKey('havalimani.id'), nullable=False, index=True)
    
    malzemeler = db.relationship('Malzeme', backref='kutu', lazy=True)

class Malzeme(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = 'malzeme'
    id = db.Column(db.Integer, primary_key=True)
    ad = db.Column(db.String(100), nullable=False)
    seri_no = db.Column(db.String(100), unique=True)
    teknik_ozellikler = db.Column(db.Text)
    stok_miktari = db.Column(db.Integer, default=1)
    
    # ✅ PERFORMANS: Durum ve Bakım tarihi raporlar için indekslendi
    durum = db.Column(db.String(20), default='Aktif', index=True) 
    kritik_mi = db.Column(db.Boolean, default=False)
    
    son_bakim_tarihi = db.Column(db.Date)
    gelecek_bakim_tarihi = db.Column(db.Date, index=True)
    kalibrasyon_tarihi = db.Column(db.Date)
    
    kutu_id = db.Column(db.Integer, db.ForeignKey('kutu.id'), nullable=False, index=True)
    havalimani_id = db.Column(db.Integer, db.ForeignKey('havalimani.id'), nullable=False, index=True)
    
    bakim_kayitlari = db.relationship('BakimKaydi', backref='malzeme', lazy=True, cascade="all, delete-orphan")

class BakimKaydi(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = 'bakim_kaydi'
    id = db.Column(db.Integer, primary_key=True)
    malzeme_id = db.Column(db.Integer, db.ForeignKey('malzeme.id'), nullable=False, index=True)
    yapan_personel_id = db.Column(db.Integer, db.ForeignKey('kullanici.id'))
    islem_notu = db.Column(db.Text, nullable=False)
    maliyet = db.Column(db.Float, default=0.0)

class IslemLog(db.Model):
    __tablename__ = 'islem_log'
    id = db.Column(db.Integer, primary_key=True)
    kullanici_id = db.Column(db.Integer, db.ForeignKey('kullanici.id'), nullable=True, index=True)
    islem_tipi = db.Column(db.String(50), nullable=False)
    detay = db.Column(db.Text)
    ip_adresi = db.Column(db.String(45)) 
    user_agent = db.Column(db.String(200))
    zaman = db.Column(db.DateTime, default=get_tr_now, index=True)

    yapan_kullanici = db.relationship('Kullanici', backref='loglar')

# --- CMS MODELLERİ ---

class SiteAyarlari(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    baslik = db.Column(db.String(200))
    alt_metin = db.Column(db.Text)
    iletisim_notu = db.Column(db.Text)

class Haber(db.Model, TimestampMixin):
    id = db.Column(db.Integer, primary_key=True)
    baslik = db.Column(db.String(200), nullable=False)
    icerik = db.Column(db.Text, nullable=False)
    tarih = db.Column(db.DateTime, default=get_tr_now, index=True)

class NavMenu(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ad = db.Column(db.String(50), nullable=False)
    link = db.Column(db.String(200), default="#")
    sira = db.Column(db.Integer, default=0)

class SliderResim(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    resim_url = db.Column(db.String(500), nullable=False)
    baslik = db.Column(db.String(200))
    alt_yazi = db.Column(db.Text)