from app import create_app
from extensions import db
from models import Havalimani, Kullanici, SiteAyarlari

# Uygulamayı fabrika fonksiyonundan üretiyoruz
app = create_app()

def veritabani_besle():
    with app.app_context():
        print("🚀 Sistem veri besleme (Seeding) işlemi başlatıldı...")
        
        # ⚠️ NOT: db.drop_all() ve db.create_all() KALDIRILDI.
        # Tablo yapısını artık 'flask db upgrade' komutu yönetiyor.
        
        # 1. Başlangıç Havalimanlarını Ekle (Yoksa Ekle)
        print("✈️ Havalimanları kontrol ediliyor...")
        birimler = [
            {"ad": "Ankara Esenboğa Havalimanı", "kodu": "ESB"},
            {"ad": "İstanbul Sabiha Gökçen Havalimanı", "kodu": "SAW"},
            {"ad": "İzmir Adnan Menderes Havalimanı", "kodu": "ADB"}
        ]
        
        for b in birimler:
            mevcut = Havalimani.query.filter_by(kodu=b['kodu']).first()
            if not mevcut:
                yeni_h = Havalimani(ad=b['ad'], kodu=b['kodu'])
                db.session.add(yeni_h)
                print(f"   [+] {b['kodu']} birimi eklendi.")
        
        db.session.flush() # ID'lerin oluşması için geçici iteleme
        
        # 2. Sistem Sahibi (Mehmet) - Yoksa Ekle
        admin_mail = "mehmetcinocevi@gmail.com"
        admin = Kullanici.query.filter_by(kullanici_adi=admin_mail).first()
        
        if not admin:
            print("👑 Sistem Sahibi oluşturuluyor...")
            kurucu = Kullanici(
                kullanici_adi=admin_mail,
                tam_ad="Mehmet", 
                rol="sahip",
                havalimani_id=None 
            )
            kurucu.sifre_set("123456") 
            db.session.add(kurucu)
            print(f"   [+] {admin_mail} başarıyla tanımlandı.")
        
        # 3. Genel Müdürlük ve Örnek Personel - Yoksa Ekle
        if not Kullanici.query.filter_by(kullanici_adi="gm@sarx.com").first():
            gm = Kullanici(kullanici_adi="gm@sarx.com", tam_ad="GM Denetçi", rol="genel_mudurluk")
            gm.sifre_set("123456")
            db.session.add(gm)
            print("   [+] Genel Müdürlük hesabı oluşturuldu.")

        # 4. Varsayılan Site Ayarları - Yoksa Ekle
        if not SiteAyarlari.query.first():
            ayarlar = SiteAyarlari(
                baslik="SAR-X ARFF", 
                alt_metin="Havalimanı Envanter ve Bakım Yönetim Sistemi"
            )
            db.session.add(ayarlar)
            print("🌐 Varsayılan site ayarları eklendi.")
        
        db.session.commit()
        
        print("-" * 50)
        print("✅ İŞLEM TAMAMLANDI!")
        print(f"Yönetici Paneli: {admin_mail} / 123456")
        print("Artık 'python app.py' ile sistemi başlatabilirsiniz.")
        print("-" * 50)

if __name__ == "__main__":
    veritabani_besle()