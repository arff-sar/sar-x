from app import create_app
from extensions import db
from models import Kullanici

app = create_app()

with app.app_context():
    email = 'mehmetcinocevi@gmail.com'
    
    # Hesabı bul (Silinmiş (is_deleted=True) olsa bile bulur)
    admin = Kullanici.query.filter_by(kullanici_adi=email).first()
    
    if not admin:
        print("Hesap bulunamadı, sıfırdan oluşturuluyor...")
        admin = Kullanici(kullanici_adi=email, tam_ad='Mehmet', rol='sahip')
        db.session.add(admin)
    else:
        print("Hesap bulundu, yetkiler ve güvenlik ayarları sıfırlanıyor...")
        admin.rol = 'sahip'
        
    # ✅ KRİTİK DÜZELTME 1: Hesabın "silinmiş" (arşivlenmiş) durumunu kaldırıyoruz!
    admin.is_deleted = False
    admin.deleted_at = None
    
    # ✅ KRİTİK DÜZELTME 2: Senin modelindeki 'pbkdf2:sha256' algoritmasını kullanan orijinal fonksiyonunu çağırıyoruz!
    admin.sifre_set('123456')
    
    db.session.commit()
    print("\n✅ HESAP KESİN OLARAK KURTARILDI VE AKTİF EDİLDİ!")
    print(f"Giriş E-postası: {email}")
    print("Şifre: 123456\n")