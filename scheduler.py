from apscheduler.schedulers.background import BackgroundScheduler
from flask_mail import Message
from flask import render_template, url_for
from extensions import db
from models import Malzeme, Kullanici, Havalimani, TR_TZ
from datetime import datetime, timedelta

def bakim_kontrol_ve_mail_at(app):
    """
    Sistemi tarar, her havalimanı için ayrı ayrı HTML mail paketleri oluşturur.
    Sahip ve Genel Müdürlüğü rahatsız etmez, sadece ilgili birim personeline atar.
    """
    with app.app_context():
        # Flask-Mail örneğini ana uygulamadan çekiyoruz
        from app import mail
        
        simdi = datetime.now(TR_TZ).date()
        uyari_siniri = simdi + timedelta(days=7) # 1 hafta önceden alarm ver

        # Tüm havalimanlarını listele (ESB, SAW, ADB vb.) - Silinmişleri yoksay
        havalimanlari = Havalimani.query.filter_by(is_deleted=False).all()

        print(f"\n" + "="*50)
        print(f"⏰ OTOMATİK HTML DENETİMİ - {datetime.now(TR_TZ).strftime('%d.%m.%Y %H:%M')}")
        
        for h in havalimanlari:
            # 1. BU BİRİME ÖZEL: Bakımı yaklaşan malzemeleri bul - Silinmişleri yoksay
            kritik_malzemeler = Malzeme.query.filter(
                Malzeme.havalimani_id == h.id,
                Malzeme.gelecek_bakim_tarihi <= uyari_siniri,
                Malzeme.durum != 'Hurda',
                Malzeme.is_deleted == False
            ).all()

            if kritik_malzemeler:
                # 2. BU BİRİME ÖZEL: Personel ve Yetkilileri bul (Sahip/GM hariç) - Silinmişleri yoksay
                personeller = Kullanici.query.filter(
                    Kullanici.havalimani_id == h.id,
                    Kullanici.rol.in_(['personel', 'yetkili']),
                    Kullanici.is_deleted == False
                ).all()

                # E-posta listesini oluştur (kullanici_adi@sirket.com formatında)
                alici_listesi = [p.kullanici_adi + "@sirket.com" for p in personeller if p.kullanici_adi]

                if alici_listesi:
                    # 3. HTML ŞABLONUNU HAZIRLA (templates/auth/mail_sablonu.html)
                    # url_for(_external=True) mail içindeki linklerin çalışması için şarttır.
                    html_icerik = render_template(
                        'auth/mail_sablonu.html',
                        birim_adi=h.ad,
                        kritik_malzemeler=kritik_malzemeler,
                        panel_url=url_for('inventory.dashboard', _external=True)
                    )

                    msg = Message(
                        subject=f"⚠️ {h.kodu} - Kritik Bakım Bildirimi",
                        recipients=alici_listesi
                    )
                    
                    # HTML desteği olmayan eski cihazlar için düz metin yedeği
                    msg.body = f"Sayın {h.ad} Ekibi, sorumluluğunuzdaki {len(kritik_malzemeler)} malzemenin bakımı geldi."
                    
                    # Zengin HTML İçeriği (Hazırladığımız o şık tasarım)
                    msg.html = html_icerik
                    
                    try:
                        mail.send(msg)
                        print(f"📧 [BAŞARILI] {h.kodu} birimi için {len(alici_listesi)} kişiye HTML mail atıldı.")
                    except Exception as e:
                        print(f"❌ [HATA] {h.kodu} maili gönderilemedi: {e}")
                else:
                    print(f"ℹ️ {h.kodu}: Kritik malzeme var ama alıcı personel bulunamadı.")
            else:
                print(f"✅ {h.kodu}: Acil bakım gerektiren ekipman yok.")
        
        print("="*50 + "\n")

def start_scheduler(app):
    """Zamanlayıcıyı başlatır ve arka planda çalıştırır."""
    scheduler = BackgroundScheduler(timezone="Europe/Istanbul")
    
    # GERÇEK SENARYO: Her sabah saat 09:00'da çalışır
    scheduler.add_job(
        func=bakim_kontrol_ve_mail_at, 
        args=[app], 
        trigger="cron", 
        hour=9, 
        minute=0, 
        id="gunluk_bakim_html_bildirimi"
    )
    
    # TEST SENARYOSU: Her 10 dakikada bir kontrol (İstersen minutes=1 yapabilirsin)
    # scheduler.add_job(func=bakim_kontrol_ve_mail_at, args=[app], trigger="interval", minutes=10)
    
    scheduler.start()