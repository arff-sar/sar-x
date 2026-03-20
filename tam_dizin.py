import os

def temiz_dizin_agaci(yol, girinti="", dosya=None):
    # Filtreler
    yasakli_klasorler = {'venv', '.git', '__pycache__', '.pytest_cache', 'htmlcov', 'instance', 'migrations'}
    yasakli_dosyalar = {'.DS_Store', '.coverage', 'proje_yapisi.txt'}
    yasakli_uzantilar = ('.pyc', '.pyo', '.db')

    try:
        ogeler = sorted(os.listdir(yol))
    except (PermissionError, OSError):
        return

    temiz_ogeler = [o for o in ogeler if o not in yasakli_klasorler and o not in yasakli_dosyalar and not o.endswith(yasakli_uzantilar)]

    for i, oge in enumerate(temiz_ogeler):
        tam_yol = os.path.join(yol, oge)
        is_last = (i == len(temiz_ogeler) - 1)
        isaret = "└── " if is_last else "├── "
        
        satir = f"{girinti}{isaret}{oge}\n"
        print(satir, end="") # Terminale yazdır
        if dosya:
            dosya.write(satir) # Dosyaya yazdır
        
        if os.path.isdir(tam_yol):
            yeni_girinti = girinti + ("    " if is_last else "│   ")
            temiz_dizin_agaci(tam_yol, yeni_girinti, dosya)

if __name__ == "__main__":
    proje_adi = os.path.basename(os.getcwd())
    hedef_dosya = "proje_yapisi.txt"
    
    with open(hedef_dosya, "w", encoding="utf-8") as f:
        baslik = f"📂 {proje_adi}/ (TEMİZLENMİŞ PROJE YAPISI)\n"
        baslik += "="*40 + "\n"
        print(baslik, end="")
        f.write(baslik)
        
        temiz_dizin_agaci(os.getcwd(), dosya=f)
    
    print(f"\n✅ Başarılı! Yapı '{hedef_dosya}' dosyasına kaydedildi.")