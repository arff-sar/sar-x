import os
from dotenv import load_dotenv
from flask import Flask, render_template, send_file

# ✅ Eklentiler (migrate eklendi)
from extensions import db, login_manager, csrf, limiter, executor, migrate 

from routes.auth import auth_bp
from routes.inventory import inventory_bp
from routes.admin import admin_bp
from routes.api import api_bp
from scheduler import start_scheduler

# .env dosyasını yükle
load_dotenv()

def create_app():
    app = Flask(__name__)
    
    # --- VERİTABANI VE PERFORMANS AYARLARI ---
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///sar_veritabani.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # ✅ PROFESYONEL BAĞLANTI HAVUZU (Connection Pooling)
    # Canlı ortamda (PostgreSQL vb.) veritabanı kilitlenmelerini önler.
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        "pool_size": 10,           # Ana bağlantı havuzu kapasitesi
        "max_overflow": 20,        # Trafik anında açılacak ek kapasite
        "pool_recycle": 3600,      # Bağlantıları saat başı tazele
        "pool_pre_ping": True,     # Kopuk bağlantıları otomatik temizle
    }
    
    # --- GÜVENLİK AYARLARI ---
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'cok_gizli_sar_anahtari')
    app.config['SESSION_COOKIE_HTTPONLY'] = True 
    app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FLASK_ENV') == 'production'
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

    # --- BİLEŞENLERİ BAŞLATMA ---
    db.init_app(app)
    migrate.init_app(app, db) # ✅ Migration sistemi aktif edildi
    login_manager.init_app(app)
    csrf.init_app(app)      
    limiter.init_app(app)   
    executor.init_app(app)  

    @login_manager.user_loader
    def load_user(user_id):
        from models import Kullanici
        # ✅ HATA KORUMASI: user_id 'None' veya boşsa int() çevrimi yapmadan None dön
        if user_id is None or str(user_id) == 'None':
            return None
        try:
            return db.session.get(Kullanici, int(user_id))
        except (ValueError, TypeError):
            return None

    @app.context_processor
    def inject_user_info():
        from flask_login import current_user
        if current_user.is_authenticated:
            return {'rol': current_user.rol, 'kullanici_ad': current_user.tam_ad, 'giren_user': current_user}
        return {'rol': None, 'kullanici_ad': None, 'giren_user': None}

    # --- BLUEPRINT KAYITLARI ---
    app.register_blueprint(auth_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp)

    # --- GLOBAL HATA YÖNETİMİ ---
    @app.errorhandler(404)
    def sayfa_bulunamadi(e):
        return render_template('hata.html', kod=404, mesaj="Aradığınız sayfa mevcut değil veya taşınmış olabilir."), 404

    @app.errorhandler(403)
    def yetkisiz_erisim(e):
        return render_template('hata.html', kod=403, mesaj="Bu sayfayı veya işlemi görüntüleme yetkiniz bulunmuyor."), 403

    @app.errorhandler(500)
    def sunucu_hatasi(e):
        return render_template('hata.html', kod=500, mesaj="Sunucu kaynaklı beklenmedik bir hata oluştu. Lütfen yöneticinize başvurun."), 500

    # --- ANA ROTALAR ---
    @app.route('/')
    def ana_sayfa():
        # ✅ KESİN ÇÖZÜM: Eksik olan modelleri buraya ekledik (Döngüsel import hatası vermemesi için fonksiyon içinde)
        from models import SiteAyarlari, Haber, SliderResim, NavMenu
        
        return render_template('index.html',
                           ayarlar=SiteAyarlari.query.first(),
                           haberler=Haber.query.order_by(Haber.tarih.desc()).all(),
                           sliderlar=SliderResim.query.all(),
                           menuler=NavMenu.query.order_by(NavMenu.sira).all())

    @app.route('/manifest.json')
    def serve_manifest(): 
        return send_file('static/manifest.json')

    @app.route('/sw.js')
    def serve_sw(): 
        return send_file('static/sw.js', mimetype='application/javascript')
        
    start_scheduler(app)
    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)