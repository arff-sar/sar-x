import qrcode
import io

def generate_qr_data(target_url):
    """
    Verilen URL'yi QR kod görseline dönüştürür.
    Hata düzeltme seviyesi M (Medium) olarak yükseltildi (%15 kayba kadar okunabilir).
    """
    qr = qrcode.QRCode(
        version=None, # Veri boyutuna göre otomatik ayarlanır
        error_correction=qrcode.constants.ERROR_CORRECT_M, # Sahada çizilmelere karşı dirençli
        box_size=10,
        border=4,
    )
    
    try:
        qr.add_data(target_url)
        qr.make(fit=True)

        # Görseli oluştur (L ve M hata düzeltme seviyeleri için optimize edildi)
        img = qr.make_image(fill_color="black", back_color="white")
        
        img_io = io.BytesIO()
        img.save(img_io, 'PNG')
        img_io.seek(0)
        return img_io
    except Exception as e:
        # Üretim ortamında hata yönetimi kritik
        print(f"QR Üretim Hatası: {e}")
        return None