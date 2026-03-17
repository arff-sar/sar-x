from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, current_user
from flask import request, jsonify

# --- GÜVENLİK VE YARDIMCI KÜTÜPHANELER ---
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import bleach
from flask_executor import Executor
from flask_migrate import Migrate  # ✅ YENİ: Veri kaybını önleyen göç sistemi

# --- BİLEŞENLERİ BAŞLATMA ---
db = SQLAlchemy()

login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = "Lütfen önce sisteme giriş yapın."
login_manager.login_message_category = "danger"

# Güvenlik, Göç ve Arka Plan Bileşenleri
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address)
executor = Executor()
migrate = Migrate()  # ✅ YENİ: Artık tabloları silip kurmaya son!

# --- SİSTEM FONKSİYONLARI ---

def log_kaydet(tip, detay):
    """Sistemdeki işlemleri IP ve Cihaz bilgisiyle Kara Kutuya kaydeder."""
    from models import IslemLog
    
    k_id = current_user.id if current_user.is_authenticated else None
    
    yeni_log = IslemLog(
        kullanici_id=k_id,
        islem_tipi=tip,
        detay=detay,
        ip_adresi=request.remote_addr,
        user_agent=request.user_agent.string
    )
    db.session.add(yeni_log)
    db.session.commit()

def guvenli_metin(metin):
    """XSS ve HTML Injection saldırılarına karşı metni temizler."""
    if not metin:
        return metin
    return bleach.clean(metin, tags=[], attributes={}, strip=True)

def api_yanit(basari=True, mesaj="", veri=None, kod=200):
    """Tüm JSON yanıtları için kurumsal standart sarmalayıcı."""
    return jsonify({
        "status": "success" if basari else "error",
        "message": mesaj,
        "data": veri
    }), kod