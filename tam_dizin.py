import os

def tam_dizin_agaci(yol, girinti=""):
    try:
        # Klasördeki her şeyi (gizli dosyalar dahil) listele
        ogeler = sorted(os.listdir(yol))
    except (PermissionError, OSError):
        # Yetki olmayan klasörleri sessizce atla
        return

    for i, oge in enumerate(ogeler):
        tam_yol = os.path.join(yol, oge)
        is_last = (i == len(ogeler) - 1)
        
        # Görsel ağaç yapısı işaretleri
        isaret = "└── " if is_last else "├── "
        print(f"{girinti}{isaret}{oge}")
        
        # Eğer bu bir klasörse, içine girip aynı işlemi tekrarla
        if os.path.isdir(tam_yol):
            yeni_girinti = girinti + ("    " if is_last else "│   ")
            tam_dizin_agaci(tam_yol, yeni_girinti)

if __name__ == "__main__":
    # Şu an bulunduğun klasörü başlangıç noktası al
    proje_yolu = os.getcwd()
    print(f"📂 {proje_yolu}")
    tam_dizin_agaci(proje_yolu)